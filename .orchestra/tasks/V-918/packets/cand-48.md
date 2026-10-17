# Candidate cand-48

## ORIGIN commit 20703eb661 (2026-06-09): #75: #75: GitHub Actions CI + fix broken test collections
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
new file mode 100644
index 000000000..c10eed817
--- /dev/null
+++ b/.github/workflows/ci.yml
@@ -0,0 +1,15 @@
+name: CI
+on:
+  push:
+    branches: [main]
+  pull_request:
+    branches: [main]
+
+jobs:
+  test:
+    runs-on: ubuntu-latest
+    steps:
+      - uses: actions/checkout@v4
+      - uses: astral-sh/setup-uv@v4
+      - run: uv sync --dev
+      - run: uv run pytest -x -q --timeout=30
diff --git a/pipelines/default/pipeline.yaml b/pipelines/default/pipeline.yaml
index e93ea5378..d9ee75c0c 100644
--- a/pipelines/default/pipeline.yaml
+++ b/pipelines/default/pipeline.yaml
@@ -56,17 +56,17 @@ roles:
     not_for: Tasks needing research or unknown scope — use full-cycle
     description: >
       General-purpose worker. Implements tasks directly, no pipeline gates.
       For system workers (permanent, module-scoped) and disposable one-shots.
   full-cycle:
     kind: worker
     label: Full-Cycle
     order: 3
-    model: opus
+    model: opus4.8
     skills: [codex-debate]
     modules: [git-workflow, report-format]
     can_spawn: ["*"]
     allow_unrouted_workers: false
     when: New feature with unknowns, large refactoring (5+ files), external integration, anything where wrong approach = wasted day
     not_for: Bug fixes, config changes, implementation from clear spec
     description: >
       Research → Plan + Codex review → Implement + Codex review. Strict 3-phase pipeline
diff --git a/pyproject.toml b/pyproject.toml
index b1e85310c..b1c6933ca 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -18,13 +18,14 @@ dependencies = [
     "croniter>=2.0,<7.0",
     "pyyaml>=6.0,<7.0",
 ]
 
 [dependency-groups]
 dev = [
     "pytest>=8.0,<10.0",
     "pytest-asyncio>=0.24,<2.0",
+    "pytest-timeout>=2.3,<3.0",
 ]
 
 [tool.pytest.ini_options]
 testpaths = ["tests"]
 norecursedirs = ["worktrees", ".venv", "data", "docs"]
diff --git a/tests/test_default_pipeline.py b/tests/test_default_pipeline.py
index 55c46b3d8..cf547d5e2 100644
--- a/tests/test_default_pipeline.py
+++ b/tests/test_default_pipeline.py
@@ -108,17 +108,17 @@ class TestDefaultRolesResolve:
     def test_worker_and_full_cycle_are_not_orchestrators(self):
         """worker И full-cycle — воркеры (оркестратор спавнит их как исполнителей)."""
         assert P.get_role(PIPELINE, "worker").is_orchestrator is False
         assert P.get_role(PIPELINE, "full-cycle").is_orchestrator is False
 
     def test_full_cycle_model_opus(self):
         rr = P.get_role(PIPELINE, "full-cycle")
         assert rr is not None
-        assert rr.model == "opus"
+        assert rr.model == "opus4.8"
 
     def test_sub_orchestrator_is_orchestrator_opus(self):
         """sub-orchestrator — kind:orchestrator, opus, can_spawn=['*']."""
         rr = P.get_role(PIPELINE, "sub-orchestrator")
         assert rr is not None
         assert rr.is_orchestrator is True
         assert rr.model == "opus"
         assert rr.can_spawn == ["*"]
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index f7abd1a43..f4fc1e435 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -152,22 +152,22 @@ class TestSchemaValidation:
               r: {kind: worker, label: R, model: turbo-9}
         """)
         with pytest.raises(Exception, match="model"):
             P.load_pipeline("demo")
 
     def test_full_model_id_accepted(self, pipelines_root):
         _write_pipeline(pipelines_root, "demo", """\
             name: demo
-            defaults: {model: claude-opus-4-7}
+            defaults: {model: claude-opus-4-8}
             roles:
               r: {kind: worker, label: R, model: claude-sonnet-4-6}
         """)
         cfg = P.load_pipeline("demo")
-        assert cfg.defaults.model == "claude-opus-4-7"
+        assert cfg.defaults.model == "claude-opus-4-8"
         assert cfg.roles["r"].model == "claude-sonnet-4-6"
 
     def test_can_spawn_unknown_role_rejected(self, pipelines_root):
         _write_pipeline(pipelines_root, "demo", """\
             name: demo
             roles:
               a: {kind: orchestrator, label: A, can_spawn: [ghost]}
               b: {kind: worker, label: B}
diff --git a/uv.lock b/uv.lock
index 97b631eec..14f72c999 100644
--- a/uv.lock
+++ b/uv.lock
@@ -1,14 +1,14 @@
 version = 1
 revision = 3
 requires-python = ">=3.12"
 
 [options]
-exclude-newer = "2026-05-28T04:30:38.061297437Z"
+exclude-newer = "2026-06-02T09:26:54.184029065Z"
 exclude-newer-span = "P7D"
 
 [[package]]
 name = "aiofiles"
 version = "25.1.0"
 source = { registry = "https://pypi.org/simple" }
 sdist = { url = "https://files.pythonhosted.org/packages/41/c3/534eac40372d8ee36ef40df62ec129bee4fdb5ad9706e58a29be53b2c970/aiofiles-25.1.0.tar.gz", hash = "sha256:a8d728f0a29de45dc521f18f07297428d56992a742f0cd2701ba86e44d23d5b2", size = 46354, upload-time = "2025-10-09T20:51:04.358Z" }
 wheels = [
@@ -818,16 +818,17 @@ dependencies = [
     { name = "telegramify-markdown" },
     { name = "uvicorn", extra = ["standard"] },
 ]
 
 [package.dev-dependencies]
 dev = [
     { name = "pytest" },
     { name = "pytest-asyncio" },
+    { name = "pytest-timeout" },
 ]
 
 [package.metadata]
 requires-dist = [
     { name = "aiogram", specifier = ">=3.28,<4.0" },
     { name = "aiohttp", specifier = ">=3.9,<4.0" },
     { name = "claude-agent-sdk", specifier = ">=0.1.72" },
     { name = "croniter", specifier = ">=2.0,<7.0" },
@@ -842,16 +843,17 @@ requires-dist = [
     { name = "telegramify-markdown", specifier = ">=1.1.3" },
     { name = "uvicorn", extras = ["standard"], specifier = ">=0.34,<1.0" },
 ]
 
 [package.metadata.requires-dev]
 dev = [
     { name = "pytest", specifier = ">=8.0,<10.0" },
     { name = "pytest-asyncio", specifier = ">=0.24,<2.0" },
+    { name = "pytest-timeout", specifier = ">=2.3,<3.0" },
 ]
 
 [[package]]
 name = "packaging"
 version = "26.2"
 source = { registry = "https://pypi.org/simple" }
 sdist = { url = "https://files.pythonhosted.org/packages/d7/f1/e7a6dd94a8d4a5626c03e4e99c87f241ba9e350cd9e6d75123f992427270/packaging-26.2.tar.gz", hash = "sha256:ff452ff5a3e828ce110190feff1178bb1f2ea2281fa2075aadb987c2fb221661", size = 228134, upload-time = "2026-04-24T20:15:23.917Z" }
 wheels = [
@@ -1257,16 +1259,28 @@ dependencies = [
     { name = "pytest" },
     { name = "typing-extensions", marker = "python_full_version < '3.13'" },
 ]
 sdist = { url = "https://files.pythonhosted.org/packages/43/7c/d36d04db312ecf4298932ef77e6e4a9e8ad017906e24e34f0b0c361a2473/pytest_asyncio-1.4.0.tar.gz", hash = "sha256:c6c0d2259945122819f171a32ecea2c349ead889ee28176caaf492143424be42", size = 58514, upload-time = "2026-05-26T09:56:04.083Z" }
 wheels = [
     { url = "https://files.pythonhosted.org/packages/03/e2/08a497ef684b88559c9cc5f4ad53a37e7b99e727094a86d6ea32536d5d3c/pytest_asyncio-1.4.0-py3-none-any.whl", hash = "sha256:933ca923a23075a87fb7070c0ec272a6848489824d887c85c812670932835aa1", size = 16930, upload-time = "2026-05-26T09:56:02.576Z" },
 ]
 
+[[package]]
+name = "pytest-timeout"
+version = "2.4.0"
+source = { registry = "https://pypi.org/simple" }
+dependencies = [
+    { name = "pytest" },
+]
+sdist = { url = "https://files.pythonhosted.org/packages/ac/82/4c9ecabab13363e72d880f2fb504c5f750433b2b6f16e99f4ec21ada284c/pytest_timeout-2.4.0.tar.gz", hash = "sha256:7e68e90b01f9eff71332b25001f85c75495fc4e3a836701876183c4bcfd0540a", size = 17973, upload-time = "2025-05-05T19:44:34.99Z" }
+wheels = [
+    { url = "https://files.pythonhosted.org/packages/fa/b6/3127540ecdf1464a00e5a01ee60a1b09175f6913f0644ac748494d9c4b21/pytest_timeout-2.4.0-py3-none-any.whl", hash = "sha256:c42667e5cdadb151aeb5b26d114aff6bdf5a907f176a007a30b940d3d865b5c2", size = 14382, upload-time = "2025-05-05T19:44:33.502Z" },
+]
+
 [[package]]
 name = "python-dateutil"
 version = "2.9.0.post0"
 source = { registry = "https://pypi.org/simple" }
 dependencies = [
     { name = "six" },
 ]
 sdist = { url = "https://files.pythonhosted.org/packages/66/c0/0c8b6ad9f17a802ee498c46e004a0eb49bc148f2fd230864601a86dcf6db/python-dateutil-2.9.0.post0.tar.gz", hash = "sha256:37dd54208da7e1cd875388217d5e00ebd4179249f90fb72437e91a35459a0ad3", size = 342432, upload-time = "2024-03-01T18:36:20.211Z" }


## LATER FIX 8dd91d5e11 (117.9 days later): V-700: #V-700: fix dashboard CI and i18n issues
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