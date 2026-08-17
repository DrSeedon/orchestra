"""#255 — мерж без acceptance_command всё равно не сажает красный тест в main.

Оракул: «execute_merge_session вызван» — не цель. Цель — красное не доехало.
Полный сьют (728s + глобальный test_lock) здесь не гоняем.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests.test_acceptance import _run_with_spy, _session_row


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
        lambda _path: ("task-42/worker", "b" * 40),
    )
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


def test_large_mapped_subset_runs_all_files_in_bounded_batches(monkeypatch):
    from app import merge_test_gate as gate

    tests = [f"tests/test_{n:02d}.py" for n in range(14)]
    calls = []

    monkeypatch.setattr(gate, "changed_paths", lambda _worktree: ["app/widget.py"])
    monkeypatch.setattr(gate, "select_tests", lambda _changed, worktree: tests)

    def fake_run(worktree, batch, *, timeout=None):
        calls.append((list(batch), timeout))
        return {
            "status": gate.PASSED,
            "reason": "",
            "exit_code": 0,
            "output": "passed " + ", ".join(batch),
            "tests": list(batch),
        }

    monkeypatch.setattr(gate, "run_pytest", fake_run)
    result = gate.evaluate_test_gate("/worktree")

    assert result["status"] == gate.PASSED
    assert [test for batch, _timeout in calls for test in batch] == tests
    assert [len(batch) for batch, _timeout in calls] == [12, 2]
    assert sum(timeout for _batch, timeout in calls) <= gate.DEFAULT_TIMEOUT_SECONDS


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
    outcomes = iter((gate.FAILED, gate.INCONCLUSIVE))

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
    assert result["tests"] == tests
    assert all(test in result["output"] for test in (tests[0], tests[-1]))
    assert "diagnostic-tests/test_00.py" in result["output"]


def test_large_subset_keeps_diagnostics_from_verbose_batches(monkeypatch):
    from app import merge_test_gate as gate

    tests = [f"tests/test_{n:02d}.py" for n in range(13)]
    outcomes = iter((gate.FAILED, gate.INCONCLUSIVE))
    diagnostics = iter(("early-failure", "late-timeout"))

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
    assert argv.count("-m") == 1
    assert "pytest" in argv


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
    assert result["output"] == expected
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
    assert result["output"] == payload[-4000:]


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
