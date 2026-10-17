# Candidate cand-54

## ORIGIN commit d607f5fc7e (2026-09-21): V-607: #V-607: add mutation test gate for worker merges
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/merge_operations.py b/app/merge_operations.py
index 17c3efee3..2efd50da4 100644
--- a/app/merge_operations.py
+++ b/app/merge_operations.py
@@ -1800,24 +1800,30 @@ async def _run_operation(operation_id: str) -> None:
 
                 test_gate = await asyncio.to_thread(
                     evaluate_test_gate,
                     current["worktree_path"],
                     target_ref=str(target.get("branch") or ""),
                     target_sha=str(target.get("sha") or ""),
                 )
                 strict_mapped = bool(oracle.get("required"))
+                mutation_gate = test_gate.get("mutation_gate") or {}
+                mutation_failed = mutation_gate.get("status") == FAILED
                 gate_blocks = test_gate["status"] in {FAILED, INCONCLUSIVE} or (
                     strict_mapped and test_gate["status"] != PASSED
                 )
                 if gate_blocks:
                     code = (
-                        "TEST_GATE_FAILED"
-                        if test_gate["status"] == FAILED
-                        else "TEST_GATE_INCONCLUSIVE"
+                        "TEST_MUTATION_GATE_FAILED"
+                        if mutation_failed and test_gate["status"] == FAILED
+                        else (
+                            "TEST_GATE_FAILED"
+                            if test_gate["status"] == FAILED
+                            else "TEST_GATE_INCONCLUSIVE"
+                        )
                     )
                     # Учёт дописывается ПОСЛЕ хвоста выхода: получатель видит `[-400:]`,
                     # то есть конец строки, — сводка в начале до него не доехала бы.
                     progress = describe_progress(test_gate)
                     error = _error(
                         code,
                         (
                             f"Merge test gate {test_gate['status']}"
@@ -1830,17 +1836,22 @@ async def _run_operation(operation_id: str) -> None:
                         retryable=test_gate["status"] in {INCONCLUSIVE, SKIPPED},
                     )
                     # Разные исходы требуют разных действий, и раньше оба получали
                     # «Fix the failing merge-gate tests» — для незавершённого прогона это
                     # прямая ложь (чинить нечего), из-за которой #329 смержили руками.
                     next_action = (
                         _action(
                             "FIX_TESTS_THEN_RETRY",
-                            "Fix the failing merge-gate tests, then start a new merge.",
+                            (
+                                "Fix the changed tests so they fail when the worker source "
+                                "change is rolled back, then start a new merge."
+                                if mutation_failed
+                                else "Fix the failing merge-gate tests, then start a new merge."
+                            ),
                         )
                         if test_gate["status"] == FAILED
                         else _action(
                             "TEST_GATE_UNFINISHED",
                             "No test was reported red — the gate ran out of its time "
                             "budget. Do NOT 'fix' tests. Retry the same operation; if it "
                             "keeps running out, the mapped subset costs more than the "
                             "gate budget and the merge needs an explicit decision.",
diff --git a/app/merge_test_gate.py b/app/merge_test_gate.py
index 374667614..b3d7f1f5c 100644
--- a/app/merge_test_gate.py
+++ b/app/merge_test_gate.py
@@ -26,19 +26,24 @@ a verdict pytest already printed (`FAILED`/`ERROR`) makes it FAILED — a red te
 or not the rest ran — and only a kill with no verdict at all is INCONCLUSIVE, reported with what
 was verified and what was never reached. Does not close bash: the worker can rewrite this file.
 """
 
 from __future__ import annotations
 
 import os
 import re
+import shutil
 import subprocess
 import sys
+import tarfile
+import tempfile
 import time
+import ast
+from contextlib import contextmanager
 from pathlib import Path
 
 from app.acceptance import FAILED, INCONCLUSIVE, PASSED, SKIPPED
 
 MAX_TEST_FILES = 12
 MAX_BATCH_TESTS = 6
 
 # Бюджет ВЫВЕДЕН ИЗ ЗАМЕРА (#336), а не назначен. Прежние фиксированные 180 с числом про
@@ -84,16 +89,22 @@ _BATCH_DIAGNOSTIC_LIMIT = 4000
 #   `-vv`, по которым `_partial_progress` отличает «набор красный» от «мы не успели». `signal`
 #   поднимает исключение в главном потоке: висящий узел получает свой `FAILED` с именем, а
 #   остаток партии продолжает считаться. Главный поток здесь и нужный: `pytest-asyncio` крутит
 #   корутину через `run_until_complete` на нём же, а синхронный Playwright ждёт драйвер на
 #   прерываемом чтении. Узел, которому законно нужно больше, ставит свой
 #   `@pytest.mark.timeout(N)` — маркер сильнее флага (`tests/test_native_history_import.py:199`).
 PER_TEST_TIMEOUT_SECONDS = 120.0
 PER_TEST_TIMEOUT_METHOD = "signal"
+# The rollback probe is deliberately bounded independently of the existing mapped-test
+# budget: it is evidence for the changed tests, not a second full merge suite.  Production
+# measurements on V-606/V-602/V-603 took 16.89/14.03/16.60 s of pytest time, so 25 s leaves
+# headroom for startup and load; an unfinished probe is reported as INCONCLUSIVE and does not
+# masquerade as proof.
+MUTATION_MAX_TIMEOUT_SECONDS = 25.0
 
 
 def budget_for(file_count: int) -> float:
     """Бюджет всего гейта под набор из `file_count` файлов."""
     return min(
         MAX_TIMEOUT_SECONDS,
         BASE_TIMEOUT_SECONDS + PER_FILE_TIMEOUT_SECONDS * max(0, file_count),
     )
@@ -331,34 +342,56 @@ def describe_progress(result: dict) -> str:
         parts.append(f"RED: {shown}" + (f" (+{extra} more)" if extra > 0 else ""))
     if result.get("stopped_in"):
         parts.append(f"ran out of budget inside {result['stopped_in']}")
     if result.get("unreached"):
         parts.append(f"never reached: {', '.join(result['unreached'])}")
     return "; ".join(parts)
 
 
-def run_pytest(worktree: str, tests: list[str], *, timeout: float | None = None) -> dict:
+def run_pytest(
+    worktree: str,
+    tests: list[str],
+    *,
+    timeout: float | None = None,
+    interpreter: str | None = None,
+) -> dict:
     budget = budget_for(len(tests)) if timeout is None else timeout
-    interpreter = _pytest_interpreter(worktree)
+    interpreter = interpreter or _pytest_interpreter(worktree)
     argv = pytest_argv(tests, interpreter=interpreter)
     env = os.environ.copy()
+    # Merge-gate runs beside the live Orchestra process.  Its state selectors must never
+    # point pytest at the service database/task repository (the latter once consumed a
+    # real task from a test fixture).  Remove them before pytest imports ``app`` and give
+    # every invocation disposable state of its own.  Quota and systemd variables are also
+    # live-process inputs; ordinary tests have their own deterministic fixtures.
+    for name in (
+        "ORCHESTRA_DB_PATH", "ORCHESTRA_TASK_REPOSITORY", "ORCHESTRA_TASK_PREFIX",
+        "NOTIFY_SOCKET", "SYSTEMD_EXEC_PID", "LISTEN_PID", "LISTEN_FDS", "LISTEN_FDNAMES",
+        "QUOTA_GATED_LANES", "QUOTA_CURVED_LANES", "QUOTA_HARD_STOP_PCT",
+        "QUOTA_LANE_HARD_STOP_PCT", "QUOTA_TOLERANCE_START_PP",
+        "QUOTA_TOLERANCE_END_PP", "QUOTA_CURVE_EXPONENT",
+    ):
+        env.pop(name, None)
     root = str(Path(worktree).resolve())
     prior = env.get("PYTHONPATH", "")
     env["PYTHONPATH"] = root if not prior else f"{root}{os.pathsep}{prior}"
     try:
-        proc = subprocess.run(
-            argv,
-            cwd=worktree,
-            env=env,
-            capture_output=True,
-            text=True,
-            timeout=budget,
-            check=False,
-        )
+        with tempfile.TemporaryDirectory(prefix="orchestra-merge-gate-") as isolated:
+            env["ORCHESTRA_DB_PATH"] = str(Path(isolated) / "orchestra.db")
+            env["ORCHESTRA_TASK_REPOSITORY"] = str(Path(isolated) / "tasks")
+            proc = subprocess.run(
+                argv,
+                cwd=worktree,
+                env=env,
+                capture_output=True,
+                text=True,
+                timeout=budget,
+                check=False,
+            )
     except FileNotFoundError:
         return {
             "status": INCONCLUSIVE, "reason": "not_found",
             "exit_code": None, "output": _diagnostic_output(interpreter, argv[0]),
             "tests": tests,
         }
     except subprocess.TimeoutExpired as exc:
         out = _normalize_output(exc.stdout) + _normalize_output(exc.stderr)
@@ -520,16 +553,280 @@ def _batch_result(worktree: str, batches: list[list[str]]) -> dict:
             (result["stopped_in"] for result in results if result.get("stopped_in")), ""
         ),
         "unreached": [
             test for result in results for test in result.get("unreached", [])
         ],
     }
 
 
+_TEST_PATH_PREFIX = "tests/"
+_SOURCE_PREFIXES = ("app/", "scripts/")
+_NON_SOURCE_PREFIXES = (
+    ".orchestra/", ".github/", "docs/", "prompts/", "prompt/",
+)
+_NON_SOURCE_SUFFIXES = {
+    ".md", ".rst", ".txt", ".toml", ".ini", ".cfg", ".yaml", ".yml", ".json",
+}
+
+
+def changed_test_paths(changed: list[str]) -> list[str]:
+    """Return test modules supplied by the worker, not merely source-mapped tests."""
+    return sorted({
+        path.replace("\\", "/").lstrip("./")
+        for path in changed
+        if path.replace("\\", "/").lstrip("./").startswith(_TEST_PATH_PREFIX)
+        and path.replace("\\", "/").lstrip("./").endswith(".py")
+    })
+
+
+def changed_source_paths(changed: list[str]) -> list[str]:
+    """Classify executable changes while leaving docs, config and prompts out."""
+    sources: set[str] = set()
+    for raw in changed:
+        path = raw.replace("\\", "/").lstrip("./")
+        if not path or path.startswith(_TEST_PATH_PREFIX) or path.startswith(_NON_SOURCE_PREFIXES):
+            continue
+        suffix = Path(path).suffix.lower()
+        if suffix in _NON_SOURCE_SUFFIXES:
+            continue
+        if path.startswith(_SOURCE_PREFIXES) or suffix in {".py", ".js", ".ts", ".tsx", ".jsx", ".css", ".html"}:
+            sources.add(path)
+    return sorted(sources)
+
+
+def _changed_added_lines(worktree: str, target_commit: str, path: str) -> set[int] | None:
+    """Return worker-side lines touched by a committed diff, or None for untracked files."""
+    diff = _git(
+        Path(worktree), "diff", "--no-renames", "--unified=0",
+        f"{target_commit}...HEAD", "--", path,
+    )
+    if diff is None:
+        return None
+    lines: set[int] = set()
+    current = 0
+    for raw in diff.splitlines():
+        if raw.startswith("@@"):
+            match = re.search(r"\+(\d+)(?:,(\d+))?", raw)
+            if not match:
+                continue
+            current = int(match.group(1))
+            count = 1 if match.group(2) is None else int(match.group(2))
+            lines.update(range(current, current + count))
+            continue
+        if raw.startswith("+") and not raw.startswith("+++"):
+            current += 1
+        elif raw.startswith("-") or raw.startswith("\\"):
+            continue
+        elif current:
+            current += 1
+    return lines
+
+
+def _test_nodes_for_file(path: str, source: str, changed_lines: set[int]) -> list[str] | None:
+    """Map changed lines to pytest node IDs; None requests a safe file fallback."""
+    try:
+        tree = ast.parse(source, filename=path)
+    except SyntaxError:
+        return None
+    nodes: list[tuple[str, int, int]] = []
+
+    def visit(body: list[ast.stmt], parents: tuple[str, ...] = ()) -> None:
+        for node in body:
+            if isinstance(node, ast.ClassDef):
+                visit(node.body, parents + (node.name,))
+                continue
+            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
+                continue
+            if not node.name.startswith("test_"):
+                visit(getattr(node, "body", []), parents)
+                continue
+            end = getattr(node, "end_lineno", node.lineno)
+            starts = [node.lineno]
+            starts.extend(dec.lineno for dec in node.decorator_list)
+            start = min(starts)
+            identity = "::".join((path, *parents, node.name))
+            nodes.append((identity, start, end))
+
+    visit(tree.body)
+    if not nodes:
+        return None
+    selected = [identity for identity, start, end in nodes
+                if any(start <= line <= end for line in changed_lines)]
+    covered = {
+        line for _identity, start, end in nodes
+        for line in changed_lines if start <= line <= end
+    }
+    # A changed import/helper/fixture/class setup is semantically shared by tests. Running
+    # one guessed node would claim proof for siblings, so keep the whole file in that case.
+    if covered != changed_lines:
+        return None
+    return sorted(set(selected)) or None
+
+
+def changed_test_nodes(
+    worktree: str, target_commit: str, tests: list[str],
+) -> tuple[list[str], list[str]]:
+    """Select changed test functions, with file fallback for ambiguous Python diffs."""
+    selected: list[str] = []
+    fallback: list[str] = []
+    for path in tests:
+        lines = _changed_added_lines(worktree, target_commit, path)
+        source_path = Path(worktree) / path
+        if lines is None or not source_path.is_file():
+            fallback.append(path)
+            continue
+        nodes = _test_nodes_for_file(path, source_path.read_text(encoding="utf-8"), lines)
+        if nodes is None:
+            fallback.append(path)
+        else:
+            selected.extend(nodes)
+    return sorted(set(selected)), sorted(set(fallback))
+
+
+def _target_commit(worktree: str, target_ref: str, target_sha: str) -> str | None:
+    ref = target_sha.strip() or target_ref.strip() or "main"
+    resolved = _git(Path(worktree), "rev-parse", "--verify", f"{ref}^{{commit}}")
+    return resolved.strip() if resolved else None
+
+
+def _copy_test_into_tree(worker: Path, target: Path, relative: str) -> None:
+    source = worker / relative
+    destination = target / relative
+    if not source.exists() and not source.is_symlink():
+        if destination.exists() or destination.is_symlink():
+            if destination.is_dir() and not destination.is_symlink():
+                shutil.rmtree(destination)
+            else:
+                destination.unlink()
+        return
+    destination.parent.mkdir(parents=True, exist_ok=True)
+    if destination.exists() or destination.is_symlink():
+        if destination.is_dir() and not destination.is_symlink():
+            shutil.rmtree(destination)
+        else:
+            destination.unlink()
+    if source.is_symlink():
+        destination.symlink_to(os.readlink(source))
+    else:
+        shutil.copy2(source, destination)
+
+
+@contextmanager
+def _mutation_tree(worker: str, target_commit: str, tests: list[str]):
+    """Yield a disposable target checkout overlaid with the worker's changed tests."""
+    temporary = tempfile.TemporaryDirectory(prefix="orchestra-merge-mutation-")
+    root = Path(temporary.name)
+    try:
+        archive = root / "target.tar"
+        with archive.open("wb") as stream:
+            proc = subprocess.run(
+                ["git", "archive", "--format=tar", target_commit],
+                cwd=worker, stdout=stream, stderr=subprocess.PIPE,
+                text=False, timeout=30, check=False,
+            )
+        if proc.returncode != 0:
+            detail = (proc.stderr or b"").decode("utf-8", "replace").strip() or f"exit {proc.returncode}"
+            raise RuntimeError(f"git archive target failed: {detail}")
+        tree = root / "tree"
+        tree.mkdir()
+        with tarfile.open(archive, "r:") as tar:
+            tar.extractall(tree, filter="data")
+        for path in tests:
+            _copy_test_into_tree(Path(worker), tree, path)
+        yield tree
+    finally:
+        temporary.cleanup()
+
+
+def evaluate_mutation_gate(
+    worktree: str,
+    changed: list[str],
+    *,
+    target_ref: str = "",
+    target_sha: str = "",
+    interpreter: str | None = None,
+) -> dict:
+    """Run worker tests against target sources in an isolated disposable tree."""
+    tests = changed_test_paths(changed)
+    sources = changed_source_paths(changed)
+    result = {
+        "status": SKIPPED,
+        "reason": "no_changed_tests" if not tests else "no_changed_sources",
+        "exit_code": None,
+        "output": "",
+        "tests": tests,
+        "changed_tests": tests,
+        "changed_sources": sources,
+        "interpreter": interpreter or _pytest_interpreter(worktree),
+        "selected_nodes": [],
+        "fallback_files": [],
+    }
+    if not tests or not sources:
+        return result
+    commit = _target_commit(worktree, target_ref, target_sha)
+    if not commit:
+        return {
+            **result,
+            "status": INCONCLUSIVE,
+            "reason": "target_unavailable",
+            "output": "cannot resolve target commit for mutation tree",
+        }
+    selected_nodes, fallback_files = changed_test_nodes(worktree, commit, tests)
+    selected_tests = selected_nodes + fallback_files
+    if not selected_tests:
+        return {
+            **result,
+            "status": INCONCLUSIVE,
+            "reason": "changed_test_nodes_unavailable",
+            "output": "changed test files contain no selectable test nodes",
+            "selected_nodes": [],
+            "fallback_files": [],
+        }
+    try:
+        with _mutation_tree(worktree, commit, tests) as tree:
+            second = run_pytest(
+                str(tree), selected_tests,
+                timeout=MUTATION_MAX_TIMEOUT_SECONDS,
+                interpreter=result["interpreter"],
+            )
+    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
+        return {
+            **result,
+            "status": INCONCLUSIVE,
+            "reason": "tree_failed",
+            "output": str(exc),
+        }
+    mutation = {
+        **second,
+        "changed_tests": tests,
+        "changed_sources": sources,
+        "target_sha": commit,
+        "interpreter": result["interpreter"],
+        "selected_nodes": selected_nodes,
+        "fallback_files": fallback_files,
+    }
+    if second["status"] == FAILED:
+        # The rollback is expected to break a regression test: that is the proof that
+        # the worker test actually watches the source change.
+        return {**mutation, "status": PASSED, "reason": "guarded_source_change"}
+    if second["status"] in {INCONCLUSIVE, SKIPPED}:
+        return mutation
+    # A passing target-source run means the changed tests did not observe the source delta.
+    return {
+        **mutation,
+        "status": FAILED,
+        "reason": "tests_not_guarding_source",
+        "output": (
+            (second.get("output") or "")
+            + "\nworker tests also pass with target sources; no regression is guarded"
+        ),
+    }
+
+
 def evaluate_test_gate(
     worktree: str,
     *,
     target_ref: str = "",
     target_sha: str = "",
 ) -> dict:
     if target_ref or target_sha:
         changed = changed_paths(
@@ -540,23 +837,76 @@ def evaluate_test_gate(
     evidence = {
         "target_ref": target_ref,
         "target_sha": target_sha,
     }
     if changed is None:
         return {
             "status": SKIPPED, "reason": "no_diff",
             "exit_code": None, "output": "", "tests": [], "mapped_files": [],
+            "changed_tests": [], "changed_sources": [],
+            "interpreter": _pytest_interpreter(worktree),
+            "mutation_gate": {
+                "status": SKIPPED, "reason": "no_diff", "tests": [],
+                "changed_tests": [], "changed_sources": [],
+                "interpreter": _pytest_interpreter(worktree),
+            },
             **evidence,
         }
     tests = select_tests(changed, worktree=worktree)
     if not tests:
+        changed_tests = changed_test_paths(changed)
+        changed_sources = changed_source_paths(changed)
+        interpreter = _pytest_interpreter(worktree)
         return {
             "status": SKIPPED, "reason": "no_mapped_tests",
             "exit_code": None, "output": "", "tests": [], "mapped_files": [],
+            "changed_tests": changed_tests, "changed_sources": changed_sources,
+            "interpreter": interpreter,
+            "mutation_gate": {
+                "status": SKIPPED,
+                "reason": "no_mapped_tests",
+                "exit_code": None,
+                "output": "",
+                "tests": changed_tests,
+                "changed_tests": changed_tests,
+                "changed_sources": changed_sources,
+                "interpreter": interpreter,
+            },
             **evidence,
         }
     if len(tests) > MAX_TEST_FILES:
         batches = _ordered_batches(tests)
         result = _batch_result(worktree, batches)
     else:
         result = run_pytest(worktree, tests)
-    return {**result, "mapped_files": tests, **evidence}
+    result = {
+        **result,
+        "mapped_files": tests,
+        "changed_tests": changed_test_paths(changed),
+        "changed_sources": changed_source_paths(changed),
+        "interpreter": _pytest_interpreter(worktree),
+        **evidence,
+    }
+    if result["status"] == PASSED:
+        mutation = evaluate_mutation_gate(
+            worktree,
+            changed,
+            target_ref=target_ref,
+            target_sha=target_sha,
+            interpreter=result["interpreter"],
+        )
+    else:
+        mutation = {
+            "status": SKIPPED,
+            "reason": "first_gate_not_passed",
+            "exit_code": None,
+            "output": "",
+            "tests": result["changed_tests"],
+            "changed_tests": result["changed_tests"],
+            "changed_sources": result["changed_sources"],
+            "interpreter": result["interpreter"],
+        }
+    result["mutation_gate"] = mutation
+    if mutation["status"] == FAILED:
+        result["status"] = FAILED
+        result["reason"] = mutation.get("reason") or "mutation_failed"
+    return result
diff --git a/tests/test_merge_test_gate.py b/tests/test_merge_test_gate.py
index d579dc153..51450e508 100644
--- a/tests/test_merge_test_gate.py
+++ b/tests/test_merge_test_gate.py
@@ -29,16 +29,19 @@ def _repo(tmp_path: Path, *, files: dict[str, str]) -> Path:
     repo.mkdir()
     _git(repo, "init", "-b", "main")
     _git(repo, "config", "user.email", "t@t")
     _git(repo, "config", "user.name", "t")
     (repo / "README").write_text("base\n", encoding="utf-8")
     _git(repo, "add", "README")
     _git(repo, "commit", "-m", "base")
     _git(repo, "checkout", "-b", "task-42/worker")
+    if any(rel.startswith("app/") for rel in files):
+        (repo / "app").mkdir(exist_ok=True)
+        (repo / "app" / "__init__.py").write_text("", encoding="utf-8")
     for rel, text in files.items():
         path = repo / rel
         path.parent.mkdir(parents=True, exist_ok=True)
         path.write_text(text, encoding="utf-8")
     _git(repo, "add", "-A")
     _git(repo, "commit", "-m", "change")
     return repo
 
@@ -116,16 +119,196 @@ def test_select_tests_maps_stem_and_routes(tmp_path):
 
     mapped = select_tests(
         ["app/widget.py", "app/routes/tm.py"], worktree=str(tmp_path),
     )
     assert mapped == ["tests/test_routes_surface.py", "tests/test_widget.py"]
     assert select_tests(["docs/a.md"], worktree=str(tmp_path)) == []
 
 
+def _mutation_repo(tmp_path: Path, test_body: str, *, source_changed: bool = True) -> tuple[Path, str]:
+    repo = tmp_path / "mutation-repo"
+    repo.mkdir()
+    _git(repo, "init", "-b", "main")
+    _git(repo, "config", "user.email", "t@t")
+    _git(repo, "config", "user.name", "t")
+    (repo / "app").mkdir()
+    (repo / "tests").mkdir()
+    (repo / "app" / "__init__.py").write_text("", encoding="utf-8")
+    (repo / "app" / "widget.py").write_text("VALUE = 1\n", encoding="utf-8")
+    (repo / "tests" / "test_widget.py").write_text(
+        test_body + "# target-only marker\n", encoding="utf-8",
+    )
+    _git(repo, "add", "-A")
+    _git(repo, "commit", "-m", "base")
+    target = subprocess.run(
+        ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
+        capture_output=True, text=True,
+    ).stdout.strip()
+    _git(repo, "checkout", "-b", "worker")
+    (repo / "tests" / "test_widget.py").write_text(test_body, encoding="utf-8")
+    if source_changed:
+        (repo / "app" / "widget.py").write_text("VALUE = 2\n", encoding="utf-8")
+    _git(repo, "add", "-A")
+    _git(repo, "commit", "-m", "worker")
+    return repo, target
+
+
+def test_mutation_gate_accepts_regression_test_that_breaks_on_target_sources(tmp_path):
+    from app import merge_test_gate as gate
+
+    repo, target = _mutation_repo(
+        tmp_path,
+        "from app.widget import VALUE\n\n"
+        "def test_widget():\n    assert VALUE == 2\n",
+    )
+    result = gate.evaluate_test_gate(str(repo), target_ref="main", target_sha=target)
+
+    assert result["status"] == gate.PASSED
+    assert result["mutation_gate"]["status"] == gate.PASSED
+    assert result["mutation_gate"]["reason"] == "guarded_source_change"
+    assert result["mutation_gate"]["changed_tests"] == ["tests/test_widget.py"]
+    assert Path(result["interpreter"]).is_absolute()
+
+
+def test_mutation_gate_rejects_test_that_stays_green_on_target_sources(tmp_path):
+    from app import merge_test_gate as gate
+
+    repo, target = _mutation_repo(
+        tmp_path,
+        "from app.widget import VALUE\n\n"
+        "def test_widget():\n    assert VALUE in {1, 2}\n",
+    )
+    result = gate.evaluate_test_gate(str(repo), target_ref="main", target_sha=target)
+
+    assert result["status"] == gate.FAILED
+    assert result["reason"] == "tests_not_guarding_source"
+    assert result["mutation_gate"]["status"] == gate.FAILED
+    assert "no regression is guarded" in result["mutation_gate"]["output"]
+
+
+def test_mutation_gate_skips_test_only_change(tmp_path):
+    from app import merge_test_gate as gate
+
+    repo, target = _mutation_repo(
+        tmp_path,
+        "from app.widget import VALUE\n\n"
+        "def test_widget():\n    assert VALUE == 1\n\n# worker-only test edit\n",
+        source_changed=False,
+    )
+    result = gate.evaluate_test_gate(str(repo), target_ref="main", target_sha=target)
+
+    assert result["status"] == gate.PASSED
+    assert result["mutation_gate"]["status"] == gate.SKIPPED
+    assert result["mutation_gate"]["reason"] == "no_changed_sources"
+
+
+def test_mutation_gate_timeout_is_visible_and_not_a_false_pass(tmp_path, monkeypatch):
+    from app import merge_test_gate as gate
+
+    repo, target = _mutation_repo(
+        tmp_path,
+        "from app.widget import VALUE\n\n"
+        "def test_widget():\n    assert VALUE == 2\n",
+    )
+    calls = []
+
+    def fake_run(worktree, tests, *, timeout=None, interpreter=None):
+        calls.append((worktree, list(tests), timeout, interpreter))
+        return {
+            "status": gate.PASSED if len(calls) == 1 else gate.INCONCLUSIVE,
+            "reason": "" if len(calls) == 1 else "timeout",
+            "exit_code": 0 if len(calls) == 1 else None,
+            "output": "first" if len(calls) == 1 else "timed out",
+            "tests": list(tests),
+        }
+
+    monkeypatch.setattr(gate, "run_pytest", fake_run)
+    result = gate.evaluate_test_gate(str(repo), target_ref="main", target_sha=target)
+
+    assert result["status"] == gate.PASSED
+    assert result["mutation_gate"]["status"] == gate.INCONCLUSIVE
+    assert result["mutation_gate"]["reason"] == "timeout"
+    assert calls[1][2] == gate.MUTATION_MAX_TIMEOUT_SECONDS
+    assert calls[0][3] is None and calls[1][3] == result["interpreter"]
+
+
+def test_mutation_file_classification_excludes_docs_config_and_prompts():
+    from app import merge_test_gate as gate
+
+    changed = [
+        "app/widget.py", "tests/test_widget.py", "docs/guide.md",
+        "prompts/worker.md", "pyproject.toml", "config/settings.yaml",
+    ]
+    assert gate.changed_test_paths(changed) == ["tests/test_widget.py"]
+    assert gate.changed_source_paths(changed) == ["app/widget.py"]
+
+
+def test_changed_test_nodes_selects_only_touched_class_methods(tmp_path):
+    from app import merge_test_gate as gate
+
+    repo = tmp_path / "node-repo"
+    repo.mkdir()
+    _git(repo, "init", "-b", "main")
+    _git(repo, "config", "user.email", "t@t")
+    _git(repo, "config", "user.name", "t")
+    (repo / "tests").mkdir()
+    (repo / "tests" / "test_nodes.py").write_text(
+        "class TestWidget:\n"
+        "    def test_left(self):\n        assert True\n\n"
+        "    def test_right(self):\n        assert True\n",
+        encoding="utf-8",
+    )
+    _git(repo, "add", "-A")
+    _git(repo, "commit", "-m", "base")
+    target = subprocess.run(
+        ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
+        capture_output=True, text=True,
+    ).stdout.strip()
+    _git(repo, "checkout", "-b", "worker")
+    (repo / "tests" / "test_nodes.py").write_text(
+        "class TestWidget:\n"
+        "    def test_left(self):\n        assert False\n\n"
+        "    def test_right(self):\n        assert True\n",
+        encoding="utf-8",
+    )
+    _git(repo, "add", "-A")
+    _git(repo, "commit", "-m", "touch one node")
+
+    selected, fallback = gate.changed_test_nodes(
+        str(repo), target, ["tests/test_nodes.py"],
+    )
+    assert selected == ["tests/test_nodes.py::TestWidget::test_left"]
+    assert fallback == []
+
+
+def test_run_pytest_isolates_live_state_environment(tmp_path, monkeypatch):
+    from app import merge_test_gate as gate
+
+    seen = {}
+
+    def fake_run(argv, **kwargs):
+        seen.update(kwargs["env"])
+        return subprocess.CompletedProcess(argv, 0, "passed", "")
+
+    monkeypatch.setenv("ORCHESTRA_DB_PATH", "/production/orchestra.db")
+    monkeypatch.setenv("ORCHESTRA_TASK_REPOSITORY", "/production/tasks")
+    monkeypatch.setenv("ORCHESTRA_TASK_PREFIX", "V-")
+    monkeypatch.setenv("QUOTA_GATED_LANES", "claude")
+    monkeypatch.setattr(gate.subprocess, "run", fake_run)
+
+    result = gate.run_pytest(str(tmp_path), ["tests/test_widget.py"])
+
+    assert result["status"] == gate.PASSED
+    assert seen["ORCHESTRA_DB_PATH"].startswith("/tmp/")
+    assert seen["ORCHESTRA_TASK_REPOSITORY"].startswith("/tmp/")
+    assert "ORCHESTRA_TASK_PREFIX" not in seen
+    assert "QUOTA_GATED_LANES" not in seen
+
+
 def test_large_mapped_subset_reaches_a_verdict_at_measured_file_costs(monkeypatch):
     """Набор из РЕАЛЬНО дорогих файлов обязан получить вердикт, а не таймаут.
 
     Стоимости взяты из замера #336, а не выдуманы: `tests/test_manager.py` — 219.5 с
     (283 с под нагрузкой), `tests/test_frontend.py` — 71–148 с по пяти прод-замерам.
     Каждый из них дороже всего прежнего фиксированного бюджета 180 с сам по себе, а батч
     не может быть меньше одного файла — поэтому при фиксированном бюджете такой набор
     не получал вердикта ни при какой раскладке (замер: #290 отбит семь раз подряд).
@@ -839,17 +1022,22 @@ def test_argv_verbosity_really_prints_per_test_lines(tmp_path):
     assert proc.returncode == 0, proc.stdout + proc.stderr
     assert "test_two.py::test_first PASSED" in proc.stdout
     assert "test_two.py::test_second PASSED" in proc.stdout
 
 
 @pytest.mark.asyncio
 @pytest.mark.parametrize("gate_db", [{
     "app/widget.py": "VALUE = 1\n",
-    "tests/test_widget.py": "def test_widget():\n    assert True\n",
+    "tests/test_widget.py": (
+        "from app.widget import VALUE\n"
+        "\n"
+        "def test_widget():\n"
+        "    assert VALUE == 1\n"
+    ),
 }], indirect=True)
 async def test_green_mapped_test_reaches_executor(gate_db, monkeypatch):
     result, calls = await _run_with_spy(monkeypatch, worktree=str(gate_db))
     assert len(calls) == 1
     assert result["operation_state"] == "SUCCEEDED"
     assert result["test_gate"]["status"] == "passed"
 
 


## LATER FIX ea58b7dbe0 (14.1 days later): V-702: #V-702: fix merge gate outcomes and recovery routes
lines of origin it changed/deleted: 5
(code only, capped 400 lines)

V-702: #V-702: fix merge gate outcomes and recovery routes

Squashed commits:
- #V-702: fix merge gate outcomes and recovery routes
- #V-702: scope taskless recovery mutation check
- #V-702: make taskless delivery test production-shaped
- #V-702: isolate diff budget recovery oracle
- #V-702: isolate merge gate regressions
- #V-702: isolate taskless merge lifecycle checks
- #V-702: record regression mutation outcomes
- #V-702: promote explicit taskless adhoc merges
- #V-702: assert promoted merge lands and closes task
- #V-702: record corrected T159 mutation result

Orchestra-Operation: 2d449b07-34d9-47ae-9032-2cf628169bd3


diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index afae4e895..d4ebe9e1b 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -2278,19 +2278,20 @@ def _merge_payload_result(payload: Any) -> dict[str, Any]:
 
 def _merge_tool_result(result: dict[str, Any]) -> CallToolResult:
     operation_id = str(result.get("operation_id") or "unknown")
     state = str(result.get("operation_state") or "UNKNOWN").upper()
     error = result.get("error")
     action = result.get("next_action") if isinstance(result.get("next_action"), dict) else {}
     action_message = _safe_response_text(str(action.get("message") or ""))
     if state in {"PENDING", "RUNNING"}:
+        structured = {**result, "is_terminal": False, "is_failure": False}
         completion = result.get("completion") or {}
         if completion.get("mode") == "background" and completion.get("job_id"):
-            return mcp_tool_result(result, text=(
+            return mcp_tool_result(structured, text=(
                 f"STILL {state} — NOT a failure. Merge operation {operation_id} continues "
                 f"on the server. Background job {completion['job_id']} will deliver its outcome. "
                 "Do not poll or call merge_worker again. Continue independent work or end "
                 "the turn; Orchestra will resume you when the outcome arrives. "
                 "Do not start a duplicate merge or merge manually."
             ))
         # a blocking reason (dirty tree, conflict) already sits in `error` — surfacing it
         # here saves the caller two blind retries before the cause finally shows up
@@ -2318,17 +2319,17 @@ def _merge_tool_result(result: dict[str, Any]) -> CallToolResult:
             f"refusal names the actual branch — check worker_wip there and start a new "
             f"operation without operation_id."
             + (f" Server note: {_safe_response_text(reason)}" if reason else "")
         )
         progress = result.get("progress") if isinstance(result.get("progress"), dict) else {}
         if progress.get("stage"):
             elapsed = float(progress.get("elapsed_seconds") or 0)
             text += f" Current stage: {progress['stage']}; elapsed {elapsed:.0f}s."
-        return mcp_tool_result(result, text=text)
+        return mcp_tool_result(structured, text=text)
     if state == "SUCCEEDED":
         git = result.get("git") if isinstance(result.get("git"), dict) else {}
         count = int(git.get("commits_merged") or 0)
         branch = git.get("worker_branch") or "?"
         # Про добавку оркестратор обязан узнать из ПЕРВЫХ строк, а не найти в полях потом.
         # Поля может не быть вовсе (старый сервер до рестарта) — тогда текст прежний.
         drift = ""
         if git.get("head_drift") == "BENIGN_ADVANCE":
@@ -2473,17 +2474,21 @@ async def merge_worker(
     next_task_id: str = "",
     operation_id: str = "",
     waive_diff_budget: bool = False,
     task_outcome: str = "",
     expected_head: str = "",
     acceptance_note: str = "",
     task_id: str = "",
 ) -> CallToolResult:
-    """Durably squash a worker branch; waits for outcome. A slow STILL RUNNING result supplies a background wake: end the turn or do independent work, do not poll. Follow receipt recovery instructions; FAILED/PARTIAL/UNKNOWN require investigation. operation_id resumes that operation; branch drift is refused and needs a new operation. Before new work inspect worker_wip and pass its exact expected_head plus acceptance_note (acceptance decision and reason for absent model review); no separate attestation required. Verify the landed target afterward. waive_diff_budget is orchestrator-only and recorded in the result. task_outcome selects complete/continue; next_task_id preserves lifecycle handoff. For an unbound adhoc session, task_id explicitly identifies its in_progress task."""
+    """Durably squash a worker branch; waits for outcome. A slow STILL RUNNING result supplies a background wake: end the turn or do independent work, do not poll. Follow receipt recovery instructions; FAILED/PARTIAL/UNKNOWN require investigation. operation_id resumes that operation; branch drift is refused and needs a new operation. Before new work inspect worker_wip and pass its exact expected_head plus acceptance_note (acceptance decision and reason for absent model review); no separate attestation required. Verify the landed target afterward. waive_diff_budget is orchestrator-only and recorded in the result. task_outcome selects complete/continue; next_task_id preserves lifecycle handoff. On a taskless adhoc branch, task_id promotes committed work to the named task before merging; omitting task_id refuses a strict task-lifecycle merge."""
+    task_id = task_id.strip()
+    task_outcome = task_outcome.strip().lower()
+    if task_id and not task_outcome:
+        task_outcome = "complete"
     if waive_diff_budget and ROLE not in _ORCH_ROLES:
         return mcp_tool_result(
             result={
                 "operation_state": "FAILED",
                 "error": {
                     "code": "DIFF_BUDGET_WAIVE_FORBIDDEN",
                     "message": "waive_diff_budget is orchestrator-only",
                 },
diff --git a/app/merge_operations.py b/app/merge_operations.py
index 2efd50da4..b0cfce64a 100644
--- a/app/merge_operations.py
+++ b/app/merge_operations.py
@@ -135,30 +135,33 @@ def _base_result(
 def normalize_request(
     *,
     name: str,
     scope: str,
     target: str = "",
     next_task_id: str = "",
     waive_diff_budget: bool = False,
     waived_by: str = "",
+    task_id: str = "",
     task_outcome: str = "",
     merge_schema_version: int | None = None,
     expected_head: str = "",
     acceptance_note: str = "",
 ) -> dict[str, Any]:
     request = {
         "name": name.strip(),
         "scope": scope.rstrip("/"),
         "target": target.strip(),
         "next_task_id": next_task_id.strip(),
         "squash": True,
         "waive_diff_budget": bool(waive_diff_budget),
         "waived_by": waived_by.strip() if waive_diff_budget else "",
     }
+    if task_id.strip():
+        request["task_id"] = task_id.strip()
     if merge_schema_version is not None:
         request["merge_schema_version"] = int(merge_schema_version)
         request["task_outcome"] = task_outcome.strip().lower()
     if expected_head:
         request["expected_head"] = expected_head.strip()
     if acceptance_note:
         request["acceptance_note"] = acceptance_note.strip()
     return request
@@ -1087,16 +1090,33 @@ def _classify_failure(raw: dict[str, Any], message: str) -> tuple[str, dict[str,
             return "NO_COMMITS_MERGED", details, _action(
                 "CLEAN_TARGET_THEN_NEW_OPERATION",
                 "Clean the target worktree, then start a new merge operation.",
             )
         return "NO_COMMITS_MERGED", details, _action(
             "CHECK_WORKER_THEN_NEW_OPERATION",
             "No commits reached the target branch; verify the worker branch before retrying.",
         )
+    if "diff too large" in lower:
+        return "DIFF_TOO_LARGE", details, _action(
+            "WAKE_PARENT",
+            "Use send_message to wake the parent orchestrator and ask it to review the "
+            "diff limit; only the orchestrator can retry with waive_diff_budget=True. "
+            "Keep the worker branch intact.",
+        )
+    next_action = raw.get("next_action")
+    if (
+        "session has no bound task" in lower
+        and isinstance(next_action, dict)
+        and next_action.get("message")
+    ):
+        return "SESSION_HAS_NO_BOUND_TASK", details, {
+            "code": str(next_action.get("code") or "ASSIGN_TASK"),
+            "message": _text(next_action.get("message"), "Assign a task before merging."),
+        }
     if "target working tree is dirty" in lower:
         details["paths_text"] = message
         return "TARGET_DIRTY", details, _action(
             "CLEAN_TARGET_THEN_NEW_OPERATION",
             "Clean the target worktree, then start a new merge operation.",
         )
     if "worker working tree is dirty" in lower:
         details["paths_text"] = message
@@ -2018,29 +2038,31 @@ def _head_matches(expected: str, actual: str) -> bool:
 
 async def accept_merge_operation(
     *,
     operation_id: str,
     name: str,
     scope: str,
     target: str = "",
     next_task_id: str = "",
+    task_id: str = "",
     waive_diff_budget: bool = False,
     waived_by: str = "",
     task_outcome: str = "",
     merge_schema_version: int | None = None,
     expected_head: str = "",
     acceptance_note: str = "",
     accepting_actor: str = "",
 ) -> tuple[dict[str, Any], int]:
     request = normalize_request(
         name=name,
         scope=scope,
         target=target,
         next_task_id=next_task_id,
+        task_id=task_id,
         waive_diff_budget=waive_diff_budget,
         waived_by=waived_by,
         task_outcome=task_outcome,
         merge_schema_version=merge_schema_version,
         expected_head=expected_head,
         acceptance_note=acceptance_note,
     )
     try:
diff --git a/app/merge_test_gate.py b/app/merge_test_gate.py
index b3d7f1f5c..7c99d9f80 100644
--- a/app/merge_test_gate.py
+++ b/app/merge_test_gate.py
@@ -433,27 +433,28 @@ def run_pytest(
             "status": SKIPPED, "reason": "no_tests_after_deselect",
             "exit_code": proc.returncode, "output": diagnostic, "tests": tests,
         }
     if re.search(r"No module named ['\"]?pytest['\"]?", output):
         return {
             "status": INCONCLUSIVE, "reason": "pytest_unavailable",
             "exit_code": proc.returncode, "output": diagnostic, "tests": tests,
         }
-    if (
-        proc.returncode == USAGE_ERROR_EXIT_CODE
-        and "unrecognized arguments" in output
-        and "--timeout" in output
-    ):
+    if proc.returncode == USAGE_ERROR_EXIT_CODE:
         # Интерпретатор без `pytest-timeout` отвергает НАШ флаг ещё до сбора: pytest выходит
         # с usage error, тесты не запускались вовсе. Общая ветка ниже объявила бы это
         # `exit_nonzero`, то есть «набор красный», и заблокировала мержи всех проектов на
         # отсутствующем плагине.
+        reason = (
+            "pytest_timeout_unavailable"
+            if "unrecognized arguments" in output and "--timeout" in output
+            else "pytest_usage_error"
+        )
         return {
-            "status": INCONCLUSIVE, "reason": "pytest_timeout_unavailable",
+            "status": INCONCLUSIVE, "reason": reason,
             "exit_code": proc.returncode, "output": diagnostic, "tests": tests,
         }
     return {
         "status": FAILED, "reason": "exit_nonzero",
         "exit_code": proc.returncode, "output": diagnostic, "tests": tests,
     }
 
 
@@ -566,28 +567,33 @@ _NON_SOURCE_PREFIXES = (
 _NON_SOURCE_SUFFIXES = {
     ".md", ".rst", ".txt", ".toml", ".ini", ".cfg", ".yaml", ".yml", ".json",
 }
 
 
 def changed_test_paths(changed: list[str]) -> list[str]:
     """Return test modules supplied by the worker, not merely source-mapped tests."""
     return sorted({
-        path.replace("\\", "/").lstrip("./")
+        _normalize_repo_path(path)
         for path in changed
-        if path.replace("\\", "/").lstrip("./").startswith(_TEST_PATH_PREFIX)
-        and path.replace("\\", "/").lstrip("./").endswith(".py")
+        if _normalize_repo_path(path).startswith(_TEST_PATH_PREFIX)
+        and _normalize_repo_path(path).endswith(".py")
     })
 
 
+def _normalize_repo_path(path: str) -> str:
+    normalized = path.replace("\\", "/")
+    return normalized[2:] if normalized.startswith("./") else normalized
+
+
 def changed_source_paths(changed: list[str]) -> list[str]:
     """Classify executable changes while leaving docs, config and prompts out."""
     sources: set[str] = set()
     for raw in changed:
-        path = raw.replace("\\", "/").lstrip("./")
+        path = _normalize_repo_path(raw)
         if not path or path.startswith(_TEST_PATH_PREFIX) or path.startswith(_NON_SOURCE_PREFIXES):
             continue
         suffix = Path(path).suffix.lower()
         if suffix in _NON_SOURCE_SUFFIXES:
             continue
         if path.startswith(_SOURCE_PREFIXES) or suffix in {".py", ".js", ".ts", ".tsx", ".jsx", ".css", ".html"}:
             sources.add(path)
     return sorted(sources)
@@ -741,17 +747,20 @@ def evaluate_mutation_gate(
     worktree: str,
     changed: list[str],
     *,
     target_ref: str = "",
     target_sha: str = "",
     interpreter: str | None = None,
 ) -> dict:
     """Run worker tests against target sources in an isolated disposable tree."""
-    tests = changed_test_paths(changed)
+    tests = [
+        path for path in changed_test_paths(changed)
+        if (Path(worktree) / path).is_file()
+    ]
     sources = changed_source_paths(changed)
     result = {
         "status": SKIPPED,
         "reason": "no_changed_tests" if not tests else "no_changed_sources",
         "exit_code": None,
         "output": "",
         "tests": tests,
         "changed_tests": tests,
diff --git a/app/routes/merge_operations.py b/app/routes/merge_operations.py
index 9b49ddb09..e5aedaacd 100644
--- a/app/routes/merge_operations.py
+++ b/app/routes/merge_operations.py
@@ -63,25 +63,94 @@ async def create_merge_operation(req: dict, request: Request = None):
                 },
             },
             403,
         )
     from app.mcp_proof import work_acceptor_principal
     from app.db import get_session_by_name
     target_session = get_session_by_name(str(req.get("name") or ""), str(req.get("scope") or "").rstrip("/")) if request is not None else None
     accepting_actor = work_acceptor_principal(request, target_session or {}, str(req.get("target") or (target_session or {}).get("base_branch") or "main")) if request is not None else ""
+    explicit_task_id = str(req.get("task_id") or "").strip()
+    if (
+        explicit_task_id
+        and target_session
+        and not str(target_session.get("task_id") or "").strip()
+        and str(target_session.get("branch") or "").startswith("adhoc-")
+    ):
+        if req.get("merge_schema_version") != 2 or str(req.get("task_outcome") or "") != "complete":
+            return _response(
+                {
+                    "operation_state": "FAILED",
+                    "error": {
+                        "code": "TASK_LIFECYCLE_V2_REQUIRED",
+                        "message": "Promoting adhoc work requires merge_schema_version=2 and task_outcome='complete'.",
+                    },
+                },
+                400,
+            )
+        if not accepting_actor or not str(req.get("expected_head") or "").strip() or not str(req.get("acceptance_note") or "").strip():
+            return _response(
+                {
+                    "operation_state": "FAILED",
+                    "error": {
+                        "code": "WORK_ACCEPTANCE_REQUIRED",
+                        "message": "Before promoting adhoc work, inspect worker_wip and provide its exact expected_head and an acceptance_note.",
+                    },
+                },
+                409,
+            )
+        from app.routes.sessions import switch_branch
+
+        promotion = await switch_branch(
+            str(req.get("name") or ""),
+            {
+                "scope": str(req.get("scope") or ""),
+                "task_id": explicit_task_id,
+                "promote_current": True,
+            },
+        )
+        if not isinstance(promotion, dict) or not promotion.get("ok"):
+            refreshed = get_session_by_name(
+                str(req.get("name") or ""), str(req.get("scope") or "").rstrip("/"),
+            )
+            if str((refreshed or {}).get("task_id") or "").strip() == explicit_task_id:
+                target_session = refreshed
+            else:
+                detail = (
+                    str(promotion.get("error") or "adhoc work promotion failed")
+                    if isinstance(promotion, dict)
+                    else promotion.body.decode("utf-8", "replace")
+                    if isinstance(promotion, JSONResponse)
+                    else "adhoc work promotion returned no result"
+                )
+                return _response(
+                    {
+                        "operation_state": "FAILED",
+                        "error": {"code": "ADHOC_PROMOTION_FAILED", "message": detail},
+                        "next_action": {
+                            "code": "INSPECT_ADHOC_WORK",
+                            "message": "Inspect the worker branch and resolve the promotion refusal before retrying the merge.",
+                        },
+                    },
+                    promotion.status_code if isinstance(promotion, JSONResponse) else 409,
+                )
+        else:
+            target_session = get_session_by_name(
+                str(req.get("name") or ""), str(req.get("scope") or "").rstrip("/"),
+            )
     result, status_code = await accept_merge_operation(
         operation_id=str(req.get("operation_id") or ""),
         expected_head=str(req.get("expected_head") or ""),
         acceptance_note=str(req.get("acceptance_note") or ""),
         accepting_actor=accepting_actor,
         name=str(req.get("name") or ""),
         scope=str(req.get("scope") or ""),
         target=str(req.get("target") or ""),
         next_task_id=str(req.get("next_task_id") or ""),
+        task_id=explicit_task_id,
         waive_diff_budget=waive,
         waived_by=str(req.get("waived_by") or ""),
         task_outcome=str(req.get("task_outcome") or ""),
         merge_schema_version=(
             int(req["merge_schema_version"])
             if req.get("merge_schema_version") is not None else None
         ),
     )
diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index b147cec04..9afc2c5e5 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -1971,30 +1971,34 @@ async def delete_session(name: str, scope: str, force: bool = False):
 
 def _merge_not_reached(
     error: str,
     *,
     target_branch: str = "",
     worker_branch: str = "",
     worker_head: str = "",
     http_status: int = 400,