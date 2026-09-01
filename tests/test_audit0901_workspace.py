"""Audit 01.09.2026: отказ разрешить целевую ветку не должен улетать из merge_worktree_to_main.

Шаг стоит ПЕРВЫМ под repo_mutation_lock и не трогает ни одного рефа, поэтому исход Git
известен для любого отказа: ничего не произошло. Улетевшее исключение попадает в catch-all
роута, где становится partial/unknown и держит резервацию задачи.
"""

import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
    (repo / "README.md").write_text("# test")
    (repo / "CLAUDE.md").write_text("# instructions")
    (repo / ".mcp.json").write_text("{}")
    (repo / ".env").write_text("SECRET=123")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, capture_output=True, check=True)
    return repo


@pytest.fixture
def wt_root(tmp_path, monkeypatch):
    root = tmp_path / "worktrees"
    root.mkdir()
    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", root)
    return root


@pytest.fixture
def worker_worktree(git_repo, wt_root):
    from app.workspace import create_worktree

    wt = create_worktree(str(git_repo), "merge-worker", base_branch="main")
    (Path(wt.path) / "work.txt").write_text("done")
    subprocess.run(["git", "add", "."], cwd=wt.path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "work"], cwd=wt.path, capture_output=True, check=True)
    return wt


def test_merge_reports_missing_target_without_raising(git_repo, worker_worktree):
    """Несуществующая цель — чистый отказ 'ничего не произошло', а не partial/unknown.

    Ровно то же условие двумя шагами позже (`target branch does not exist`) возвращает
    failed/not_reached; утечка ValueError из resolve_base_branch уводит роут в catch-all,
    где исход объявляется неизвестным и резервация задачи остаётся висеть.
    """
    from app.workspace import merge_worktree_to_main

    result = merge_worktree_to_main(
        worker_worktree.path, str(git_repo), target_branch="deleted-target",
    )

    assert result["ok"] is False
    assert result["state"] == "failed"
    assert result["commit_point"] == "not_reached"
    assert "deleted-target" in result["error"]
    assert result["_http_status"] == 400


def test_merge_refusal_reports_pinned_worker_identity(git_repo, worker_worktree):
    """Отказ описывает воркера теми значениями, которыми роут его запиннил.

    Улетавший наружу путь строил ответ через `_merge_not_reached(worker_branch=pinned…)`;
    ранний return обязан быть не беднее. Провенанс доказывается парой: без пинов поля
    пустые (git на этом шаге ещё не спрашивали), с пинами — ровно пины.
    """
    from app.workspace import merge_worktree_to_main

    unpinned = merge_worktree_to_main(
        worker_worktree.path, str(git_repo), target_branch="deleted-target",
    )
    pinned = merge_worktree_to_main(
        worker_worktree.path,
        str(git_repo),
        target_branch="deleted-target",
        expected_worker_branch="merge-worker",
        expected_worker_head="0" * 40,
    )

    assert (unpinned["worker_branch"], unpinned["worker_head"]) == ("", "")
    assert pinned["worker_branch"] == "merge-worker"
    assert pinned["worker_head"] == "0" * 40


def test_merge_refusal_normalizes_to_failed_with_status(git_repo, worker_worktree):
    """Потребитель отказа — normalize_merge_result: FAILED/NOT_REACHED и НЕ null-status."""
    from app.merge_operations import normalize_merge_result
    from app.workspace import merge_worktree_to_main

    raw = merge_worktree_to_main(
        worker_worktree.path, str(git_repo), target_branch="deleted-target",
    )
    normalized = normalize_merge_result("op-1", raw, {"target": "deleted-target"})

    assert normalized["operation_state"] == "FAILED"
    assert normalized["commit_point"] == "NOT_REACHED"
    assert normalized["git"]["status"] == "FAILED"
    assert normalized["error"]["code"] == "TARGET_MISSING"
    assert normalized["error"]["status"] == 400
    assert normalized["next_action"]["code"] == "FIX_TARGET_THEN_NEW_OPERATION"


def test_merge_reports_unreadable_refs_without_raising(git_repo, worker_worktree, monkeypatch):
    """`show-ref --verify` с кодом ≠0/1 → RuntimeError из _inspect_branch_ref.

    Тип отказа другой, место — то же самое (первый шаг под локом), поэтому и исход обязан
    быть тем же: failed/not_reached без удержания резервации.
    """
    from app import workspace

    real_git = workspace._git_cmd

    def broken_show_ref(args, **kwargs):
        if "show-ref" in args and "--verify" in args:
            return subprocess.CompletedProcess(
                args, 128, "", "fatal: not a git repository: '.git'",
            )
        return real_git(args, **kwargs)

    monkeypatch.setattr(workspace, "_git_cmd", broken_show_ref)

    result = workspace.merge_worktree_to_main(
        worker_worktree.path, str(git_repo), target_branch="main",
    )

    assert result["ok"] is False
    assert result["state"] == "failed"
    assert result["commit_point"] == "not_reached"
    assert "RuntimeError" in result["error"]
    assert result["_http_status"] == 500


def test_merge_reports_missing_git_binary_without_raising(git_repo, worker_worktree, monkeypatch):
    """Пропавший git = OSError из subprocess: тот же шаг, тот же известный исход."""
    from app import workspace

    real_git = workspace._git_cmd

    def no_git_binary(args, **kwargs):
        if "check-ref-format" in args:
            raise FileNotFoundError(2, "No such file or directory", "git")
        return real_git(args, **kwargs)

    monkeypatch.setattr(workspace, "_git_cmd", no_git_binary)

    result = workspace.merge_worktree_to_main(
        worker_worktree.path, str(git_repo), target_branch="main",
    )

    assert result["ok"] is False
    assert result["state"] == "failed"
    assert result["commit_point"] == "not_reached"
    assert "FileNotFoundError" in result["error"]
    assert result["_http_status"] == 500
