"""Воркер в ДРУГОМ репозитории, чем проект родителя, обязан быть назван вслух.

28.08.2026: три ребёнка веера отработали research по pitch-ball и закоммитили его в
репозиторий comfy-image-pipeline (`.orchestra/tasks/1/`, 135 строк). Расхождения не видел
никто — ни родитель в ответе спавна, ни сами дети в своём задании.
"""

import pytest


def _mapping(common_dir: str, repo: str) -> dict:
    return {
        "worktree_path": "/orchestra/worktrees/slug/child",
        "repo_path": repo,
        "git_common_dir": common_dir,
        "branch": "task-1/child",
    }


def test_same_repository_stays_silent():
    """Обычный воркер своего проекта не должен получать никаких предупреждений."""
    from app.mcp_stdio import _cross_repo_note

    note = _cross_repo_note("/projects/alpha", _mapping("/projects/alpha/.git", "/projects/alpha"))

    assert note == ""


def test_foreign_repository_is_named_with_both_sides():
    from app.mcp_stdio import _cross_repo_note

    note = _cross_repo_note("/projects/alpha", _mapping("/projects/beta/.git", "/projects/beta"))

    assert "ДРУГОЙ РЕПОЗИТОРИЙ" in note
    # Обе стороны названы явно: куда коммитит воркер и какой проект у родителя.
    assert "/projects/beta" in note and "/projects/alpha" in note
    # И следствие, из-за которого сломались мержи.
    assert "merge_worker" in note


def test_note_compares_repositories_not_path_strings():
    """Worktree ВСЕГДА лежит внутри каталога Orchestra.

    Сравнение `worktree_path` со `scope` дало бы предупреждение на каждом обычном
    воркере — то есть шум, который перестают читать.
    """
    from app.mcp_stdio import _cross_repo_note

    mapping = _mapping("/projects/alpha/.git", "/projects/alpha")
    mapping["worktree_path"] = "/mnt/data/Projects/Python/orchestra/worktrees/x/child"

    assert _cross_repo_note("/projects/alpha", mapping) == ""


def test_missing_scope_or_common_dir_never_warns():
    """Нет данных — нет вывода: догадка здесь хуже молчания."""
    from app.mcp_stdio import _cross_repo_note

    assert _cross_repo_note("", _mapping("/projects/beta/.git", "/projects/beta")) == ""
    assert _cross_repo_note("/projects/alpha", _mapping("", "/projects/beta")) == ""
