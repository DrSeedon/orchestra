def test_mutation_paths_keep_dot_directories_and_drop_deleted_tests(tmp_path, monkeypatch):
    from contextlib import contextmanager

    from app import merge_test_gate as gate
    from tests.test_merge_test_gate import _mutation_repo

    repo, target = _mutation_repo(
        tmp_path,
        "from app.widget import VALUE\n\n"
        "def test_widget():\n    assert VALUE == 2\n",
    )
    observed = []
    monkeypatch.setattr(
        gate, "changed_paths",
        lambda *_args, **_kwargs: [
            "app/widget.py", "tests/test_widget.py", "tests/test_deleted.py",
            ".orchestra/tasks/V-702/helper.py",
        ],
    )
    monkeypatch.setattr(
        gate, "changed_test_nodes",
        lambda *_args: (["tests/test_widget.py::test_widget"], []),
    )

    original_tree = gate._mutation_tree

    @contextmanager
    def track_tree(worktree, target_sha, tests):
        observed.extend(tests)
        with original_tree(worktree, target_sha, tests) as tree:
            yield tree

    monkeypatch.setattr(gate, "_mutation_tree", track_tree)
    monkeypatch.setattr(
        gate, "run_pytest",
        lambda _worktree, tests, **_kwargs: {
            "status": gate.PASSED, "reason": "", "exit_code": 0,
            "output": "passed", "tests": list(tests),
        },
    )
    result = gate.evaluate_test_gate(str(repo), target_ref="main", target_sha=target)

    assert result["changed_tests"] == ["tests/test_deleted.py", "tests/test_widget.py"]
    assert result["changed_sources"] == ["app/widget.py"]
    assert observed == ["tests/test_deleted.py", "tests/test_widget.py"]
    assert result["mutation_gate"]["status"] == gate.FAILED
    assert result["mutation_gate"]["reason"] == "tests_not_guarding_source"


def test_pytest_usage_error_is_not_a_test_failure(monkeypatch, tmp_path):
    import subprocess

    from app import merge_test_gate as gate

    def usage_error(argv, **_kwargs):
        return subprocess.CompletedProcess(
            argv, gate.USAGE_ERROR_EXIT_CODE, "ERROR: usage: pytest [options]", "",
        )

    monkeypatch.setattr(gate.subprocess, "run", usage_error)

    result = gate.run_pytest(str(tmp_path), ["tests/test_widget.py"])

    assert result["status"] == gate.INCONCLUSIVE
    assert result["reason"] == "pytest_usage_error"
    assert result["exit_code"] == gate.USAGE_ERROR_EXIT_CODE
