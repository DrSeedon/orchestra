"""#255 — мерж без acceptance_command всё равно не сажает красный тест в main.

Оракул: «execute_merge_session вызван» — не цель. Цель — красное не доехало.
Полный сьют (728s + глобальный test_lock) здесь не гоняем.
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.test_acceptance import _run_with_spy, _session_row, worker_head


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _repo(tmp_path: Path, *, files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "README").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README")
    _git(repo, "commit", "-m", "base")
    _git(repo, "checkout", "-b", "task-42/worker")
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "change")
    return repo


def _record_reviewed_receipt(dbmod, worktree: Path) -> None:
    """Квитанция ревью на текущий продовый снимок — предусловие, а не предмет этих тестов.

    Предмет здесь тест-гейт (#255). С приходом review-coverage (#462) мерж, меняющий
    `app/**`, требует ещё и квитанции; без неё эти тесты меряли бы чужой гейт и краснели бы
    на нём, так и не дойдя до своего. Покрытие ревью проверяется отдельно —
    `tests/test_review_coverage_gate_462.py` и `tests/test_review_coverage_target_drift_474.py`.
    """
    from app.review_coverage import production_paths, production_snapshot

    head = worker_head(str(worktree))
    target_sha = subprocess.run(
        ["git", "rev-parse", "main"],
        cwd=worktree, capture_output=True, text=True, check=True,
    ).stdout.strip()
    snapshot = production_snapshot(
        str(worktree), target_sha=target_sha, worker_head=head,
    )
    if not production_paths(list(snapshot["production_paths"])):
        return
    now = datetime.now(timezone.utc).isoformat()
    dbmod.review_receipt_create({
        "receipt_id": f"review-receipt:{uuid.uuid4()}",
        "schema_version": 1,
        "runtime": "codex",
        "reviewer_model": "gpt-5.6-luna",
        "model_source": "direct",
        "session_id": "merge-session",
        "worker_name": "worker",
        "scope": "/scope",
        "task_id": "42",
        "task_source": "session_lookup",
        "artifact_path": f"/tmp/gate-review-{uuid.uuid4()}.md",
        "mode": "implementation",
        "round": 1,
        "job_id": "bg-255",
        "usage_event_id": "usage-255",
        "requested_at": now,
        "completed_at": now,
        "status": "completed",
        "return_code": 0,
        "failure_code": "",
        "artifact_exists": 1,
        "artifact_bytes": 10,
        "artifact_sha256": "a" * 64,
        "verdict_present": 1,
        "verdict_value": "ACK",
        "jsonl_response_present": 1,
        "recovery_source": "",
        "author_outcome": "accepted",
        "outcome_source": "direct",
        "outcome_evidence_ref": ".orchestra/tasks/474/report.md#gate-fixture",
        "notification_event_id": "",
        "subject_kind": "implementation",
        "coverage_outcome": "reviewed",
        "policy_ref": "",
        "decision_actor": "",
        **snapshot,
    })


@pytest.fixture
def gate_db(tmp_path, monkeypatch, request):
    import app.db as dbmod
    import app.merge_operations as operations
    import app.tm as tm

    files = getattr(request, "param", {
        "app/widget.py": "VALUE = 1\n",
        "tests/test_widget.py": (
            "def test_widget():\n"
            "    raise AssertionError('ACC255-RED')\n"
        ),
    })
    worktree = _repo(tmp_path, files=files)
    db_path = tmp_path / "gate.db"
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    dbmod.init_db()
    operations._runner_tasks.clear()
    dbmod.save_session(_session_row(str(worktree)))
    with tm._conn() as conn:
        tm.ensure_project(conn, "proj", scope="/scope")
        tm.create_task(conn, "proj", "ticket", par_number=42, acceptance_command="")
    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda _path: ("task-42/worker", worker_head(str(worktree))),
    )
    _record_reviewed_receipt(dbmod, worktree)
    return worktree


@pytest.mark.asyncio
async def test_red_mapped_test_does_not_reach_merge_executor(gate_db, monkeypatch):
    """Сегодня мерж с красным тестом проходит — платформа подмножество не гоняет."""
    result, calls = await _run_with_spy(monkeypatch, worktree=str(gate_db))
    assert calls == [], (
        "execute_merge_session вызван при красном mapped-тесте — красное село бы в main"
    )
    assert result["operation_state"] == "FAILED"
    assert result["commit_point"] == "NOT_REACHED"
    assert result["error"]["code"] == "TEST_GATE_FAILED"
    output = (result.get("test_gate") or {}).get("output") or ""
    assert "ACC255-RED" in output


def test_ci_pytest_does_not_stop_at_first_failure():
    """Финальный прогон CI без -x: один красный не прячет хвост."""
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    pytest_lines = [
        line for line in text.splitlines()
        if re.search(r"\bpytest\b", line)
    ]
    assert pytest_lines, "в CI нет вызова pytest"
    for line in pytest_lines:
        assert not re.search(r"(^|\s)-x(\s|$)", line), line
        assert "--exitfirst" not in line
        assert "--maxfail=1" not in line


def test_select_tests_maps_stem_and_routes(tmp_path):
    from app.merge_test_gate import select_tests

    (tmp_path / "app" / "routes").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "widget.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_widget.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    (tmp_path / "app" / "routes" / "tm.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_routes_surface.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    (tmp_path / "docs" / "a.md").parent.mkdir(exist_ok=True)
    (tmp_path / "docs" / "a.md").write_text("n\n", encoding="utf-8")

    mapped = select_tests(
        ["app/widget.py", "app/routes/tm.py"], worktree=str(tmp_path),
    )
    assert mapped == ["tests/test_routes_surface.py", "tests/test_widget.py"]
    assert select_tests(["docs/a.md"], worktree=str(tmp_path)) == []


def test_large_mapped_subset_reaches_a_verdict_at_measured_file_costs(monkeypatch):
    """Набор из РЕАЛЬНО дорогих файлов обязан получить вердикт, а не таймаут.

    Стоимости взяты из замера #336, а не выдуманы: `tests/test_manager.py` — 219.5 с
    (283 с под нагрузкой), `tests/test_frontend.py` — 71–148 с по пяти прод-замерам.
    Каждый из них дороже всего прежнего фиксированного бюджета 180 с сам по себе, а батч
    не может быть меньше одного файла — поэтому при фиксированном бюджете такой набор
    не получал вердикта ни при какой раскладке (замер: #290 отбит семь раз подряд).

    Проверяется ПОВЕДЕНИЕ, а не литерал: батч ограничен, каждый файл прогнан, бюджет
    растёт с размером набора, вердикт выдан. Тест переживает смену любой из трёх констант
    и краснеет на возврате к бюджету, не зависящему от размера набора.
    """
    from app import merge_test_gate as gate

    costs = {"tests/test_manager.py": 283.0, "tests/test_frontend.py": 148.0}
    tests = ["tests/test_manager.py", "tests/test_frontend.py"] + [
        f"tests/test_{n:02d}.py" for n in range(12)
    ]
    tests.sort()
    calls = []
    clock = [0.0]

    monkeypatch.setattr(gate, "changed_paths", lambda _worktree: ["app/widget.py"])
    monkeypatch.setattr(gate, "select_tests", lambda _changed, worktree: tests)
    monkeypatch.setattr(gate.time, "monotonic", lambda: clock[0])

    def fake_run(worktree, batch, *, timeout=None):
        calls.append((list(batch), timeout))
        cost = sum(costs.get(test, 10.0) for test in batch)
        clock[0] += min(cost, timeout)
        status = gate.PASSED if cost <= timeout else gate.INCONCLUSIVE
        return {
            "status": status,
            "reason": "" if status == gate.PASSED else "timeout",
            "exit_code": 0 if status == gate.PASSED else None,
            "output": "ran " + ", ".join(batch),
            "tests": list(batch),
        }

    monkeypatch.setattr(gate, "run_pytest", fake_run)
    result = gate.evaluate_test_gate("/worktree")

    assert result["status"] == gate.PASSED, "набор зелёный — гейт обязан это установить"
    assert [test for batch, _timeout in calls for test in batch] == tests
    batch_sizes = [len(batch) for batch, _timeout in calls]
    assert min(batch_sizes) >= 1 and max(batch_sizes) < gate.MAX_TEST_FILES
    # Бюджет обязан зависеть от размера набора: иначе тяжёлый файл не помещается никогда.
    assert gate.budget_for(len(tests)) > gate.budget_for(1) > gate.budget_for(0)
    assert gate.budget_for(1) >= max(costs.values()), (
        "бюджет обязан вмещать самый дорогой ОДИНОЧНЫЙ файл — батч меньше файла невозможен"
    )
    # Самый дорогой файл не помещается ни в один батч при прежнем фиксированном бюджете.
    assert costs["tests/test_manager.py"] > 180.0 / len(calls)


def test_each_batch_is_attempted_when_non_final_batch_fails(monkeypatch):
    from app import merge_test_gate as gate

    tests = [f"tests/test_{n:02d}.py" for n in range(13)]
    calls = []

    monkeypatch.setattr(gate, "changed_paths", lambda _worktree: ["app/widget.py"])
    monkeypatch.setattr(gate, "select_tests", lambda _changed, worktree: tests)
    monkeypatch.setattr(gate.time, "monotonic", lambda: 0.0)
    outcomes = iter((gate.FAILED, gate.INCONCLUSIVE, gate.PASSED))

    def fake_run(worktree, batch, *, timeout=None):
        calls.append((list(batch), timeout, len(batch)))
        status = next(outcomes)
        return {
            "status": status,
            "reason": "exit_nonzero" if status == gate.FAILED else "timeout",
            "exit_code": 1 if status == gate.FAILED else None,
            "output": "diag-" + (" ".join(batch)),
            "tests": list(batch),
        }

    monkeypatch.setattr(gate, "run_pytest", fake_run)
    result = gate.evaluate_test_gate("/worktree")

    assert len(calls) == 3
    assert [size for _batch, _timeout, size in calls] == [5, 4, 4]
    assert max(size for _batch, _timeout, size in calls) < gate.MAX_TEST_FILES
    assert result["status"] == gate.FAILED
    assert result["reason"] == "batch_failed"


def test_small_mapped_subset_stays_one_batch(monkeypatch):
    from app import merge_test_gate as gate

    tests = [f"tests/test_{n:02d}.py" for n in range(12)]
    calls = []

    monkeypatch.setattr(gate, "changed_paths", lambda _worktree: ["app/widget.py"])
    monkeypatch.setattr(gate, "select_tests", lambda _changed, worktree: tests)

    def fake_run(worktree, batch, *, timeout=None):
        calls.append((list(batch), timeout))
        return {
            "status": gate.PASSED,
            "reason": "",
            "exit_code": 0,
            "output": "passed",
            "tests": list(batch),
        }

    monkeypatch.setattr(gate, "run_pytest", fake_run)
    result = gate.evaluate_test_gate("/worktree")

    assert result["status"] == gate.PASSED
    assert calls == [(tests, None)]


def test_large_subset_preserves_failed_and_inconclusive_batches(monkeypatch):
    from app import merge_test_gate as gate

    tests = [f"tests/test_{n:02d}.py" for n in range(13)]
    outcomes = iter((gate.FAILED, gate.INCONCLUSIVE, gate.PASSED))

    monkeypatch.setattr(gate, "changed_paths", lambda _worktree: ["app/widget.py"])
    monkeypatch.setattr(gate, "select_tests", lambda _changed, worktree: tests)

    def fake_run(worktree, batch, *, timeout=None):
        status = next(outcomes)
        return {
            "status": status,
            "reason": "exit_nonzero" if status == gate.FAILED else "timeout",
            "exit_code": 1 if status == gate.FAILED else None,
            "output": "diagnostic-" + batch[0],
            "tests": list(batch),
        }

    monkeypatch.setattr(gate, "run_pytest", fake_run)
    result = gate.evaluate_test_gate("/worktree")

    assert result["status"] == gate.FAILED
    assert result["reason"] == "batch_failed"
    assert sorted(result["tests"]) == tests
    assert all(test in result["output"] for test in (tests[0], tests[-1]))
    assert "diagnostic-tests/test_00.py" in result["output"]


def test_large_subset_keeps_diagnostics_from_verbose_batches(monkeypatch):
    from app import merge_test_gate as gate

    tests = [f"tests/test_{n:02d}.py" for n in range(13)]
    outcomes = iter((gate.FAILED, gate.INCONCLUSIVE, gate.PASSED))
    diagnostics = iter(("early-failure", "late-timeout", "late-pass"))

    monkeypatch.setattr(gate, "changed_paths", lambda _worktree: ["app/widget.py"])
    monkeypatch.setattr(gate, "select_tests", lambda _changed, worktree: tests)

    def fake_run(worktree, batch, *, timeout=None):
        status = next(outcomes)
        return {
            "status": status,
            "reason": "exit_nonzero" if status == gate.FAILED else "timeout",
            "exit_code": 1 if status == gate.FAILED else None,
            "output": next(diagnostics) + "-" + ("x" * 5000),
            "tests": list(batch),
        }

    monkeypatch.setattr(gate, "run_pytest", fake_run)
    result = gate.evaluate_test_gate("/worktree")

    assert "early-failure" in result["output"]
    assert "late-timeout" in result["output"]
    assert len(result["output"]) <= 4000


def test_pytest_argv_has_no_exitfirst():
    from app.merge_test_gate import pytest_argv

    argv = pytest_argv(["tests/test_widget.py"])
    assert "-x" not in argv
    assert "--exitfirst" not in argv
    assert "--maxfail=1" not in argv
    # Раньше здесь стояло `argv.count("-m") == 1` — оно пиновало форму запуска
    # `python -m pytest`. Теперь `-m` два: второй несёт выражение маркеров, поэтому
    # проверяем обе роли поимённо, а не считаем вхождения.
    assert argv[:4] == [sys.executable, "-m", "pytest", "-q"]
    assert "pytest" in argv


def test_pytest_argv_deselects_live_probes_after_the_module_flag():
    """Гейт не тратит ход провайдера: живые пробы снимаются выражением маркеров."""
    from app.merge_test_gate import LIVE_PROBE_MARKER, pytest_argv

    argv = pytest_argv(["tests/test_widget.py"])

    assert f"not {LIVE_PROBE_MARKER}" in argv
    marker_flag = argv.index(f"not {LIVE_PROBE_MARKER}") - 1
    assert argv[marker_flag] == "-m"
    # Второй `-m` обязан идти ПОСЛЕ `python -m pytest`, иначе он подменит имя модуля.
    assert marker_flag > argv.index("pytest")
    assert argv[-1] == "tests/test_widget.py"


def test_run_pytest_reports_all_deselected_as_skipped_not_failed(tmp_path, monkeypatch):
    """Файл целиком из живых проб не должен читаться как красный.

    После `-m "not live_probe"` pytest отвечает кодом 5 (ничего не собрано). Прежняя
    ветка `exit_nonzero` объявила бы это провалом и заблокировала мерж на пустом прогоне.
    """
    from app import merge_test_gate as gate
    from app.acceptance import SKIPPED

    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["pytest"],
            returncode=gate.NO_TESTS_EXIT_CODE,
            stdout="no tests ran, 2 deselected",
            stderr="",
        ),
    )

    result = gate.run_pytest(str(tmp_path), ["tests/test_only_probes.py"])

    assert result["status"] == SKIPPED
    assert result["reason"] == "no_tests_after_deselect"
    assert result["exit_code"] == gate.NO_TESTS_EXIT_CODE


def _fake_python(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_run_pytest_prefers_worktree_venv_and_prints_interpreter(tmp_path, monkeypatch):
    from app import merge_test_gate as gate

    worktree = tmp_path / "worktree"
    interpreter = _fake_python(worktree / ".venv" / "bin" / "python")
    calls = []

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "two passed", "")

    monkeypatch.setattr(gate.subprocess, "run", fake_run)

    result = gate.run_pytest(str(worktree), ["tests/test_widget.py"])

    assert calls[0][0] == str(interpreter)
    assert f"interpreter={interpreter}" in result["output"]


def test_run_pytest_uses_repo_root_venv_before_orchestra_python(tmp_path, monkeypatch):
    from app import merge_test_gate as gate

    worktree = tmp_path / "worktree"
    repo_root = tmp_path / "repo"
    (worktree / ".git").mkdir(parents=True)
    interpreter = _fake_python(repo_root / ".venv" / "bin" / "python")
    monkeypatch.setattr(
        gate,
        "_git",
        lambda _cwd, *args: str(repo_root / ".git") + "\n"
        if args == ("rev-parse", "--path-format=absolute", "--git-common-dir")
        else None,
    )
    calls = []

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "two passed", "")

    monkeypatch.setattr(gate.subprocess, "run", fake_run)

    result = gate.run_pytest(str(worktree), ["tests/test_widget.py"])

    assert calls[0][0] == str(interpreter)
    assert f"interpreter={interpreter}" in result["output"]


def test_linked_worktree_uses_main_checkout_venv(tmp_path):
    from app import merge_test_gate as gate

    main = tmp_path / "project"
    main.mkdir()
    _git(main, "init", "-b", "main")
    _git(main, "config", "user.email", "t@t")
    _git(main, "config", "user.name", "t")
    (main / "README").write_text("base\n", encoding="utf-8")
    _git(main, "add", "README")
    _git(main, "commit", "-m", "base")
    interpreter = _fake_python(main / ".venv" / "bin" / "python")
    interpreter.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    interpreter.chmod(0o755)
    linked = tmp_path / "linked"
    subprocess.run(
        ["git", "worktree", "add", str(linked), "-b", "worker"],
        cwd=main, check=True, capture_output=True, text=True,
    )

    result = gate.run_pytest(str(linked), ["tests/test_widget.py"])

    assert result["status"] == gate.PASSED
    assert result["output"].startswith(f"interpreter={interpreter}\n")


def test_linked_worktree_symlinked_python_retains_venv_packages(tmp_path):
    from app import merge_test_gate as gate

    main = tmp_path / "project"
    main.mkdir()
    _git(main, "init", "-b", "main")
    _git(main, "config", "user.email", "t@t")
    _git(main, "config", "user.name", "t")
    (main / "README").write_text("base\n", encoding="utf-8")
    _git(main, "add", "README")
    _git(main, "commit", "-m", "base")
    venv = main / ".venv"
    (venv / "bin").mkdir(parents=True)
    base_python = Path(sys._base_executable).resolve()
    (venv / "pyvenv.cfg").write_text(
        f"home = {base_python.parent}\n"
        "include-system-site-packages = false\n"
        f"version = {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}\n",
        encoding="utf-8",
    )
    interpreter = venv / "bin" / "python"
    interpreter.symlink_to(base_python)
    import pytest as pytest_module
    site_packages = Path(pytest_module.__file__).resolve().parent.parent
    python_version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    (venv / "lib" / python_version).mkdir(parents=True)
    (venv / "lib" / python_version / "site-packages").symlink_to(
        site_packages, target_is_directory=True,
    )
    linked = tmp_path / "linked"
    subprocess.run(
        ["git", "worktree", "add", str(linked), "-b", "worker"],
        cwd=main, check=True, capture_output=True, text=True,
    )
    (linked / "tests").mkdir()
    (linked / "tests" / "test_placeholder.py").write_text(
        "def test_placeholder():\n    assert True\n", encoding="utf-8",
    )

    result = gate.run_pytest(str(linked), ["tests/test_placeholder.py"])

    assert result["status"] == gate.PASSED
    assert f"interpreter={interpreter}" in result["output"]


def test_run_pytest_reports_project_pytest_missing_without_fallback(tmp_path, monkeypatch):
    from app import merge_test_gate as gate
    from app.acceptance import INCONCLUSIVE

    worktree = tmp_path / "worktree"
    interpreter = _fake_python(worktree / ".venv" / "bin" / "python")
    calls = []

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv, 1, "", "/bin/python: No module named pytest",
        )

    monkeypatch.setattr(gate.subprocess, "run", fake_run)

    result = gate.run_pytest(str(worktree), ["tests/test_widget.py"])

    assert result["status"] == INCONCLUSIVE
    assert result["reason"] == "pytest_unavailable"
    assert result["exit_code"] == 1
    # Предмет теста — ИНТЕРПРЕТАТОР, а не набор флагов: за флаги отвечают `test_pytest_argv_*`,
    # и дословный список здесь был вторым их владельцем — #474 добавил потолок узла, и копия
    # покраснела на форме, а не на поведении.
    assert len(calls) == 1
    assert calls[0][0] == str(interpreter)
    assert str(sys.executable) not in calls[0]
    assert calls[0][-1] == "tests/test_widget.py"
    assert f"interpreter={interpreter}" in result["output"]
    assert str(sys.executable) not in result["output"]


def test_run_pytest_keeps_interpreter_marker_in_trimmed_refusal(tmp_path, monkeypatch):
    from app import merge_test_gate as gate

    interpreter = _fake_python(tmp_path / "worktree" / ".venv" / "bin" / "python")
    output = "pytest refusal " + ("x" * 5000)
    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(argv, 1, output, ""),
    )

    result = gate.run_pytest(str(tmp_path / "worktree"), ["tests/test_widget.py"])

    marker = f"interpreter={interpreter}"
    assert result["status"] == gate.FAILED
    assert marker in result["output"]
    assert result["output"].endswith(marker)


def test_run_pytest_uses_orchestra_python_when_project_venv_is_absent(tmp_path, monkeypatch):
    from app import merge_test_gate as gate

    calls = []

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "two passed", "")

    monkeypatch.setattr(gate.subprocess, "run", fake_run)

    result = gate.run_pytest(str(tmp_path), ["tests/test_widget.py"])

    assert calls[0][0] == sys.executable
    assert f"interpreter={sys.executable}" in result["output"]


def test_live_probe_inventory_is_explicit():
    """Живая проба не может исчезнуть из гейта незаметно.

    Маркер снимает тест с merge-gate, то есть выводит его из-под общей проверки. Такой
    ход обязан быть заявленным: список ниже — единственное место, где он заявляется.
    Появился маркер где-то ещё (или пропал отсюда) — тест краснеет и заставляет
    объяснить, почему проба тратит настоящий ход провайдера.
    """
    from app.merge_test_gate import LIVE_PROBE_MARKER

    expected = {
        "tests/test_native_history_import.py": 2,
        "tests/test_runtime_history.py": 1,
    }

    # Считаем ДЕКОРАТОРЫ, а не вхождения строки: первая версия этой проверки насчитала 3
    # вместо 2, потому что имя маркера упомянуто в докстринге файла. Проза не должна ни
    # раздувать инвентарь, ни прятать в себе настоящий маркер.
    decorator = f"@pytest.mark.{LIVE_PROBE_MARKER}"
    root = Path(__file__).resolve().parent
    found = {}
    for path in sorted(root.rglob("*.py")):
        count = sum(
            1
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith(decorator)
        )
        if count:
            found[str(path.relative_to(root.parent))] = count

    assert found == expected, (
        "инвентарь живых проб разошёлся с заявленным; добавляешь пробу — впиши её сюда "
        f"и в докстринг её файла. Найдено: {found}"
    )


@pytest.mark.parametrize(
    "stdout,stderr,expected",
    [
        (b"bytes", "str", "bytesstr"),
        ("str", b"bytes", "strbytes"),
        (None, None, ""),
        (b"\xff", None, "�"),
    ],
)
def test_run_pytest_timeout_normalizes_output_types(tmp_path, monkeypatch, stdout, stderr, expected):
    from app import merge_test_gate as gate
    from app.acceptance import INCONCLUSIVE

    tests = ["tests/test_widget.py"]
    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(
                cmd=["pytest"],
                timeout=1,
                output=stdout,
                stderr=stderr,
            )
        ),
    )
    result = gate.run_pytest(str(tmp_path), tests, timeout=1)
    assert result["status"] == INCONCLUSIVE
    assert result["reason"] == "timeout"
    marker = f"interpreter={sys.executable}"
    assert result["output"].startswith(marker + "\n")
    assert expected in result["output"]
    assert result["output"].endswith(marker)
    assert result["tests"] == tests


def test_run_pytest_timeout_replaces_invalid_utf8(tmp_path, monkeypatch):
    from app import merge_test_gate as gate

    tests = ["tests/test_widget.py"]
    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(
                cmd=["pytest"],
                timeout=1,
                output=b"bad\xffbytes",
                stderr=None,
            )
        ),
    )
    result = gate.run_pytest(str(tmp_path), tests, timeout=1)
    assert result["status"] == "inconclusive"
    assert result["reason"] == "timeout"
    assert "bad�bytes" in result["output"]
    assert result["output"].startswith(f"interpreter={sys.executable}\n")
    assert result["output"].endswith(f"interpreter={sys.executable}")


def test_run_pytest_timeout_truncates_to_last_4000_chars(tmp_path, monkeypatch):
    from app import merge_test_gate as gate

    tests = ["tests/test_widget.py"]
    payload = "x" * 4500
    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(
                cmd=["pytest"],
                timeout=1,
                output=payload,
                stderr=None,
            )
        ),
    )
    result = gate.run_pytest(str(tmp_path), tests, timeout=1)
    assert result["reason"] == "timeout"
    assert len(result["output"]) == 4000
    marker = f"interpreter={sys.executable}\n"
    assert result["output"].startswith(marker)
    assert result["output"].endswith(marker.rstrip("\n"))
    assert payload[-100:] in result["output"]


# Дословно снято с убитого прогона (#336): `-q -vv`, kill на 10 с. Формат фикстуры не
# сочинён — иначе разбор проверялся бы против выдумки, а не против того, что печатает pytest.
_KILLED_WITH_RED = (
    "test_probe.py::test_a_ok PASSED                                          [ 25%]\n"
    "test_probe.py::test_b_red FAILED                                         [ 50%]\n"
    "test_probe.py::test_c_slow "
)


def _timeout_raiser(payload: str):
    def _raise(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(
            cmd=["pytest"], timeout=1, output=payload, stderr=None,
        )
    return _raise


def test_timeout_that_saw_a_red_test_is_failed_not_inconclusive(tmp_path, monkeypatch):
    """Убитый прогон, успевший показать красное, — это FAILED, а не «не успели».

    Замер #336 на живой операции #248: в убитом выходе стояло девять `F`, гейт доложил
    `inconclusive`, то есть «повтори» — а повторять было нечего, тесты были красные.
    Красный тест красен независимо от того, доехал ли остаток набора.
    """
    from app import merge_test_gate as gate
    from app.acceptance import FAILED

    monkeypatch.setattr(gate.subprocess, "run", _timeout_raiser(_KILLED_WITH_RED))

    result = gate.run_pytest(str(tmp_path), ["test_probe.py"], timeout=1)

    assert result["status"] == FAILED
    assert result["reason"] == "timeout_with_failures"
    assert result["failed_tests"] == ["test_probe.py::test_b_red"]
    assert "test_probe.py::test_b_red" in gate.describe_progress(result)


def test_timeout_without_red_says_what_was_verified_and_what_was_not(tmp_path, monkeypatch):
    """Случай #329: набор зелёный, просто не доехал — отказ обязан это сказать.

    Раньше и он, и красный приходили как FAILED с советом «почини падающие тесты»,
    которых нет; из-за этого #329 смержили руками.
    """
    from app import merge_test_gate as gate
    from app.acceptance import INCONCLUSIVE

    payload = (
        "tests/test_a.py::test_one PASSED   [ 33%]\n"
        "tests/test_a.py::test_two PASSED   [ 66%]\n"
        "tests/test_a.py::test_slow "
    )
    monkeypatch.setattr(gate.subprocess, "run", _timeout_raiser(payload))

    result = gate.run_pytest(
        str(tmp_path), ["tests/test_a.py", "tests/test_never.py"], timeout=1,
    )

    assert result["status"] == INCONCLUSIVE
    assert result["reason"] == "timeout"
    assert result["failed_tests"] == []
    assert result["passed_count"] == 2
    assert result["stopped_in"] == "tests/test_a.py::test_slow"
    assert result["unreached"] == ["tests/test_never.py"]


def test_parametrised_nodeid_cannot_disguise_a_red_test():
    """Красное не должно читаться как зелёное из-за текста внутри имени теста.

    nodeid параметризованного теста содержит произвольный текст, включая пробелы и сами
    слова-вердикты. Замер #336: нежадный разбор на строке
    `tests/test_a.py::t2[a b PASSED c] FAILED` возвращал PASSED — то есть гейт пропустил бы
    красноту в main. Поэтому вердикт берётся последний на строке.
    Итоговая сводка (`FAILED nodeid - ...`) не должна считаться вторым провалом.
    """
    from app.merge_test_gate import _partial_progress

    progress = _partial_progress(
        "FAILED tests/test_a.py::t2[a b PASSED c] - assert 1 == 2\n"
        "tests/test_a.py::t1 PASSED [ 1%]\n"
        "tests/test_a.py::t2[a b PASSED c] FAILED [ 2%]\n"
        "tests/test_a.py::t3_inflight ",
        ["tests/test_a.py", "tests/test_b.py"],
    )

    assert progress["failed_tests"] == ["tests/test_a.py::t2[a b PASSED c]"]
    assert progress["passed_count"] == 1
    assert progress["stopped_in"] == "tests/test_a.py::t3_inflight"
    assert progress["unreached"] == ["tests/test_b.py"]


def test_argv_verbosity_really_prints_per_test_lines(tmp_path):
    """Гварда на неочевидную арифметику флагов, без которой всё выше — пустышка.

    `-q` это −1, `-vv` это +2; сумма +1 даёт потестовые строки. Замена на «более
    аккуратное» `-q -v` даёт сумму 0 — снова безымянные точки, и разбор перестаёт
    что-либо находить, оставаясь зелёным на моках. Поэтому здесь настоящий pytest.
    """
    from app.merge_test_gate import pytest_argv

    (tmp_path / "test_two.py").write_text(
        "def test_first():\n    assert True\n\n\ndef test_second():\n    assert True\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        pytest_argv(["test_two.py"]),
        cwd=str(tmp_path), capture_output=True, text=True, timeout=120, check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "test_two.py::test_first PASSED" in proc.stdout
    assert "test_two.py::test_second PASSED" in proc.stdout


@pytest.mark.asyncio
@pytest.mark.parametrize("gate_db", [{
    "app/widget.py": "VALUE = 1\n",
    "tests/test_widget.py": "def test_widget():\n    assert True\n",
}], indirect=True)
async def test_green_mapped_test_reaches_executor(gate_db, monkeypatch):
    result, calls = await _run_with_spy(monkeypatch, worktree=str(gate_db))
    assert len(calls) == 1
    assert result["operation_state"] == "SUCCEEDED"
    assert result["test_gate"]["status"] == "passed"


@pytest.mark.asyncio
@pytest.mark.parametrize("gate_db", [{
    "docs/note.md": "no code\n",
}], indirect=True)
async def test_docs_only_change_skips_gate_and_merges(gate_db, monkeypatch):
    result, calls = await _run_with_spy(monkeypatch, worktree=str(gate_db))
    assert len(calls) == 1
    assert result["test_gate"]["status"] == "skipped"
    assert result["test_gate"]["reason"] == "no_mapped_tests"


def test_per_test_ceiling_is_far_below_the_smallest_batch_budget():
    """Потолок узла бесполезен, если он сравним с бюджетом партии.

    Пол бюджета — партия из одного файла: `budget_for(1)`. Ниже трети от него один висяк
    физически не может выесть партию, а второй и третий приносят FAILED с именами раньше,
    чем истечёт общий бюджет.
    """
    from app import merge_test_gate as gate

    assert gate.PER_TEST_TIMEOUT_SECONDS * 2 < gate.budget_for(1), (
        "per-test ceiling must stay far under the smallest batch budget"
    )


@pytest.mark.parametrize("per_test_timeout", [2.0])
def test_hung_node_becomes_a_named_red_not_inconclusive(
    tmp_path, monkeypatch, per_test_timeout,
):
    """#474 — один зависший узел обязан краснеть ИМЕНЕМ, а не съедать бюджет партии.

    Замер 04.09: мерж #466 простоял 9+ минут на
    `test_concurrent_keys_start_exactly_one_executor_and_survive_request_return`
    (процесс жив, CPU 1%, состояние `S` — ждал события, переставшего наступать), после чего
    гейт вернул `inconclusive` без единого имени, а мержи всего проекта стояли всё это время.

    Здесь настоящий pytest, а не мок: проверяемое поведение целиком принадлежит плагину и
    флагам, и на заглушках оно зелено при любой реализации. Потолок параметризован, чтобы
    прогон стоил секунды, а не заявленные 120.
    """
    from app import merge_test_gate as gate
    from app.acceptance import FAILED

    monkeypatch.setattr(gate, "PER_TEST_TIMEOUT_SECONDS", per_test_timeout)
    (tmp_path / "test_hang.py").write_text(
        "import threading\n"
        "\n"
        "\n"
        "def test_waits_for_an_event_that_never_comes():\n"
        "    threading.Event().wait()\n"
        "\n"
        "\n"
        "def test_after_the_hang():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    batch_budget = 20.0

    started = time.monotonic()
    result = gate.run_pytest(str(tmp_path), ["test_hang.py"], timeout=batch_budget)
    elapsed = time.monotonic() - started

    assert result["status"] == FAILED, result["output"]
    assert result["reason"] == "exit_nonzero", (
        "pytest must finish on its own; the batch budget must not be what stops it"
    )
    assert "test_waits_for_an_event_that_never_comes" in result["output"]
    # `signal`, а не `thread`: `thread` убил бы весь процесс через `os._exit` и унёс бы
    # построчные вердикты, по которым гейт вообще отличает красноту от «не успели».
    assert "test_after_the_hang PASSED" in result["output"], (
        "the rest of the batch must keep running after one node hits the ceiling"
    )
    assert elapsed < batch_budget / 2, (
        f"the ceiling must land long before the batch budget, took {elapsed:.1f}s"
    )


def test_pytest_argv_carries_the_per_test_ceiling_and_its_method():
    from app import merge_test_gate as gate

    argv = gate.pytest_argv(["tests/test_widget.py"])

    assert f"--timeout={gate.PER_TEST_TIMEOUT_SECONDS:g}" in argv
    assert f"--timeout-method={gate.PER_TEST_TIMEOUT_METHOD}" in argv
    assert gate.PER_TEST_TIMEOUT_METHOD == "signal"


def test_missing_timeout_plugin_is_inconclusive_not_red(tmp_path, monkeypatch):
    """Интерпретатор без `pytest-timeout` не должен читаться как «тесты красные».

    pytest отвергает незнакомый флаг usage-ошибкой ДО сбора: тесты не запускались вовсе.
    Ветка `exit_nonzero` объявила бы это провалом и заблокировала мержи всех проектов.
    """
    from app import merge_test_gate as gate
    from app.acceptance import INCONCLUSIVE

    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["pytest"],
            returncode=4,
            stdout="",
            stderr=(
                "ERROR: usage: pytest [options] [file_or_dir]\n"
                "pytest: error: unrecognized arguments: --timeout=120\n"
            ),
        ),
    )

    result = gate.run_pytest(str(tmp_path), ["tests/test_widget.py"])

    assert result["status"] == INCONCLUSIVE
    assert result["reason"] == "pytest_timeout_unavailable"


def test_real_failure_mentioning_the_timeout_flag_stays_red(tmp_path, monkeypatch):
    """Находка Luna (#474, раунд 1): распознавать плагин по тексту вывода — мало.

    Красный тест, чей вывод содержит `unrecognized arguments … --timeout`, ушёл бы в
    INCONCLUSIVE («повтори»), то есть настоящая краснота читалась бы как «мы не успели».
    Отличает их код возврата: usage-ошибка pytest — это 4, обычный провал — 1.
    """
    from app import merge_test_gate as gate
    from app.acceptance import FAILED

    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["pytest"],
            returncode=1,
            stdout=(
                "tests/test_widget.py::test_cli FAILED [100%]\n"
                "E  error: unrecognized arguments: --timeout=5\n"
            ),
            stderr="",
        ),
    )

    result = gate.run_pytest(str(tmp_path), ["tests/test_widget.py"])

    assert result["status"] == FAILED
    assert result["reason"] == "exit_nonzero"
