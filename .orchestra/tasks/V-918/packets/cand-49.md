# Candidate cand-49

## ORIGIN commit 8ebed917ea (2026-08-07): #150: #150: молчащий источник usage пишет NULL и строку в журнал вместо нуля
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/db.py b/app/db.py
index 762e69f3d..73d2eb14b 100644
--- a/app/db.py
+++ b/app/db.py
@@ -1708,17 +1708,17 @@ def voice_cost_add(session_name: str, scope: str, duration_sec: float,
 
 def voice_cost_total_usd() -> float:
     with _conn() as c:
         return float(c.execute(
             "SELECT COALESCE(SUM(cost_usd), 0) FROM voice_costs"
         ).fetchone()[0])
 
 
-def usage_save_snapshot(five_hour_pct: float, seven_day_pct: float,
+def usage_save_snapshot(five_hour_pct: float | None, seven_day_pct: float | None,
                         five_hour_resets_at: str, seven_day_resets_at: str,
                         total_cost_usd: float, active_agents: int,
                         providers: dict | None = None) -> None:
     with _conn() as c:
         c.execute(
             """INSERT INTO usage_snapshots
                (ts, five_hour_pct, seven_day_pct, five_hour_resets_at,
                 seven_day_resets_at, total_cost_usd, active_agents, provider_usage)
@@ -1731,27 +1731,30 @@ def usage_save_snapshot(five_hour_pct: float, seven_day_pct: float,
         )
 
 
 def _usage_providers_from_row(row: dict) -> dict:
     providers = json.loads(row.pop("provider_usage", "{}") or "{}")
     if providers:
         return providers
     windows = []
-    if row.get("five_hour_resets_at") or row.get("five_hour_pct"):
+    # NULL в колонке = источник молчал (#150). Окно без числа — не точка данных:
+    # отдать его с `utilization: None` значило бы переложить ноль на потребителя.
+    fh_pct, sd_pct = row.get("five_hour_pct"), row.get("seven_day_pct")
+    if fh_pct is not None and (row.get("five_hour_resets_at") or fh_pct):
         windows.append({
             "id": "five_hour", "label": "5h",
-            "utilization": row.get("five_hour_pct", 0),
+            "utilization": fh_pct,
             "window_minutes": 300,
             "resets_at": row.get("five_hour_resets_at") or None,
         })
-    if row.get("seven_day_resets_at") or row.get("seven_day_pct"):
+    if sd_pct is not None and (row.get("seven_day_resets_at") or sd_pct):
         windows.append({
             "id": "seven_day", "label": "7d",
-            "utilization": row.get("seven_day_pct", 0),
+            "utilization": sd_pct,
             "window_minutes": 10080,
             "resets_at": row.get("seven_day_resets_at") or None,
         })
     return {"anthropic": {"label": "Claude", "windows": windows}} if windows else {}
 
 
 def usage_history_oldest_ts() -> str:
     """Время самого первого снимка — по нему фронт понимает, есть ли что грузить дальше."""
diff --git a/app/routes/system.py b/app/routes/system.py
index 68e942d5b..6433e9310 100644
--- a/app/routes/system.py
+++ b/app/routes/system.py
@@ -902,21 +902,25 @@ async def _collect_usage_snapshot() -> None:
     from app.backend_codex import CODEX_BIN
     from app.db import usage_save_snapshot
     anthropic_data = None
     anthropic_error = ""
     token, refresh_token, _tier = _read_oauth_credentials()
     if token:
         try:
             anthropic_data = await _fetch_anthropic_usage(token)
-        except PermissionError:
+        except PermissionError as e:
+            # Причину пишем СРАЗУ: если обновление токена не поможет, дальше её взять
+            # будет неоткуда и отказ станет безымянным.
+            anthropic_error = f"{type(e).__name__}: {e}"
             if refresh_token:
                 new_token = await _refresh_oauth_token(refresh_token)
                 if new_token:
                     anthropic_data = await _fetch_anthropic_usage(new_token)
+                    anthropic_error = ""
         except Exception as e:
             anthropic_data = None
             anthropic_error = f"{type(e).__name__}: {e}"
     if anthropic_data:
         _usage_cache["data"] = anthropic_data
         _usage_cache["ts"] = time.time()
         _save_usage_cache()
 
@@ -956,25 +960,33 @@ async def _collect_usage_snapshot() -> None:
     ):
         if asked and not answered:
             providers[provider_id] = {
                 "label": label,
                 "windows": [],
                 "status": "unavailable",
                 "error": error or "no data",
             }
+            logger.warning(
+                "usage snapshot: %s asked and did not answer — %s",
+                provider_id, error or "empty response",
+            )
     if not providers:
         return
 
     fh = (anthropic_data or {}).get("five_hour") or {}
     sd = (anthropic_data or {}).get("seven_day") or {}
     cost = sum(s.cost_usd for s in manager.sessions.values())
     active = sum(1 for s in manager.sessions.values() if s.status.value == "running")
+    # Ноль здесь означал бы «квота не израсходована» — ровно то, чего не знаем, когда
+    # источник молчал. Пишем NULL: агрегаты SQLite такие строки пропускают, а график
+    # рисует разрыв вместо падения в пол. Саму строку оставляем — в ней ещё живут
+    # codex/grok и локальные cost/active, которые от молчания anthropic не пострадали.
     usage_save_snapshot(
-        fh.get("utilization", 0), sd.get("utilization", 0),
+        fh.get("utilization"), sd.get("utilization"),
         fh.get("resets_at", ""), sd.get("resets_at", ""),
         round(cost, 4), active, providers=providers,
     )
 
 
 async def _usage_snapshot_loop():
     await asyncio.sleep(10)
     while True:
diff --git a/tests/test_usage_snapshot.py b/tests/test_usage_snapshot.py
index 98fab4829..443bbad1e 100644
--- a/tests/test_usage_snapshot.py
+++ b/tests/test_usage_snapshot.py
@@ -1,15 +1,16 @@
 """Снимок истории квот не должен врать.
 
 Три состояния провайдера обязаны быть различимы в `provider_usage`:
 не настроен → ключа нет; спросили и молчит → `status="unavailable"`;
 ответил → окна с числами (в том числе честные 100% на исчерпанном лимите).
 """
 import json
+import logging
 
 import pytest
 
 from app.routes import system
 
 
 @pytest.fixture
 def saved(monkeypatch):
@@ -142,8 +143,109 @@ async def test_snapshot_still_written_when_only_codex_answers(monkeypatch, saved
 def test_history_row_roundtrips_unavailable_marker():
     """Метка должна доезжать до графика через usage_get_history."""
     from app.db import _usage_providers_from_row
 
     marker = {"codex": {"label": "Codex", "windows": [], "status": "unavailable"}}
     row = {"five_hour_pct": 0, "provider_usage": json.dumps(marker)}
 
     assert _usage_providers_from_row(row)["codex"]["status"] == "unavailable"
+
+
+# --- #150: молчащий источник не пишет ноль в выделенные колонки ---
+
+
+@pytest.fixture
+def saved_columns(monkeypatch, saved):
+    """Полные аргументы записи снимка — `saved` отдаёт только `providers`."""
+    calls = []
+    import app.db
+
+    monkeypatch.setattr(app.db, "usage_save_snapshot",
+                        lambda *args, **kwargs: calls.append(args))
+    return calls
+
+
+@pytest.mark.asyncio
+async def test_answered_source_writes_the_number(monkeypatch, saved_columns):
+    _anthropic_ok(monkeypatch)  # five_hour: utilization 12, seven_day отсутствует
+    _codex(monkeypatch, error=RuntimeError("no codex"))
+
+    await system._collect_usage_snapshot()
+
+    five_hour, seven_day = saved_columns[0][0], saved_columns[0][1]
+    assert five_hour == 12
+    # Окна, которого в ответе не было, тоже нет — а не ноль.
+    assert seven_day is None
+
+
+@pytest.mark.asyncio
+async def test_real_zero_is_written_as_zero(monkeypatch, saved_columns):
+    """Сброшенное окно — законный ноль, его терять нельзя."""
+    async def _fetch(_token):
+        return {"five_hour": {"utilization": 0, "resets_at": ""},
+                "seven_day": {"utilization": 69, "resets_at": "2026-08-10T00:00:00Z"}}
+
+    monkeypatch.setattr(system, "_fetch_anthropic_usage", _fetch)
+    _codex(monkeypatch, error=RuntimeError("no codex"))
+
+    await system._collect_usage_snapshot()
+
+    assert saved_columns[0][0] == 0
+    assert saved_columns[0][1] == 69
+
+
+@pytest.mark.asyncio
+async def test_silent_source_writes_no_number_and_names_the_cause(
+    monkeypatch, saved_columns, caplog,
+):
+    async def _fetch(_token):
+        raise TimeoutError("read timed out")
+
+    monkeypatch.setattr(system, "_fetch_anthropic_usage", _fetch)
+    _codex(monkeypatch, result={"plan_type": "pro", "rate_limits": {}})
+
+    with caplog.at_level(logging.WARNING, logger="orchestra.system"):
+        await system._collect_usage_snapshot()
+
+    assert saved_columns[0][0] is None
+    assert saved_columns[0][1] is None
+    warned = [r.getMessage() for r in caplog.records if "did not answer" in r.getMessage()]
+    assert len(warned) == 1
+    assert "anthropic" in warned[0]
+    assert "TimeoutError" in warned[0], warned[0]
+
+
+@pytest.mark.asyncio
+async def test_expired_credentials_are_named_not_swallowed(monkeypatch, saved_columns, caplog):
+    """401 без пригодного refresh — отказ обязан остаться именованным."""
+    async def _fetch(_token):
+        raise PermissionError("401 Unauthorized")
+
+    monkeypatch.setattr(system, "_fetch_anthropic_usage", _fetch)
+    monkeypatch.setattr(system, "_read_oauth_credentials", lambda: ("token", "refresh", None))
+
+    async def _refresh(_rt):
+        return ""
+
+    monkeypatch.setattr(system, "_refresh_oauth_token", _refresh)
+    _codex(monkeypatch, result={"plan_type": "pro", "rate_limits": {}})
+
+    with caplog.at_level(logging.WARNING, logger="orchestra.system"):
+        await system._collect_usage_snapshot()
+
+    assert saved_columns[0][0] is None
+    warned = [r.getMessage() for r in caplog.records if "did not answer" in r.getMessage()]
+    assert "PermissionError" in warned[0], warned[0]
+
+
+def test_null_column_yields_no_window(monkeypatch):
+    """Строка с NULL не превращается обратно в точку графика."""
+    from app.db import _usage_providers_from_row
+
+    silent = {"provider_usage": "{}", "five_hour_pct": None, "seven_day_pct": None,
+              "five_hour_resets_at": "2026-08-10T00:00:00Z", "seven_day_resets_at": ""}
+    assert _usage_providers_from_row(silent) == {}
+
+    answered = {"provider_usage": "{}", "five_hour_pct": 0.0, "seven_day_pct": 69.0,
+                "five_hour_resets_at": "2026-08-10T00:00:00Z", "seven_day_resets_at": ""}
+    windows = _usage_providers_from_row(answered)["anthropic"]["windows"]
+    assert [w["utilization"] for w in windows] == [0.0, 69.0]


## LATER FIX 8dd91d5e11 (59.1 days later): V-700: #V-700: fix dashboard CI and i18n issues
lines of origin it changed/deleted: 2
(code only, capped 400 lines)

V-700: #V-700: fix dashboard CI and i18n issues

Orchestra-Operation: 135686ca-629c-47d3-b6b6-7d67924f8061


diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
index 6335cc983..87456a56e 100644
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -28,20 +28,20 @@ jobs:
       fail-fast: false
       matrix:
         shard: [0, 1, 2, 3, 4, 5]
     steps:
       # Часть тестов сравнивает рабочее дерево с `main` и ходит к родительским
       # коммитам. По умолчанию checkout берёт ОДИН коммит ОДНОЙ ветки, и такой
       # тест падает не по существу: `git show main:app/static/js/app.js` отвечает
       # `exit 128`. `fetch-depth: 0` даёт полную историю и все ветки.
-      - uses: actions/checkout@v4
+      - uses: actions/checkout@v5
         with:
           fetch-depth: 0
-      - uses: astral-sh/setup-uv@v4
+      - uses: astral-sh/setup-uv@v7
       - run: uv sync --dev
       # На образе ubuntu-latest ffmpeg не предустановлен, а тест длительности
       # аудио обязан звать НАСТОЯЩИЙ ffprobe — подменять бинарь значило бы
       # проверять заглушку вместо разбора контейнера.
       - run: sudo apt-get update && sudo apt-get install -y ffmpeg
       # `uv sync` ставит пакет playwright, но не бинарники браузеров. Без этого
       # шага все браузерные тесты молча скипались бы, и CI был бы зелёным, ничего
       # про фронт не проверив.
@@ -77,18 +77,18 @@ jobs:
     # из гейта, не убиваем»), поэтому джоба помечена `continue-on-error` — она остаётся
     # СИГНАЛОМ, видимым в списке проверок, но не решает судьбу прогона. Гоняются те же
     # 167 узлов, что снимает с себя merge-гейт: состав закреплён
     # `tests/test_merge_test_gate.py::test_browser_inventory_is_explicit`.
     runs-on: ubuntu-latest
     continue-on-error: true
     timeout-minutes: 20
     steps:
-      - uses: actions/checkout@v4
+      - uses: actions/checkout@v5
         with:
           fetch-depth: 0
-      - uses: astral-sh/setup-uv@v4
+      - uses: astral-sh/setup-uv@v7
       - run: uv sync --dev
       - run: uv run playwright install --with-deps chromium
       - name: pytest browser
         run: |
           PYTHONUNBUFFERED=1 /usr/bin/time -v uv run pytest -v -rf --timeout=30 \
             -m "browser" tests/
diff --git a/app/db.py b/app/db.py
index 0672cd3c6..fafad79cf 100644
--- a/app/db.py
+++ b/app/db.py
@@ -2372,24 +2372,24 @@ def usage_exchange_rate(hours: int = 72, min_five_hour_pct: float = 30.0) -> dic
 def _usage_providers_from_row(row: dict) -> dict:
     providers = json.loads(row.pop("provider_usage", "{}") or "{}")
     if providers:
         return providers
     windows = []
     # NULL в колонке = источник молчал (#150). Окно без числа — не точка данных:
     # отдать его с `utilization: None` значило бы переложить ноль на потребителя.
     fh_pct, sd_pct = row.get("five_hour_pct"), row.get("seven_day_pct")
-    if fh_pct is not None and (row.get("five_hour_resets_at") or fh_pct):
+    if fh_pct is not None and (row.get("five_hour_resets_at") or fh_pct == 0):
         windows.append({
             "id": "five_hour", "label": "5h",
             "utilization": fh_pct,
             "window_minutes": 300,
             "resets_at": row.get("five_hour_resets_at") or None,
         })
-    if sd_pct is not None and (row.get("seven_day_resets_at") or sd_pct):
+    if sd_pct is not None and (row.get("seven_day_resets_at") or sd_pct == 0):
         windows.append({
             "id": "seven_day", "label": "7d",
             "utilization": sd_pct,
             "window_minutes": 10080,
             "resets_at": row.get("seven_day_resets_at") or None,
         })
     return {"anthropic": {"label": "Claude", "windows": windows}} if windows else {}
 
diff --git a/app/quota_gate.py b/app/quota_gate.py
index 71c3f0793..cfbe175e1 100644
--- a/app/quota_gate.py
+++ b/app/quota_gate.py
@@ -265,17 +265,17 @@ SPARK_MODEL = "gpt-5.3-codex-spark"
 LUNA_MODEL = "gpt-5.6-luna"
 
 # Полосы, которым диагональ применяется. Всё, чего здесь нет, ограничено только
 # жёстким стопом.
 GATED_LANES = _env_gated_lanes("QUOTA_GATED_LANES", _ENV_GATED_LANES_DEFAULT)
 CURVED_LANES = _env_gated_lanes("QUOTA_CURVED_LANES", _ENV_CURVED_LANES_DEFAULT)
 
 LANE_LABELS = {
-    "claude": "Claude-воркеры",
+    "claude": "Claude workers",
     "sol": "Sol",
     "luna": "Luna",
     "spark": "Spark",
 }
 
 # Временное снятие гейта владельцем (#V-578). Снимается ТОЛЬКО наша дополнительная
 # осторожность — диагональ и потолок отдельной полосы; общий жёсткий стоп остаётся,
 # потому что за ним стоит предел провайдера, а не наше правило: пропустив туда, мы
diff --git a/app/static/js/analytics.js b/app/static/js/analytics.js
index 00675e456..d9c659508 100644
--- a/app/static/js/analytics.js
+++ b/app/static/js/analytics.js
@@ -644,28 +644,31 @@ function _analyticsCapacity(provider) {
 
 function _analyticsKpi(label, value, detail) {
     return `<article><span>${label}</span><strong>${value}</strong><small>${detail}</small></article>`;
 }
 
 function _analyticsMoney(value) {
     if (value == null || Number.isNaN(Number(value))) return '—';
     const amount = Number(value);
-    return `${MODEL_COST_CURRENCY}${amount.toLocaleString('ru-RU', { minimumFractionDigits: amount < 100 ? 2 : 0, maximumFractionDigits: 2 })}`;
+    const locale = typeof orchLang === 'function' && orchLang() === 'ru' ? 'ru-RU' : 'en-US';
+    return `${MODEL_COST_CURRENCY}${amount.toLocaleString(locale, { minimumFractionDigits: amount < 100 ? 2 : 0, maximumFractionDigits: 2 })}`;
 }
 
 function _analyticsNumber(value) {
-    return Number(value || 0).toLocaleString('ru-RU');
+    const locale = typeof orchLang === 'function' && orchLang() === 'ru' ? 'ru-RU' : 'en-US';
+    return Number(value || 0).toLocaleString(locale);
 }
 
 function _analyticsDateTime(value) {
     if (!value) return '—';
     const date = new Date(value);
     if (Number.isNaN(date.getTime())) return _analyticsEsc(String(value));
-    return date.toLocaleString('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
+    const locale = typeof orchLang === 'function' && orchLang() === 'ru' ? 'ru-RU' : 'en-US';
+    return date.toLocaleString(locale, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
 }
 
 function _analyticsDuration(seconds) {
     const total = Number(seconds || 0);
     if (total < 60) return T('{sec} sec', {sec: Math.round(total)});
     return T('{min} min {sec} sec', {min: Math.floor(total / 60), sec: Math.round(total % 60)});
 }
 
diff --git a/app/static/js/i18n.js b/app/static/js/i18n.js
index 4ebaf5fc9..1b1b8edb5 100644
--- a/app/static/js/i18n.js
+++ b/app/static/js/i18n.js
@@ -122,16 +122,17 @@
     'In progress': 'Идёт',
     'Ready': 'Готово',
     'Result': 'Результат',
     'Rolled back': 'Откат',
     'Tool': 'Инструмент',
     'Output shortened for display ({n} source bytes)': 'Показана часть вывода (исходный размер: {n} байт)',
     'Created': 'Создано',
     'Created:': 'Создана:',
+    'Claude workers': 'Claude-воркеры',
     'Creating...': 'Создание…',
     'Critical': 'Критический',
     'Current turn': 'Текущий ход',
     'DESCRIPTION': 'ОПИСАНИЕ',
     'DONE': 'ГОТОВО',
     'Daily': 'Сутки',
     'Data unavailable': 'Данные недоступны',
     'Delegation': 'Делегирование',
diff --git a/app/static/js/quota-lines.js b/app/static/js/quota-lines.js
index e2317f9f9..455af7756 100644
--- a/app/static/js/quota-lines.js
+++ b/app/static/js/quota-lines.js
@@ -107,17 +107,17 @@ function _qlAllLanes() {
     for (const bucket of (_quotaLinesData?.buckets || [])) {
         for (const lane of (bucket.lanes || [])) lanes.push(lane);
     }
     return lanes;
 }
 
 function _qlLaneLabel(laneId) {
     const found = _qlAllLanes().find(lane => lane.lane === laneId);
-    return found ? (found.label || laneId) : laneId;
+    return T(found ? (found.label || laneId) : laneId);
 }
 
 // Hard-stop ceilings in words: Sol has its own (95%), others share one. Label
 // must match the `ql-hard` lines on the chart — both use the same numbers.
 function _qlCeilingText(rule) {
     const own = Object.entries(rule.lane_hard_stop_pct || {})
         .filter(([, pct]) => Number.isFinite(Number(pct)))
         .sort(([a], [b]) => a.localeCompare(b))
@@ -156,17 +156,17 @@ function _qlGateState() {
             text: T('gate LIFTED — diagonal holds no lanes, only ceiling remains: {ceiling}', {
                 ceiling: ceilings,
             }),
         };
     }
     const held = rule.gated_lanes.map(_qlLaneLabel);
     const free = _qlAllLanes()
         .filter(lane => !rule.gated_lanes.includes(lane.lane))
-        .map(lane => lane.label || lane.lane);
+        .map(lane => T(lane.label || lane.lane));
     const tail = free.length ? ` · ${T('outside gate')}: ${free.join(', ')}` : '';
     return {state: 'on', text: T('gate ON: {held}{tail} · ceiling: {ceiling}', {
         held: held.join(', '),
         tail,
         ceiling: ceilings,
     })};
 }
 
@@ -304,17 +304,17 @@ function _qlTimelineSvg(panel, rule) {
         }
     }
     // Facts stop at now. Add a current sample there; the right half is policy only.
     let pointIndex = 0;
     for (const lane of _qlLanes(panel)) {
         const point = _qlPoint(lane.bucket);
         if (!point) continue;
         const color = _QL_LANE_COLORS[lane.lane] || 'var(--ink)';
-        p.push(`<circle data-ql-timeline-point="${_escHtml(lane.lane)}" cx="${x(now)}" cy="${y(point.util)}" r="${5.5 + pointIndex * 2}" fill="none" stroke="${color}" stroke-width="2.5"><title>${_escHtml(lane.label || lane.lane)}: ${_qlNum(point.util)}%</title></circle>`);
+        p.push(`<circle data-ql-timeline-point="${_escHtml(lane.lane)}" cx="${x(now)}" cy="${y(point.util)}" r="${5.5 + pointIndex * 2}" fill="none" stroke="${color}" stroke-width="2.5"><title>${_escHtml(T(lane.label || lane.lane))}: ${_qlNum(point.util)}%</title></circle>`);
         pointIndex++;
     }
     p.push(`<line class="ql-now" x1="${x(now)}" y1="${_QL_MT}" x2="${x(now)}" y2="${_QL_MT + _QL_PH}"/>`);
     const histories = new Set();
     for (const bucket of panel.buckets.map(_qlBucket).filter(Boolean)) {
         if (histories.has(bucket.bucket)) continue;
         histories.add(bucket.bucket);
         const points = bucket.timeline?.points || [];
@@ -369,17 +369,17 @@ function _qlChartSvg(panel, rule) {
     p.push(`<line class="ql-hard" x1="${_qlX(0)}" y1="${_qlY(hard)}" x2="${_qlX(1)}" y2="${_qlY(hard)}"/>`);
     p.push(`<text class="ql-axis ql-halo" x="${_QL_ML + _QL_PW - 4}" y="${_qlY(hard) - 7}" text-anchor="end" fill="#fdba74">${T('hard {pct}% — stop for lanes without own ceiling', {pct: _qlNum(hard)})}</text>`);
     // Lane-specific line for lane with lower ceiling: one common line would lie
     // that the expensive lane runs to the last pool percent.
     for (const lane of _qlLanes(panel)) {
         const stop = _qlHardStop(rule, lane.lane);
         if (!(stop < hard)) continue;
         p.push(`<line class="ql-hard" data-ql-hard-lane="${_escHtml(lane.lane)}" x1="${_qlX(0)}" y1="${_qlY(stop)}" x2="${_qlX(1)}" y2="${_qlY(stop)}"/>`);
-        p.push(`<text class="ql-axis ql-halo" x="${_QL_ML + _QL_PW - 4}" y="${_qlY(stop) - 7}" text-anchor="end" fill="#fdba74">${T('{label} — hard {pct}%', {label: _escHtml(lane.label || lane.lane), pct: _qlNum(stop)})}</text>`);
+        p.push(`<text class="ql-axis ql-halo" x="${_QL_ML + _QL_PW - 4}" y="${_qlY(stop) - 7}" text-anchor="end" fill="#fdba74">${T('{label} — hard {pct}%', {label: _escHtml(T(lane.label || lane.lane)), pct: _qlNum(stop)})}</text>`);
     }
     p.push(`<line class="ql-orch" x1="${_qlX(0)}" y1="${_qlY(100)}" x2="${_qlX(1)}" y2="${_qlY(100)}"/>`);
     p.push(`<text class="ql-axis ql-halo" x="${_QL_ML + 6}" y="${_qlY(100) + 15}" fill="#c7d2fe">${T('orchestrator always runs — no limit')}</text>`);
 
     const byBucket = [];
     for (const id of panel.buckets) {
         const bucket = _qlBucket(id);
         if (!bucket) continue;
@@ -426,17 +426,17 @@ function _qlChartSvg(panel, rule) {
         }
         const x = _qlX(point.progress), y = _qlY(point.util);
         p.push(`<line class="ql-cursor" x1="${x}" y1="${_QL_MT}" x2="${x}" y2="${_QL_MT + _QL_PH}"/>`);
         const offset = _QL_LANE_MARKERS[i] || _QL_LANE_MARKERS[0];
         const right = point.progress > 0.6;
         const dx = right ? -Math.abs(offset.dx) : offset.dx;
         const dy = offset.dy;
         const color = _QL_LANE_COLORS[lane.lane] || 'var(--ink)';
-        const label = _escHtml(String(lane.label || lane.lane));
+        const label = _escHtml(String(T(lane.label || lane.lane)));
         const markerClass = `ql-point-${lane.lane || 'lane'}`;
         const anchor = right ? 'end' : 'start';
         const hardY = _qlY(hard);
         const baseY = _qlY(point.util + 0);
         const rawLabelY = y + dy;
         const avoidHardY = Math.abs(baseY - hardY) < 8 || Math.abs(rawLabelY - hardY) < 28;
         const stackedLabelY = _qlPlaceY(avoidHardY ? hardY + 22 : rawLabelY, usedLabelBands);
         const stackedDetailY = _qlPlaceY(stackedLabelY + 15, usedLabelBands);
@@ -482,18 +482,18 @@ function _qlVerdict(panel) {
         && l.bucket.fresh !== false
         && l.release_status !== 'no_data');
     if (!lanes.length) return {text: T('no data — server did not send allowance lanes'), nodata: true};
     if (!known.length) return {text: T('no data — no pool telemetry, gate returns unknown'), nodata: true};
     const partial = known.length < lanes.length;
     if (partial) {
         return {text: T('no data — some lanes missing telemetry'), nodata: true, blocked: false};
     }
-    const blocked = known.filter(l => l.blocked).map(l => l.label || l.lane);
-    const open = known.filter(l => !l.blocked).map(l => l.label || l.lane);
+    const blocked = known.filter(l => l.blocked).map(l => T(l.label || l.lane));
+    const open = known.filter(l => !l.blocked).map(l => T(l.label || l.lane));
     const parts = [];
     if (blocked.length) parts.push(T('{lanes} — blocked', {lanes: blocked.join(', ')}));
     if (open.length) parts.push(T('{lanes} — running', {lanes: open.join(', ')}));
     return {
         text: parts.join(' · '),
         nodata: false,
         blocked: blocked.length > 0,
     };
@@ -510,20 +510,20 @@ function _qlPanelHtml(panel) {
         </section>`;
     }
     const lanes = _qlLanes(panel).map(lane => {
         const nodata = !lane.bucket?.data_available
             || lane.bucket.fresh === false
             || lane.release_status === 'no_data';
         const state = nodata ? 'nodata' : lane.blocked ? 'blocked' : 'open';
         const word = _qlLaneSummary(lane);
-        return `<span class="ql-badge ql-badge-${state}" data-ql-lane="${_escHtml(lane.lane)}">${_escHtml(lane.label || lane.lane)}: <b>${word}</b>${lane.gated ? '' : T(' <i>no diagonal</i>')}</span>`;
+        return `<span class="ql-badge ql-badge-${state}" data-ql-lane="${_escHtml(lane.lane)}">${_escHtml(T(lane.label || lane.lane))}: <b>${word}</b>${lane.gated ? '' : T(' <i>no diagonal</i>')}</span>`;
     }).join('');
     const reasons = _qlLanes(panel).filter(l => l.blocked && l.reason)
-        .map(l => `<li><b>${_escHtml(l.label || l.lane)}</b> — ${_escHtml(l.reason)}</li>`).join('');
+        .map(l => `<li><b>${_escHtml(T(l.label || l.lane))}</b> — ${_escHtml(l.reason)}</li>`).join('');
     const chart = _qlChartSvg(panel, rule);
     const traceNotices = (chart.traceNotices || [])
         .map(item => `<div class="ql-trace-msg" data-ql-trace-msg="${_escHtml(item.bucket)}">${T('{label}: no history for this window', {label: _escHtml(item.label)})}</div>`)
         .join('');
     return `<section class="ql-panel" data-ql-panel="${_escHtml(panel.key)}">
         <div class="ql-head"><h3>${_escHtml(panel.title)}</h3><span>${_escHtml(panel.sub)}</span></div>
         <div class="ql-head ql-timeline-head"><h4>${T('Quota timeline')}</h4><span>${T('±3.5 days · current time centered · Krasnoyarsk')}</span></div>
         ${_qlTimelineSvg(panel, rule)}
diff --git a/app/static/js/usage.js b/app/static/js/usage.js
index 2df5950d3..48f4b5262 100644
--- a/app/static/js/usage.js
+++ b/app/static/js/usage.js
@@ -38,17 +38,18 @@ function _resetCountdown(isoStr) {
     if (h >= 24) { const d = Math.floor(h / 24); return `${d}d ${h % 24}h ${m}m`; }
     return `${h}h ${m}m`;
 }
 
 function _krskReset(isoStr) {
     if (!isoStr) return '';
     const at = new Date(isoStr);
     if (Number.isNaN(at.getTime())) return '';
-    return new Intl.DateTimeFormat('ru-RU', {
+    const locale = typeof orchLang === 'function' && orchLang() === 'ru' ? 'ru-RU' : 'en-US';
+    return new Intl.DateTimeFormat(locale, {
         timeZone: 'Asia/Krasnoyarsk',
         weekday: 'short', day: 'numeric', month: 'short',
         hour: '2-digit', minute: '2-digit',
     }).format(at);
 }
 
 function _resetPctNum(isoStr, windowMs) {
     if (!isoStr) return null;
@@ -602,21 +603,21 @@ function _historyProviders(row) {
     if (row?.providers && typeof row.providers === 'object') return row.providers;
     const windows = [];
     // null в колонке = источник не ответил (#150). `Number(null)` даёт 0, и окно
     // с нулём нарисовало бы провал в пол там, где данных нет вовсе
     const pct = value => (value == null || value === '' || !Number.isFinite(Number(value)))
         ? null : Number(value);
     const fiveHour = pct(row?.five_hour_pct);
     const sevenDay = pct(row?.seven_day_pct);
-    if (fiveHour !== null && (row.five_hour_resets_at || fiveHour)) {
+    if (fiveHour !== null && (row.five_hour_resets_at || fiveHour === 0)) {
         windows.push({id:'five_hour', label:'5h', utilization:fiveHour,
             window_minutes:300, resets_at:row.five_hour_resets_at || null});
     }
-    if (sevenDay !== null && (row.seven_day_resets_at || sevenDay)) {
+    if (sevenDay !== null && (row.seven_day_resets_at || sevenDay === 0)) {
         windows.push({id:'seven_day', label:'7d', utilization:sevenDay,
             window_minutes:10080, resets_at:row.seven_day_resets_at || null});
     }
     return windows.length ? {anthropic:{label:'Claude', windows}} : {};
 }
 
 function _usageHistorySeries(data) {
     const series = new Map();
diff --git a/tests/test_dashboard_i18n_formatting.py b/tests/test_dashboard_i18n_formatting.py
new file mode 100644
index 000000000..7aaa7d427
--- /dev/null
+++ b/tests/test_dashboard_i18n_formatting.py
@@ -0,0 +1,57 @@
+from pathlib import Path
+
+import pytest
+from playwright.sync_api import sync_playwright
+
+from app.quota_gate import LANE_LABELS
+
+ROOT = Path(__file__).parent.parent
+
+
+@pytest.fixture(scope="module")
+def browser():
+    with sync_playwright() as playwright:
+        instance = playwright.chromium.launch(headless=True)
+        yield instance
+        instance.close()
+
+
+def _formatting_page(browser, language):
+    context = browser.new_context()
+    context.add_init_script(f"localStorage.setItem('orch_lang', '{language}')")
+    page = context.new_page()
+    page.route("http://harness.local/**", lambda route: route.fulfill(
+        status=200, content_type="text/html", body="<body></body>"))
+    page.goto("http://harness.local/")
+    page.add_script_tag(path=str(ROOT / "app/static/js/utils.js"))
+    page.add_script_tag(path=str(ROOT / "app/static/js/i18n.js"))
+    page.add_script_tag(path=str(ROOT / "app/static/js/usage.js"))
+    page.add_script_tag(path=str(ROOT / "app/static/js/analytics.js"))
+    return context, page
+
+
+def test_dashboard_numbers_and_dates_follow_the_selected_language(browser):
+    assert LANE_LABELS["claude"] == "Claude workers"
+    values = {}