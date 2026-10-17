# Candidate cand-62

## ORIGIN commit b6782ca8a7 (2026-08-19): #336: #336: замер merge-gate до правки — где потолок, почему 180с не хватает, где теряется различие красного и незавершё
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/merge_operations.py b/app/merge_operations.py
index 07cc3a3a3..deb94f9d7 100644
--- a/app/merge_operations.py
+++ b/app/merge_operations.py
@@ -1010,49 +1010,67 @@ async def _run_operation(operation_id: str) -> None:
                     error=error,
                     next_action=_action(
                         "FIX_ACCEPTANCE_THEN_RETRY",
                         "Fix the registered acceptance command, then start a new merge.",
                     ),
                 )
                 result["acceptance"] = acceptance
             else:
-                from app.merge_test_gate import evaluate_test_gate
+                from app.merge_test_gate import describe_progress, evaluate_test_gate
 
                 test_gate = await asyncio.to_thread(
                     evaluate_test_gate, current["worktree_path"],
                 )
                 if test_gate["status"] in {FAILED, INCONCLUSIVE}:
                     code = (
                         "TEST_GATE_FAILED"
                         if test_gate["status"] == FAILED
                         else "TEST_GATE_INCONCLUSIVE"
                     )
+                    # Учёт дописывается ПОСЛЕ хвоста выхода: получатель видит `[-400:]`,
+                    # то есть конец строки, — сводка в начале до него не доехала бы.
+                    progress = describe_progress(test_gate)
                     error = _error(
                         code,
                         (
                             f"Merge test gate {test_gate['status']}"
                             f" ({test_gate.get('reason') or 'exit_nonzero'}): "
                             f"{(test_gate.get('output') or '')[-400:]}"
+                            + (f" — {progress}" if progress else "")
                         ),
                         operation_id=operation_id,
                         status=409,
                         retryable=test_gate["status"] == INCONCLUSIVE,
                     )
+                    # Разные исходы требуют разных действий, и раньше оба получали
+                    # «Fix the failing merge-gate tests» — для незавершённого прогона это
+                    # прямая ложь (чинить нечего), из-за которой #329 смержили руками.
+                    next_action = (
+                        _action(
+                            "FIX_TESTS_THEN_RETRY",
+                            "Fix the failing merge-gate tests, then start a new merge.",
+                        )
+                        if test_gate["status"] == FAILED
+                        else _action(
+                            "TEST_GATE_UNFINISHED",
+                            "No test was reported red — the gate ran out of its time "
+                            "budget. Do NOT 'fix' tests. Retry the same operation; if it "
+                            "keeps running out, the mapped subset costs more than the "
+                            "gate budget and the merge needs an explicit decision.",
+                        )
+                    )
                     result = _base_result(
                         operation_id,
                         "FAILED",
                         target_branch=record["request"].get("target", ""),
                         worker_branch=record["accepted_worker_branch"],
                         worker_head=record["accepted_worker_head"],
                         error=error,
-                        next_action=_action(
-                            "FIX_TESTS_THEN_RETRY",
-                            "Fix the failing merge-gate tests, then start a new merge.",
-                        ),
+                        next_action=next_action,
                     )
                     result["acceptance"] = acceptance
                     result["test_gate"] = test_gate
                 else:
                     from app.routes.sessions import execute_merge_session
 
                     raw = await execute_merge_session(
                         session_id=record["session_id"],
diff --git a/app/merge_test_gate.py b/app/merge_test_gate.py
index 358d9653e..0377ea03e 100644
--- a/app/merge_test_gate.py
+++ b/app/merge_test_gate.py
@@ -11,33 +11,70 @@ so #240 oracles keep working). Unmapped app modules are a hole we accept —
 missing tests ≠ landing a red test that already exists.
 
 Tests marked `live_probe` are deselected: they spend a real provider turn, so they go red
 on quota and provider outages instead of on the diff. They stay runnable by hand
 (`pytest -m live_probe tests/`) and their inventory is pinned by a test.
 
 Mapped files are run in sequential batches of MAX_TEST_FILES. The batches share one
 wall-clock budget and never turn into a full-suite invocation.
-Timeout → inconclusive. Does not close bash: the worker can rewrite this file.
+
+Killed by the budget → the partial pytest output decides, because "the tests are red" and
+"we did not finish" arrive as the same TimeoutExpired and must not be answered the same way:
+a verdict pytest already printed (`FAILED`/`ERROR`) makes it FAILED — a red test is red whether
+or not the rest ran — and only a kill with no verdict at all is INCONCLUSIVE, reported with what
+was verified and what was never reached. Does not close bash: the worker can rewrite this file.
 """
 
 from __future__ import annotations
 
 import os
+import re
 import subprocess
 import sys
 import time
 from pathlib import Path
 
 from app.acceptance import FAILED, INCONCLUSIVE, PASSED, SKIPPED
 
 MAX_TEST_FILES = 12
 MAX_BATCH_TESTS = 6
-DEFAULT_TIMEOUT_SECONDS = 180.0
+
+# Бюджет ВЫВЕДЕН ИЗ ЗАМЕРА (#336), а не назначен. Прежние фиксированные 180 с числом про
+# pytest никогда не были: `git log -S` показывает, что это дефолт операторской команды
+# приёмки (#240), скопированный в гейт вместе с ним (#255). Каждое число ниже — с источником,
+# иначе через месяц оно станет вторым таким же 180.
+#
+# ПОЛ = BASE + PER_FILE = 330 с. Самый дорогой одиночный тест-файл замерен в 219.5 с
+#   (`tests/test_manager.py`; под нагрузкой 15+ тот же файл дал 283 с) — взят полуторный
+#   запас. Батч не может быть меньше одного файла, поэтому при бюджете ниже этого числа
+#   дифф, задевающий `app/manager.py`, не получает вердикта ни при какой раскладке батчей.
+# ШАГ = 150 с на файл. Медиана тест-файла ≈33 с, среднее ≈68 с, хвост тяжёлый
+#   (`tests/test_frontend.py` — 71–148 с по пяти прод-замерам). Шаг взят от среднего с
+#   двойным запасом, чтобы набор средних файлов укладывался, а не впритык.
+# ПОТОЛОК = 1200 с. Худший правдоподобный набор из замеренных (manager+frontend+db+session+
+#   mcp_stdio+tg_bridge) = 682 с суммой одиночных прогонов, полуторный запас. Потолок нужен,
+#   потому что число файлов со стоимостью коррелирует слабо: один и тот же файл замерен
+#   14.3 и 149.5 с (10.5×) — разброс задаёт конкурентная загрузка машины, и подобрать
+#   «точный» бюджет нельзя в принципе. Отсюда же второй контур защиты: отказ по времени
+#   обязан оставаться информативным (см. `_partial_progress`), а не только редким.
+BASE_TIMEOUT_SECONDS = 180.0
+PER_FILE_TIMEOUT_SECONDS = 150.0
+MAX_TIMEOUT_SECONDS = 1200.0
 _BATCH_DIAGNOSTIC_LIMIT = 4000
+
+
+def budget_for(file_count: int) -> float:
+    """Бюджет всего гейта под набор из `file_count` файлов."""
+    return min(
+        MAX_TIMEOUT_SECONDS,
+        BASE_TIMEOUT_SECONDS + PER_FILE_TIMEOUT_SECONDS * max(0, file_count),
+    )
+
+
 ROUTE_TEST = "tests/test_routes_surface.py"
 _ROUTE_EXACT = frozenset({
     "app/main.py",
     "tests/route_surface_snapshot.json",
     "tests/test_routes_surface.py",
 })
 
 
@@ -115,25 +152,100 @@ NO_TESTS_EXIT_CODE = 5  # pytest EXIT_NOTESTSCOLLECTED
 
 
 def pytest_argv(tests: list[str]) -> list[str]:
     # No -x / --exitfirst / --maxfail=1: one red must not hide the rest.
     # `-m "not live_probe"` снимает с гейта пробы, тратящие настоящий ход провайдера: они
     # краснеют от квоты и недоступности, а не от диффа, и блокируют чужие мержи (18.08:
     # codex-проба стояла красной по rate_limit в самом main). Умолчание безопасное — новая
     # проба БЕЗ маркера гоняется гейтом и падает громко; исчезнуть незаметно она не может.
+    #
+    # `-vv` рядом с `-q` — не косметика, а единственный источник, по которому «набор
+    # красный» отличимо от «мы не успели»: pytest печатает вердикт КАЖДОГО теста отдельной
+    # строкой сразу по его окончании и успевает это сделать до убийства по таймауту, тогда
+    # как `-q` даёт безымянные точки (а при убийстве в фазе сбора — пустой выход вовсе).
+    # Замер #336: убитый прогон отдал `test_b_red FAILED` и имя висящего теста, тогда как
+    # `-q` на том же прогоне — 0 символов.
+    # Арифметика флагов проверена прогоном и неочевидна: `-q` это −1, `-vv` это +2, сумма
+    # +1 — тот же режим, что голый `-v`. Писать `-q -v` НЕЛЬЗЯ: сумма 0, снова точки.
     return [
-        sys.executable, "-m", "pytest", "-q",
+        sys.executable, "-m", "pytest", "-q", "-vv",
         "-m", f"not {LIVE_PROBE_MARKER}",
         *tests,
     ]
 
 
+# `tests/test_x.py::test_name[param] PASSED [ 12%]`.
+# Строка обязана НАЧИНАТЬСЯ с nodeid: тогда строки итоговой сводки (`FAILED tests/x.py::y - ...`)
+# сюда не попадают и провал не считается дважды.
+# Вердикт берётся ПОСЛЕДНИЙ на строке, а не первый: nodeid параметризованного теста содержит
+# произвольный текст, в том числе пробелы и сами эти слова. Замер #336 — на строке
+# `tests/test_a.py::t2[a b PASSED c] FAILED [2%]` нежадный разбор возвращал PASSED, то есть
+# КРАСНЫЙ тест читался как зелёный; это ровно то направление ошибки, которого быть не должно.
+# Требование пробела перед вердиктом отсекает `nodeid[FAILED]` у теста, который ещё идёт.
+_NODEID_RE = re.compile(r"^\S+\.py::\S")
+_VERDICT_RE = re.compile(r"\s(?P<verdict>PASSED|FAILED|ERROR|XFAIL|XPASS|SKIPPED)(?=\s|$)")
+
+
+def _partial_progress(output: str, tests: list[str]) -> dict:
+    """Что pytest успел сообщить до убийства по таймауту.
+
+    Обе неудачи приходят одним и тем же `TimeoutExpired`, и без разбора этого выхода они
+    неразличимы. Замер #336 на живых операциях: у #248 в убитом выходе стояли девять `F`
+    (настоящая краснота), у #329 — сплошные точки (набор зелёный, просто не доехал); гейт
+    доложил обоим одно и то же «inconclusive».
+    """
+    failed: list[str] = []
+    passed = 0
+    seen_files: set[str] = set()
+    stopped_in = ""
+    for raw in output.splitlines():
+        line = raw.rstrip()
+        if not _NODEID_RE.match(line):
+            continue
+        verdicts = list(_VERDICT_RE.finditer(line))
+        if not verdicts:
+            # Имя напечатано, вердикта ещё нет — на этом тесте нас и прервали.
+            stopped_in = line.strip()
+            seen_files.add(stopped_in.split("::", 1)[0])
+            continue
+        last = verdicts[-1]
+        nodeid = line[:last.start()].strip()
+        seen_files.add(nodeid.split("::", 1)[0])
+        if last.group("verdict") in {"FAILED", "ERROR"}:
+            failed.append(nodeid)
+        elif last.group("verdict") == "PASSED":
+            passed += 1
+        stopped_in = ""
+    return {
+        "failed_tests": failed,
+        "passed_count": passed,
+        "stopped_in": stopped_in,
+        "unreached": [test for test in tests if test not in seen_files],
+    }
+
+
+def describe_progress(result: dict) -> str:
+    """Одна строка для человека: что проверено, что нет. Пусто — сказать нечего."""
+    if "passed_count" not in result:
+        return ""
+    parts = [f"verified green: {result['passed_count']}"]
+    if result.get("failed_tests"):
+        shown = ", ".join(result["failed_tests"][:5])
+        extra = len(result["failed_tests"]) - 5
+        parts.append(f"RED: {shown}" + (f" (+{extra} more)" if extra > 0 else ""))
+    if result.get("stopped_in"):
+        parts.append(f"ran out of budget inside {result['stopped_in']}")
+    if result.get("unreached"):
+        parts.append(f"never reached: {', '.join(result['unreached'])}")
+    return "; ".join(parts)
+
+
 def run_pytest(worktree: str, tests: list[str], *, timeout: float | None = None) -> dict:
-    budget = DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout
+    budget = budget_for(len(tests)) if timeout is None else timeout
     argv = pytest_argv(tests)
     env = os.environ.copy()
     root = str(Path(worktree).resolve())
     prior = env.get("PYTHONPATH", "")
     env["PYTHONPATH"] = root if not prior else f"{root}{os.pathsep}{prior}"
     try:
         proc = subprocess.run(
             argv,
@@ -146,19 +258,30 @@ def run_pytest(worktree: str, tests: list[str], *, timeout: float | None = None)
         )
     except FileNotFoundError:
         return {
             "status": INCONCLUSIVE, "reason": "not_found",
             "exit_code": None, "output": argv[0], "tests": tests,
         }
     except subprocess.TimeoutExpired as exc:
         out = _normalize_output(exc.stdout) + _normalize_output(exc.stderr)
+        progress = _partial_progress(out, tests)
+        # Красный тест красен независимо от того, доехал ли остаток набора: мерж такого
+        # состояния посадил бы красноту в main. Поэтому увиденный провал — это FAILED
+        # (окончательно, повтор не поможет), и только отсутствие провалов — INCONCLUSIVE.
+        if progress["failed_tests"]:
+            return {
+                "status": FAILED, "reason": "timeout_with_failures",
+                "exit_code": None, "output": out[-4000:], "tests": tests,
+                **progress,
+            }
         return {
             "status": INCONCLUSIVE, "reason": "timeout",
             "exit_code": None, "output": out[-4000:], "tests": tests,
+            **progress,
         }
     except OSError as exc:
         return {
             "status": INCONCLUSIVE, "reason": "os_error",
             "exit_code": None, "output": str(exc), "tests": tests,
         }
     output = (_normalize_output(proc.stdout) + _normalize_output(proc.stderr))[-4000:]
     if proc.returncode == 0:
@@ -204,17 +327,17 @@ def _ordered_batches(tests: list[str]) -> list[list[str]]:
         size = base_size + (index < remainder)
         batches.append(tests[cursor:cursor + size])
         cursor += size
     return batches
 
 
 def _batch_result(worktree: str, batches: list[list[str]]) -> dict:
     """Run every mapped batch under one deadline and combine its evidence."""
-    deadline = time.monotonic() + DEFAULT_TIMEOUT_SECONDS
+    deadline = time.monotonic() + budget_for(sum(len(batch) for batch in batches))
     batches_left = len(batches)
     results: list[dict] = []
     for batch in batches:
         remaining = deadline - time.monotonic()
         if remaining <= 0:
             result = {
                 "status": INCONCLUSIVE,
                 "reason": "timeout",
@@ -263,16 +386,26 @@ def _batch_result(worktree: str, batches: list[list[str]]) -> dict:
             section = f"{section}\n{_compact_output(output, budget)}"
         sections.append(section[:section_limit])
     return {
         "status": status,
         "reason": reason,
         "exit_code": exit_code,
         "output": "\n".join(sections),
         "tests": list(sum(batches, [])),
+        "failed_tests": [
+            node for result in results for node in result.get("failed_tests", [])
+        ],
+        "passed_count": sum(result.get("passed_count", 0) for result in results),
+        "stopped_in": next(
+            (result["stopped_in"] for result in results if result.get("stopped_in")), ""
+        ),
+        "unreached": [
+            test for result in results for test in result.get("unreached", [])
+        ],
     }
 
 
 def evaluate_test_gate(worktree: str) -> dict:
     changed = changed_paths(worktree)
     if changed is None:
         return {
             "status": SKIPPED, "reason": "no_diff",
diff --git a/docs/tasks/336/measure.sh b/docs/tasks/336/measure.sh
new file mode 100644
index 000000000..e4e0914a4
--- /dev/null
+++ b/docs/tasks/336/measure.sh
@@ -0,0 +1,20 @@
+#!/bin/bash
+# #336: per-file cost of the #329 mapped set, exactly as the gate invokes pytest.
+cd /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-merge-gate
+PY=/home/kesha/orchestra/.venv/bin/python
+OUT=/tmp/336-measure.txt
+: > "$OUT"
+FILES="tests/test_db.py tests/test_default_pipeline.py tests/test_manager.py tests/test_pipeline.py tests/test_quota_gate.py tests/test_worker_model_policy.py"
+for f in $FILES; do
+  s=$(date +%s.%N)
+  PYTHONPATH=$PWD timeout 900 "$PY" -m pytest -q -m "not live_probe" "$f" > /tmp/336-one.log 2>&1
+  rc=$?
+  e=$(date +%s.%N)
+  printf '%-40s rc=%-3s %8.2fs  %s\n' "$f" "$rc" "$(echo "$e - $s" | bc)" "$(tail -3 /tmp/336-one.log | tr '\n' ' ' | tail -c 120)" >> "$OUT"
+done
+s=$(date +%s.%N)
+PYTHONPATH=$PWD timeout 900 "$PY" -m pytest -q -m "not live_probe" $FILES > /tmp/336-all.log 2>&1
+rc=$?
+e=$(date +%s.%N)
+printf '%-40s rc=%-3s %8.2fs  %s\n' "ALL-6-IN-ONE-INVOCATION" "$rc" "$(echo "$e - $s" | bc)" "$(tail -3 /tmp/336-all.log | tr '\n' ' ' | tail -c 120)" >> "$OUT"
+echo MEASURE-DONE >> "$OUT"
diff --git a/docs/tasks/336/measure2.sh b/docs/tasks/336/measure2.sh
new file mode 100644
index 000000000..3dee83387
--- /dev/null
+++ b/docs/tasks/336/measure2.sh
@@ -0,0 +1,17 @@
+#!/bin/bash
+# #336: повтор ключевого числа (#329 набор одним вызовом) на менее нагруженной машине.
+# Пишет load average рядом с результатом — без него число несравнимо с первым замером.
+cd /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-merge-gate
+PY=/home/kesha/orchestra/.venv/bin/python
+OUT=/tmp/336-measure2.txt
+FILES="tests/test_db.py tests/test_default_pipeline.py tests/test_manager.py tests/test_pipeline.py tests/test_quota_gate.py tests/test_worker_model_policy.py"
+{
+  echo "load-before: $(cut -d' ' -f1-3 /proc/loadavg)  pytest-procs: $(pgrep -c -f 'm pytest' || echo 0)"
+  s=$(date +%s.%N)
+  PYTHONPATH=$PWD timeout 1200 "$PY" -m pytest -q -m "not live_probe" $FILES > /tmp/336-all2.log 2>&1
+  rc=$?
+  e=$(date +%s.%N)
+  printf 'ALL-6-IN-ONE rc=%s %.2fs  %s\n' "$rc" "$(echo "$e - $s" | bc)" "$(tail -2 /tmp/336-all2.log | tr '\n' ' ')"
+  echo "load-after:  $(cut -d' ' -f1-3 /proc/loadavg)  pytest-procs: $(pgrep -c -f 'm pytest' || echo 0)"
+  echo MEASURE2-DONE
+} > "$OUT" 2>&1
diff --git a/pyproject.toml b/pyproject.toml
index 03f4bd47c..544768b3b 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -53,15 +53,23 @@ dev = [
 # Дата совпадает с содержимым лока: самый свежий пакет в `uv.lock` загружен 2026-07-08.
 # Ставить дату НОВЕЕ лока нельзя — следующий `uv lock` тогда разом обновит ~40 пакетов
 # (проверено: uvicorn 0.48 → 0.52.1, aiogram 3.28.2 → 3.30.0). Двигать эту дату — значит
 # осознанно обновлять зависимости: меняешь дату, гоняешь `uv lock`, гоняешь тесты, коммитишь
 # лок и дату ОДНИМ коммитом.
 exclude-newer = "2026-07-09T10:16:55.018333899Z"
 
 [tool.pytest.ini_options]
+# Живые пробы сняты со ВСЯКОГО прогона, а не только с команды merge-gate (#328 закрыл
+# лишь гейт). Плоский `uv run pytest -q` собирал их обратно и вис до упора на исчерпанной
+# квоте Codex: замер #336 — прогон убит по общему таймауту с EXIT=124 на 78%, окно потеряно
+# молча. Защита, действующая только когда запускающий помнит про флаг, в автоматике не
+# исполняется. CLI перебивает эту строку, а не складывается с ней (`-m` — одно значение,
+# побеждает последнее): `pytest -m live_probe tests/` собирает 3 пробы из 3214, обычный
+# прогон — 3211 из 3214, ровно столько же, сколько командой гейта.
+addopts = ["-m", "not live_probe"]
 testpaths = ["tests"]
 norecursedirs = ["worktrees", ".venv", "data", "docs"]
 markers = [
     "needs_two_users: требует беспарольного sudo — владение файлами не моделируется заглушками",
     "needs_model: требует эмбеддер (orchestra[rag]) — индексация и поиск не моделируются заглушками",
     "live_probe: тратит настоящий ход провайдера (поднимает CLI, шлёт запрос). Краснеет от квоты и капризов провайдера, а не от диффа, поэтому merge-gate его не гоняет — запускать вручную `uv run pytest -m live_probe tests/`. Новую такую пробу заводить только вместе с записью в test_live_probe_inventory_is_explicit",
 ]
diff --git a/tests/test_merge_test_gate.py b/tests/test_merge_test_gate.py
index 146c51ea1..cdbd915ce 100644
--- a/tests/test_merge_test_gate.py
+++ b/tests/test_merge_test_gate.py
@@ -109,52 +109,70 @@ def test_select_tests_maps_stem_and_routes(tmp_path):
 
     mapped = select_tests(
         ["app/widget.py", "app/routes/tm.py"], worktree=str(tmp_path),
     )
     assert mapped == ["tests/test_routes_surface.py", "tests/test_widget.py"]
     assert select_tests(["docs/a.md"], worktree=str(tmp_path)) == []
 
 
-def test_large_mapped_subset_runs_all_files_in_bounded_batches(monkeypatch):
+def test_large_mapped_subset_reaches_a_verdict_at_measured_file_costs(monkeypatch):
+    """Набор из РЕАЛЬНО дорогих файлов обязан получить вердикт, а не таймаут.
+
+    Стоимости взяты из замера #336, а не выдуманы: `tests/test_manager.py` — 219.5 с
+    (283 с под нагрузкой), `tests/test_frontend.py` — 71–148 с по пяти прод-замерам.
+    Каждый из них дороже всего прежнего фиксированного бюджета 180 с сам по себе, а батч
+    не может быть меньше одного файла — поэтому при фиксированном бюджете такой набор
+    не получал вердикта ни при какой раскладке (замер: #290 отбит семь раз подряд).
+
+    Проверяется ПОВЕДЕНИЕ, а не литерал: батч ограничен, каждый файл прогнан, бюджет
+    растёт с размером набора, вердикт выдан. Тест переживает смену любой из трёх констант
+    и краснеет на возврате к бюджету, не зависящему от размера набора.
+    """
     from app import merge_test_gate as gate
 
-    tests = [f"tests/test_{n:02d}.py" for n in range(14)]
+    costs = {"tests/test_manager.py": 283.0, "tests/test_frontend.py": 148.0}
+    tests = ["tests/test_manager.py", "tests/test_frontend.py"] + [
+        f"tests/test_{n:02d}.py" for n in range(12)
+    ]
+    tests.sort()
     calls = []
     clock = [0.0]
 
     monkeypatch.setattr(gate, "changed_paths", lambda _worktree: ["app/widget.py"])
     monkeypatch.setattr(gate, "select_tests", lambda _changed, worktree: tests)
     monkeypatch.setattr(gate.time, "monotonic", lambda: clock[0])
 
     def fake_run(worktree, batch, *, timeout=None):
         calls.append((list(batch), timeout))
-        cost = {2: 36.82, 4: 48.0, 5: 60.0, 12: 240.0}[len(batch)]
+        cost = sum(costs.get(test, 10.0) for test in batch)
         clock[0] += min(cost, timeout)
         status = gate.PASSED if cost <= timeout else gate.INCONCLUSIVE
         return {
             "status": status,
             "reason": "" if status == gate.PASSED else "timeout",
             "exit_code": 0 if status == gate.PASSED else None,
-            "output": "passed " + ", ".join(batch),
+            "output": "ran " + ", ".join(batch),
             "tests": list(batch),
         }
 
     monkeypatch.setattr(gate, "run_pytest", fake_run)
     result = gate.evaluate_test_gate("/worktree")
 
-    assert result["status"] == gate.PASSED
+    assert result["status"] == gate.PASSED, "набор зелёный — гейт обязан это установить"
     assert [test for batch, _timeout in calls for test in batch] == tests
     batch_sizes = [len(batch) for batch, _timeout in calls]
-    assert batch_sizes == [5, 5, 4]
-    assert max(batch_sizes) < gate.MAX_TEST_FILES
-    assert sum({4: 48.0, 5: 60.0}[size] for size in batch_sizes) <= gate.DEFAULT_TIMEOUT_SECONDS
-    assert 36.82 + 240.0 > gate.DEFAULT_TIMEOUT_SECONDS  # old [2, 12] profile
-    assert [timeout for _batch, timeout in calls] == [60.0, 60.0, 60.0]
-    assert clock[0] == pytest.approx(168.0)
+    assert min(batch_sizes) >= 1 and max(batch_sizes) < gate.MAX_TEST_FILES
+    # Бюджет обязан зависеть от размера набора: иначе тяжёлый файл не помещается никогда.
+    assert gate.budget_for(len(tests)) > gate.budget_for(1) > gate.budget_for(0)
+    assert gate.budget_for(1) >= max(costs.values()), (
+        "бюджет обязан вмещать самый дорогой ОДИНОЧНЫЙ файл — батч меньше файла невозможен"
+    )
+    # Самый дорогой файл не помещается ни в один батч при прежнем фиксированном бюджете.
+    assert costs["tests/test_manager.py"] > 180.0 / len(calls)
 
 
 def test_each_batch_is_attempted_when_non_final_batch_fails(monkeypatch):
     from app import merge_test_gate as gate
 
     tests = [f"tests/test_{n:02d}.py" for n in range(13)]
     calls = []
 
@@ -428,16 +446,129 @@ def test_run_pytest_timeout_truncates_to_last_4000_chars(tmp_path, monkeypatch):
         ),
     )
     result = gate.run_pytest(str(tmp_path), tests, timeout=1)
     assert result["reason"] == "timeout"
     assert len(result["output"]) == 4000
     assert result["output"] == payload[-4000:]
 
 
+# Дословно снято с убитого прогона (#336): `-q -vv`, kill на 10 с. Формат фикстуры не
+# сочинён — иначе разбор проверялся бы против выдумки, а не против того, что печатает pytest.
+_KILLED_WITH_RED = (
+    "test_probe.py::test_a_ok PASSED                                          [ 25%]\n"
+    "test_probe.py::test_b_red FAILED                                         [ 50%]\n"
+    "test_probe.py::test_c_slow "
+)
+
+
+def _timeout_raiser(payload: str):
+    def _raise(*_args, **_kwargs):
+        raise subprocess.TimeoutExpired(
+            cmd=["pytest"], timeout=1, output=payload, stderr=None,
+        )
+    return _raise
+
+
+def test_timeout_that_saw_a_red_test_is_failed_not_inconclusive(tmp_path, monkeypatch):
+    """Убитый прогон, успевший показать красное, — это FAILED, а не «не успели».
+
+    Замер #336 на живой операции #248: в убитом выходе стояло девять `F`, гейт доложил
+    `inconclusive`, то есть «повтори» — а повторять было нечего, тесты были красные.
+    Красный тест красен независимо от того, доехал ли остаток набора.
+    """
+    from app import merge_test_gate as gate
+    from app.acceptance import FAILED
+
+    monkeypatch.setattr(gate.subprocess, "run", _timeout_raiser(_KILLED_WITH_RED))
+
+    result = gate.run_pytest(str(tmp_path), ["test_probe.py"], timeout=1)
+
+    assert result["status"] == FAILED
+    assert result["reason"] == "timeout_with_failures"
+    assert result["failed_tests"] == ["test_probe.py::test_b_red"]
+    assert "test_probe.py::test_b_red" in gate.describe_progress(result)
+
+
+def test_timeout_without_red_says_what_was_verified_and_what_was_not(tmp_path, monkeypatch):
+    """Случай #329: набор зелёный, просто не доехал — отказ обязан это сказать.
+
+    Раньше и он, и красный приходили как FAILED с советом «почини падающие тесты»,
+    которых нет; из-за этого #329 смержили руками.
+    """
+    from app import merge_test_gate as gate
+    from app.acceptance import INCONCLUSIVE
+
+    payload = (
+        "tests/test_a.py::test_one PASSED   [ 33%]\n"
+        "tests/test_a.py::test_two PASSED   [ 66%]\n"
+        "tests/test_a.py::test_slow "
+    )
+    monkeypatch.setattr(gate.subprocess, "run", _timeout_raiser(payload))
+
+    result = gate.run_pytest(
+        str(tmp_path), ["tests/test_a.py", "tests/test_never.py"], timeout=1,
+    )
+
+    assert result["status"] == INCONCLUSIVE
+    assert result["reason"] == "timeout"
+    assert result["failed_tests"] == []
+    assert result["passed_count"] == 2
+    assert result["stopped_in"] == "tests/test_a.py::test_slow"
+    assert result["unreached"] == ["tests/test_never.py"]
+
+
+def test_parametrised_nodeid_cannot_disguise_a_red_test():
+    """Красное не должно читаться как зелёное из-за текста внутри имени теста.
+
+    nodeid параметризованного теста содержит произвольный текст, включая пробелы и сами
+    слова-вердикты. Замер #336: нежадный разбор на строке
+    `tests/test_a.py::t2[a b PASSED c] FAILED` возвращал PASSED — то есть гейт пропустил бы
+    красноту в main. Поэтому вердикт берётся последний на строке.
+    Итоговая сводка (`FAILED nodeid - ...`) не должна считаться вторым провалом.
+    """
+    from app.merge_test_gate import _partial_progress
+
+    progress = _partial_progress(
+        "FAILED tests/test_a.py::t2[a b PASSED c] - assert 1 == 2\n"
+        "tests/test_a.py::t1 PASSED [ 1%]\n"
+        "tests/test_a.py::t2[a b PASSED c] FAILED [ 2%]\n"
+        "tests/test_a.py::t3_inflight ",
+        ["tests/test_a.py", "tests/test_b.py"],
+    )
+
+    assert progress["failed_tests"] == ["tests/test_a.py::t2[a b PASSED c]"]
+    assert progress["passed_count"] == 1
+    assert progress["stopped_in"] == "tests/test_a.py::t3_inflight"
+    assert progress["unreached"] == ["tests/test_b.py"]
+
+
+def test_argv_verbosity_really_prints_per_test_lines(tmp_path):
+    """Гварда на неочевидную арифметику флагов, без которой всё выше — пустышка.
+
+    `-q` это −1, `-vv` это +2; сумма +1 даёт потестовые строки. Замена на «более
+    аккуратное» `-q -v` даёт сумму 0 — снова безымянные точки, и разбор перестаёт
+    что-либо находить, оставаясь зелёным на моках. Поэтому здесь настоящий pytest.
+    """
+    from app.merge_test_gate import pytest_argv
+
+    (tmp_path / "test_two.py").write_text(
+        "def test_first():\n    assert True\n\n\ndef test_second():\n    assert True\n",
+        encoding="utf-8",
+    )
+    proc = subprocess.run(
+        pytest_argv(["test_two.py"]),
+        cwd=str(tmp_path), capture_output=True, text=True, timeout=120, check=False,
+    )
+
+    assert proc.returncode == 0, proc.stdout + proc.stderr
+    assert "test_two.py::test_first PASSED" in proc.stdout
+    assert "test_two.py::test_second PASSED" in proc.stdout
+
+
 @pytest.mark.asyncio
 @pytest.mark.parametrize("gate_db", [{
     "app/widget.py": "VALUE = 1\n",
     "tests/test_widget.py": "def test_widget():\n    assert True\n",
 }], indirect=True)
 async def test_green_mapped_test_reaches_executor(gate_db, monkeypatch):
     result, calls = await _run_with_spy(monkeypatch, worktree=str(gate_db))
     assert len(calls) == 1


## LATER FIX aa7a76100c (56.4 days later): V-847: #V-847: parallelize full pytest and isolate fixtures
lines of origin it changed/deleted: 2
(code only, capped 400 lines)

V-847: #V-847: parallelize full pytest and isolate fixtures

Orchestra-Operation: e3d2b274-4da5-46c5-a019-d0b959632090


diff --git a/app/manager.py b/app/manager.py
index 1cd684757..ef4963f54 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -70,24 +70,25 @@ from app.errtext import err_text
 from app.tasks import spawn_supervised
 
 logger = logging.getLogger(__name__)
 
 _adhoc_serial = itertools.count(1)
 
 
 def enc_cli_dir(cwd: str) -> str:
-    """~/.claude/projects/<this> — cwd with '/' and '.' mapped to '-'. Case preserved.
+    """~/.claude/projects/<this> — path separators, dots, and underscores map to '-'.
+    Case is preserved.
 
     The leading '-' (from the leading '/') is part of the name and must stay:
     stripping it produced a directory the CLI never reads. The CLI also maps
-    dots in temporary paths to '-'. scripts/migrate_agent.py re-exports this
+    dots and underscores in temporary paths to '-'. scripts/migrate_agent.py re-exports this
     function so the encoding cannot drift a second time.
     """
-    return cwd.replace("/", "-").replace(".", "-")
+    return cwd.replace("/", "-").replace(".", "-").replace("_", "-")
 
 
 # Клиент MCP отваливается по таймауту через 30 с (mcp_stdio.py). Ждём заведомо меньше,
 # чтобы вызывающий получил внятный отказ, а не ReadTimeout, неотличимый от мёртвого сервера.
 LOCK_WAIT_LIMIT_SECONDS = 25.0
 class LockBusy(RuntimeError):
     """Лок сессии занят дольше отведённого: у вызова есть кто уступить и кому повторить."""
 
diff --git a/app/merge_test_gate.py b/app/merge_test_gate.py
index 5a5a192c4..0562484a6 100644
--- a/app/merge_test_gate.py
+++ b/app/merge_test_gate.py
@@ -286,50 +286,71 @@ def pytest_argv(
 # сюда не попадают и провал не считается дважды.
 # Вердикт берётся ПОСЛЕДНИЙ на строке, а не первый: nodeid параметризованного теста содержит
 # произвольный текст, в том числе пробелы и сами эти слова. Замер #336 — на строке
 # `tests/test_a.py::t2[a b PASSED c] FAILED [2%]` нежадный разбор возвращал PASSED, то есть
 # КРАСНЫЙ тест читался как зелёный; это ровно то направление ошибки, которого быть не должно.
 # Требование пробела перед вердиктом отсекает `nodeid[FAILED]` у теста, который ещё идёт.
 _NODEID_RE = re.compile(r"^\S+\.py::\S")
 _VERDICT_RE = re.compile(r"\s(?P<verdict>PASSED|FAILED|ERROR|XFAIL|XPASS|SKIPPED)(?=\s|$)")
+_XDIST_VERDICT_RE = re.compile(
+    r"^\[gw\d+\]\s+\[\s*\d+%\]\s+"
+    r"(?P<verdict>PASSED|FAILED|ERROR|XFAIL|XPASS|SKIPPED)\s+"
+    r"(?P<nodeid>\S+\.py::.+)$"
+)
 
 
 def _partial_progress(output: str, tests: list[str]) -> dict:
     """Что pytest успел сообщить до убийства по таймауту.
 
     Обе неудачи приходят одним и тем же `TimeoutExpired`, и без разбора этого выхода они
     неразличимы. Замер #336 на живых операциях: у #248 в убитом выходе стояли девять `F`
     (настоящая краснота), у #329 — сплошные точки (набор зелёный, просто не доехал); гейт
     доложил обоим одно и то же «inconclusive».
     """
     failed: list[str] = []
     passed_tests: list[str] = []
     passed = 0
     seen_files: set[str] = set()
     stopped_in = ""
+    running: set[str] = set()
     for raw in output.splitlines():
         line = raw.rstrip()
+        xdist_verdict = _XDIST_VERDICT_RE.match(line)
+        if xdist_verdict:
+            nodeid = xdist_verdict.group("nodeid").strip()
+            verdict = xdist_verdict.group("verdict")
+            running.discard(nodeid)
+            seen_files.add(nodeid.split("::", 1)[0])
+            if verdict in {"FAILED", "ERROR"}:
+                failed.append(nodeid)
+            elif verdict == "PASSED":
+                passed += 1
+                passed_tests.append(nodeid)
+            stopped_in = sorted(running)[-1] if running else ""
+            continue
         if not _NODEID_RE.match(line):
             continue
         verdicts = list(_VERDICT_RE.finditer(line))
         if not verdicts:
             # Имя напечатано, вердикта ещё нет — на этом тесте нас и прервали.
             stopped_in = line.strip()
+            running.add(stopped_in)
             seen_files.add(stopped_in.split("::", 1)[0])
             continue
         last = verdicts[-1]
         nodeid = line[:last.start()].strip()
+        running.discard(nodeid)
         seen_files.add(nodeid.split("::", 1)[0])
         if last.group("verdict") in {"FAILED", "ERROR"}:
             failed.append(nodeid)
         elif last.group("verdict") == "PASSED":
             passed += 1
             passed_tests.append(nodeid)
-        stopped_in = ""
+        stopped_in = sorted(running)[-1] if running else ""
     return {
         "failed_tests": failed,
         "passed_tests": passed_tests,
         "passed_count": passed,
         "stopped_in": stopped_in,
         "unreached": [test for test in tests if test not in seen_files],
     }
 
diff --git a/pyproject.toml b/pyproject.toml
index 9979e2609..4bb986433 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -52,17 +52,17 @@ exclude-newer = "2026-10-07T00:00:00Z"
 [tool.pytest.ini_options]
 # Живые пробы сняты со ВСЯКОГО прогона, а не только с команды merge-gate (#328 закрыл
 # лишь гейт). Плоский `uv run pytest -q` собирал их обратно и вис до упора на исчерпанной
 # квоте Codex: замер #336 — прогон убит по общему таймауту с EXIT=124 на 78%, окно потеряно
 # молча. Защита, действующая только когда запускающий помнит про флаг, в автоматике не
 # исполняется. CLI перебивает эту строку, а не складывается с ней (`-m` — одно значение,
 # побеждает последнее): `pytest -m live_probe tests/` собирает 3 пробы из 3214, обычный
 # прогон — 3211 из 3214, ровно столько же, сколько командой гейта.
-addopts = ["-m", "not live_probe"]
+addopts = ["-m", "not live_probe", "-n", "2", "--dist=loadscope"]
 testpaths = ["tests"]
 norecursedirs = ["worktrees", ".venv", "data", "docs"]
 markers = [
     "needs_two_users: требует беспарольного sudo — владение файлами не моделируется заглушками",
     "needs_model: требует эмбеддер (orchestra[rag]) — индексация и поиск не моделируются заглушками",
     "browser: поднимает НАСТОЯЩИЙ Chromium через Playwright. Снят с блокирующего набора merge-гейта (`-m \"not live_probe and not browser\"`), но продолжает гоняться в CI отдельной джобой и вручную: `uv run pytest -m browser tests/`. Маркер ставится автоматически по факту запроса браузерной фикстуры (`tests/conftest.py`), списком файлов не задаётся. Состав закреплён `test_browser_inventory_is_explicit`",
     "live_probe: тратит настоящий ход провайдера (поднимает CLI, шлёт запрос). Краснеет от квоты и капризов провайдера, а не от диффа, поэтому merge-gate его не гоняет — запускать вручную `uv run pytest -m live_probe tests/`. Новую такую пробу заводить только вместе с записью в test_live_probe_inventory_is_explicit",
 ]
diff --git a/scripts/migrate_agent.py b/scripts/migrate_agent.py
index 63c9d6704..463db9295 100755
--- a/scripts/migrate_agent.py
+++ b/scripts/migrate_agent.py
@@ -13,17 +13,17 @@ target's orchestra root / scope root.
         --name ParsingMaxim \
         --from root@laptop --to root@<VPS_IP> \
         --from-orchestra /mnt/data/Projects/Python/orchestra \
         --to-orchestra   /home/kesha/orchestra \
         --from-scope /mnt/data/Projects/Python/Parsing \
         --to-scope   /home/kesha/projects/Parsing
 
 Two path encodings are handled (matching the app):
-  - CLI transcript dir : app.manager.enc_cli_dir (leading '-' kept, '.' → '-')
+  - CLI transcript dir : app.manager.enc_cli_dir (leading '-' kept, '.', '_' → '-')
   - worktree subdir    : <root>/worktrees/<slugify(scope)>/<name>   (lowercased)
 
 Everything is created over ssh as root, but Orchestra and the Claude CLI run as the
 service user — so every path we write is handed over with chown and verified.
 
 Preconditions (fail loud): the orchestrator and every non-archived worker must be IDLE.
 """
 
diff --git a/tests/test_audit0901_delivery.py b/tests/test_audit0901_delivery.py
index d8105b245..908a7a3e8 100644
--- a/tests/test_audit0901_delivery.py
+++ b/tests/test_audit0901_delivery.py
@@ -93,44 +93,53 @@ async def _accept(*, delivery_id, message):
 class _FakeRequest:
     def __init__(self):
         self.disconnected = False
 
     async def is_disconnected(self):
         return self.disconnected
 
 
+@pytest.fixture
+def live_broker(monkeypatch):
+    from app import live_broker as live_broker_module
+    from app.live_broker import LiveBroker
+
+    broker = LiveBroker()
+    monkeypatch.setattr(live_broker_module, "broker", broker)
+    return broker
+
+
 async def _next_event(events):
     raw = await events.__anext__()
     return json.loads(raw.removeprefix("data: ").strip())
 
 
 @pytest.mark.asyncio
 async def test_stream_reports_the_live_status_after_the_session_loads(
-    delivery_db, monkeypatch,
+    delivery_db, monkeypatch, live_broker,
 ):
     """Стрим, открытый на НЕ загруженной сессии, обязан догнать её реальный статус."""
     from app.deps import manager
-    from app.live_broker import broker
     from app.routes.sessions import stream_session_logs
 
     assert manager.get(TARGET_ID) is None, "сессия не должна быть загружена на коннекте"
     response = await stream_session_logs(TARGET_NAME, SCOPE, _FakeRequest())
     events = response.body_iterator
     try:
         opened = await _next_event(events)
         assert opened["type"] == "__session"
         assert opened["agent_status"] == "idle"
 
         # Воркеру пришло сообщение: сессию загрузили, пошёл ход, логи идут в ТОТ ЖЕ стрим.
         monkeypatch.setitem(
             manager.sessions, TARGET_ID,
             SimpleNamespace(status=SimpleNamespace(value="running")),
         )
-        broker.publish(TARGET_ID, {"type": "stream", "content": "работаю"})
+        live_broker.publish(TARGET_ID, {"type": "stream", "content": "работаю"})
 
         live = await _next_event(events)
         assert live["type"] == "stream"
         assert live["agent_status"] == "running", (
             "статус заморожен на коннекте: событие идущего хода штампуется 'idle', "
             "и клиент затирает им верный статус из опроса"
         )
     finally:
diff --git a/tests/test_compact_chat_672.py b/tests/test_compact_chat_672.py
index bb8ae78dc..b7d1fe5ea 100644
--- a/tests/test_compact_chat_672.py
+++ b/tests/test_compact_chat_672.py
@@ -96,17 +96,17 @@ async def test_compact_events_and_statuses_do_not_reach_telegram_or_mirror(tb, m
          "content": "turn ended (end_turn, 1 turns, $0.01 turn)"},
     ])
 
     assert sent == []
     assert mirrored == []
 
 
 def test_compact_journal_rows_render_as_one_separate_collapsible_block(
-    dashboard_browser: Browser,
+    dashboard_browser: Browser, tmp_path: Path,
 ):
     fixture_path = Path(__file__).parent.parent / ".orchestra/tasks/V-672/compact-fixture.json"
     fixture = json.loads(fixture_path.read_text())
     assert fixture["source"]["legacy_tool_result_rows_without_tool_use_id"] == 34
     page = _open_tool_correlation_page(dashboard_browser, compact_mode=False)
     page.evaluate("""fixture => {
         for (const row of fixture.events) {
             addChatEntry('compact_event', JSON.stringify(row.content), null, null, {
@@ -131,17 +131,17 @@ def test_compact_journal_rows_render_as_one_separate_collapsible_block(
     expect(card).to_contain_text("Context compaction")
     expect(card).to_contain_text("In progress")
     card.evaluate("""card => {
         card.open = true;
         card.querySelector('details[data-phase="audit"]').open = true;
         card.querySelector('details[data-phase="audit"] details').open = true;
     }""")
     assert card.evaluate("card => card.open && card.querySelector('details[data-phase=\"audit\"]').open")
-    screenshot = Path(__file__).parent.parent / ".orchestra/tasks/V-672/compact-card.png"
+    screenshot = tmp_path / "compact-card.png"
     page.evaluate("""() => {
         const clone = document.querySelector('.compact-event-card').cloneNode(true);
         clone.id = 'compact-card-screenshot';
         clone.style.cssText = 'position:fixed;top:8px;left:8px;width:900px;max-height:none;overflow:visible;z-index:99999;background:#0b1120';
         document.body.appendChild(clone);
     }""")
     page.locator("#compact-card-screenshot").screenshot(path=str(screenshot))
     page.locator("#compact-card-screenshot").evaluate("node => node.remove()")
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index 466dc31a4..5e84f7151 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -1036,17 +1036,19 @@ def test_hidden_orchestrator_menu_shares_tab_status_and_cache_builders():
     assert "_updateHiddenBtn()" in live_update
 
 
 def test_hidden_orchestrator_list_reuses_tab_status_and_cache(dashboard_browser: Browser):
     page = dashboard_browser.new_page()
     try:
         _goto_dashboard(page)
         result = page.evaluate("""() => {
-            const turn = new Date(Date.now() - 5 * 60_000).toISOString();
+            const now = Date.now();
+            Date.now = () => now;
+            const turn = new Date(now - 5 * 60_000).toISOString();
             const rows = [
                 {name: 'running-orchestrator', status: 'running', any_running: true, any_waiting: false},
                 {name: 'waiting-orchestrator', status: 'idle', any_running: false, any_waiting: true},
                 {name: 'idle-orchestrator', status: 'idle', any_running: false, any_waiting: false},
             ].map((row, index) => ({
                 id: `hidden-${index}`, scope: `/hidden/${index}`, ...row,
                 cache_ttl_seconds: 3600, last_turn_ts: turn,
             }));
diff --git a/tests/test_grok_usage_frontend.py b/tests/test_grok_usage_frontend.py
index 7295cf020..8f5d6d0d8 100644
--- a/tests/test_grok_usage_frontend.py
+++ b/tests/test_grok_usage_frontend.py
@@ -4,19 +4,16 @@ import pytest
 from playwright.sync_api import Browser, expect, sync_playwright
 
 
 ROOT = Path(__file__).parent.parent
 UTILS_JS = ROOT / "app/static/js/utils.js"
 CONNECTION_JS = ROOT / "app/static/js/connection.js"
 USAGE_JS = ROOT / "app/static/js/usage.js"
 STYLE_CSS = ROOT / "app/static/css/style.css"
-USAGE_SHOT_DIR = ROOT / ".orchestra/tasks/356"
-
-
 @pytest.fixture(scope="module")
 def browser():
     with sync_playwright() as playwright:
         instance = playwright.chromium.launch(headless=True)
         yield instance
         instance.close()
 
 
@@ -204,18 +201,17 @@ def test_usage_bar_shows_spark_label_and_release_statuses(browser):
         spark: _quotaMapLaneRelease(_usageData.codex.spark.primary, 'codex_spark').status,
     })""")
     assert release_states == {"short": "open", "gated": "opens_in", "spark": "open"}
     for provider in ("claude", "codex", "codex-spark"):
         expect(page.locator(f'[data-usage-compact-provider="{provider}"]')).to_have_count(1)
     page.close()
 
 
-def test_usage_bar_renders_each_provider_as_two_columns(browser):
-    USAGE_SHOT_DIR.mkdir(parents=True, exist_ok=True)
+def test_usage_bar_renders_each_provider_as_two_columns(browser, tmp_path):
     usage = {
         "anthropic": {
             "five_hour": {"utilization": 38, "window_minutes": 300, "resets_at": "2099-01-01T00:00:00.000Z"},
             "seven_day": {"utilization": 60, "window_minutes": 10080, "resets_at": "2099-01-01T00:00:00.000Z"},
         },
         "codex": {
             "primary": {"utilization": 40, "window_minutes": 10080, "resets_at": "2099-01-01T00:00:00.000Z"},
             "spark": {"primary": {"utilization": 57, "window_minutes": 10080, "resets_at": "2099-01-01T00:00:00.000Z"}},
@@ -309,17 +305,17 @@ def test_usage_bar_renders_each_provider_as_two_columns(browser):
 
         for provider in ("claude", "codex", "codex-spark", "grok"):
             expect(page.locator(f'[data-usage-compact-provider="{provider}"]')).to_have_count(1)
 
         bounds = page.locator("#usage-bar").bounding_box()
         assert bounds is not None
         assert bounds["height"] < 63
 
-        page.locator("#usage-bar").screenshot(path=str(USAGE_SHOT_DIR / f"usage-bar-provider-grid-{width}.png"))
+        page.locator("#usage-bar").screenshot(path=str(tmp_path / f"usage-bar-provider-grid-{width}.png"))
         page.close()
 
 
 def test_usage_controls_stay_visible_across_desktop_widths(browser):
     for width in (1280, 1440, 1680, 1920):
         page = _page(browser, True)
         page.set_viewport_size({"width": width, "height": 900})
         page.add_style_tag(path=str(STYLE_CSS))
diff --git a/tests/test_live_tool_activity_831.py b/tests/test_live_tool_activity_831.py
index f470d6521..eb096e7b8 100644
--- a/tests/test_live_tool_activity_831.py
+++ b/tests/test_live_tool_activity_831.py
@@ -40,16 +40,25 @@ def session(monkeypatch):
 @pytest.fixture
 def published(monkeypatch):
     from app.live_broker import broker
     out = []
     monkeypatch.setattr(broker, "publish", lambda sid, payload: out.append(payload))
     return out
 
 
+@pytest.fixture
+def live_broker(monkeypatch):
+    from app import live_broker as live_broker_module
+
+    broker = LiveBroker()
+    monkeypatch.setattr(live_broker_module, "broker", broker)
+    return broker
+
+
 # ── session: partials go to the broker, never to the DB ──
 
 def test_tool_arguments_and_thinking_are_brokered_not_persisted(session, published):
     session._log = MagicMock()
     session._submit_db_write = MagicMock()
     meta = {"tool_use_id": "toolu_A", "tool_name": "Bash", "short_name": "Bash"}
 
     session._handle_event(AgentEvent("tool_input_stream", "", meta))
@@ -72,27 +81,25 @@ def test_subagent_partials_nest_under_their_subagent(session, published):
 
     assert published == [{"type": "subagent_stream", "event_type": "tool_input_stream",
                           "content": '{"file_path"', "subagent_id": "task-1",
                           "item_id": "toolu_S", "tool_name": "Read"}]
     session._log.assert_not_called()
 
 
 @pytest.mark.asyncio
-async def test_final_tool_call_is_persisted_and_retires_the_live_replay(session):
-    from app.live_broker import broker
-    broker.clear_live(session.id)
+async def test_final_tool_call_is_persisted_and_retires_the_live_replay(session, live_broker):
     session._handle_event(AgentEvent("tool_input_stream", '{"command": "ls"}',
                                      {"tool_use_id": "toolu_F", "tool_name": "Bash"}))
-    assert ("tool_input_stream", "toolu_F") in broker._live.get(session.id, {})
+    assert ("tool_input_stream", "toolu_F") in live_broker._live.get(session.id, {})
 