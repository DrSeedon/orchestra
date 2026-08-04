"""#61 — возврат воркера на задачу, ветка которой смержена СКВОШЕМ.

Стенд боевой: настоящий сквош-мерж, база потом правит те же строки (без этого конфликта
нет — замер Phase 1), воркер уехал на adhoc-ветку и возвращается.
"""
import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


@pytest.fixture
def env(tmp_path, monkeypatch):
    import app.db as dbmod

    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "t.db")
    dbmod.init_db()
    root = tmp_path / "worktrees"
    root.mkdir()
    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", root)

    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", cwd=repo)
    git("config", "user.email", "t@t", cwd=repo)
    git("config", "user.name", "T", cwd=repo)
    (repo / "README.md").write_text("# test")
    git("add", ".", cwd=repo)
    git("commit", "-m", "init", cwd=repo)
    git("branch", "-M", "main", cwd=repo)

    from app.workspace import create_worktree

    wt = create_worktree(str(repo), "worker", "61", base_branch="main")
    (Path(wt.path) / "feature.txt").write_text("работа воркера")
    git("add", "-A", cwd=wt.path)
    git("commit", "-m", "#61: работа воркера", cwd=wt.path)
    worker_head = git("rev-parse", "HEAD", cwd=wt.path).stdout.strip()

    git("merge", "--squash", wt.branch, cwd=repo)
    git("commit", "-m", "#61: squash", cwd=repo)
    # база живёт дальше и правит ТЕ ЖЕ строки — без этого конфликта не будет
    (repo / "feature.txt").write_text("работа воркера, доработанная в main")
    git("add", "-A", cwd=repo)
    git("commit", "-m", "доработка поверх той же работы", cwd=repo)

    git("checkout", "-b", "adhoc-1-1/worker", cwd=wt.path)

    sid = str(uuid.uuid4())
    dbmod.save_session({
        "id": sid, "name": "worker", "scope": str(repo), "cwd": str(repo),
        "model": "claude-sonnet-5[1m]", "system_prompt": "", "status": "idle",
        "session_id": None, "cost_usd": 0.0, "worktree_path": wt.path,
        "branch": "adhoc-1-1/worker", "base_branch": "main", "is_orchestrator": False,
        "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None, "task_id": "", "needs_switch": 0,
    })
    return {"repo": str(repo), "wt": wt, "sid": sid, "worker_head": worker_head, "db": dbmod}


def _record_merge(dbmod, scope, branch, head, *, state="SUCCEEDED", point="REACHED"):
    """Запись об успешном мерже — наше доказательство, которого git выдать не может."""
    with dbmod._conn() as c:
        c.execute(
            """INSERT INTO merge_operations
               (operation_id, session_id, scope, worker_name, request_json, request_hash,
                dedupe_fingerprint, accepted_worker_branch, accepted_worker_head,
                state, commit_point, result_json, result_hash, created_at, updated_at)
               VALUES (?, 's', ?, 'worker', '{}', 'h', 'f', ?, ?, ?, ?, ?, 'h', ?, ?)""",
            (str(uuid.uuid4()), scope, branch, head, state, point,
             json.dumps({"git": {"worker_head": head}}),
             datetime.now(timezone.utc).isoformat(),
             datetime.now(timezone.utc).isoformat()),
        )


def _verdict(env, force=False):
    from app.routes.sessions import _existing_branch_verdict

    return _existing_branch_verdict(
        env["wt"].path, env["wt"].branch, env["repo"], force,
    )


def test_without_proof_platform_does_not_touch_the_branch(env):
    """Записи о мерже нет → решать за человека, что его работа не нужна, платформа не вправе."""
    assert _verdict(env)["recreate_from_base"] is False


def test_proof_makes_it_benign(env):
    _record_merge(env["db"], env["repo"], env["wt"].branch, env["worker_head"])
    assert _verdict(env)["recreate_from_base"] is True


def test_work_after_merge_is_fatal_and_names_both_heads(env):
    _record_merge(env["db"], env["repo"], env["wt"].branch, env["worker_head"])
    # воркер дописал коммит ПОСЛЕ мержа
    git("checkout", env["wt"].branch, cwd=env["wt"].path)
    (Path(env["wt"].path) / "after.txt").write_text("работа после мержа")
    git("add", "-A", cwd=env["wt"].path)
    git("commit", "-m", "после мержа", cwd=env["wt"].path)
    new_head = git("rev-parse", "HEAD", cwd=env["wt"].path).stdout.strip()
    git("checkout", "adhoc-1-1/worker", cwd=env["wt"].path)

    v = _verdict(env)
    print("\nFATAL:", v["error"])
    assert v["ok"] is False and v["state"] == "branch_has_work_after_merge"
    assert new_head in v["error"] and env["worker_head"] in v["error"]
    assert "force=true" in v["error"]
    assert _verdict(env, force=True)["recreate_from_base"] is True


def test_failed_merge_operation_is_not_a_proof(env):
    _record_merge(env["db"], env["repo"], env["wt"].branch, env["worker_head"],
                  state="FAILED", point="NOT_REACHED")
    assert _verdict(env)["recreate_from_base"] is False


def test_return_to_squash_merged_branch_now_succeeds(env):
    """Сквозной случай: раньше здесь был конфликт, теперь ветка начинается от базы."""
    from app.workspace import switch_worktree_branch

    _record_merge(env["db"], env["repo"], env["wt"].branch, env["worker_head"])
    # текущая adhoc-ветка воркера тоже смержена сквошем — без её записи уйти с неё
    # не даст проверка содержимого, и это часть того же дефекта
    current_head = git("rev-parse", "HEAD", cwd=env["wt"].path).stdout.strip()
    _record_merge(env["db"], env["repo"], "adhoc-1-1/worker", current_head)
    verdict = _verdict(env)
    assert verdict["discard_current"] is True, "запись должна разрешать уход с текущей ветки"
    res = switch_worktree_branch(
        env["wt"].path, env["wt"].branch, from_ref="main",
        force=verdict["discard_current"],
        recreate_from_base=verdict["recreate_from_base"],
    )
    print("\nВОЗВРАТ:", res)
    assert res["ok"] is True and res["state"] == "recreated_from_base"
    head_now = git("rev-parse", "HEAD", cwd=env["wt"].path).stdout.strip()
    main_head = git("rev-parse", "main", cwd=env["repo"]).stdout.strip()
    assert head_now == main_head, "ветка обязана начинаться ровно от базы"
    assert git("rev-parse", "--abbrev-ref", "HEAD",
               cwd=env["wt"].path).stdout.strip() == env["wt"].branch
    # работа не потеряна: она в базе, и доработка базы на месте
    assert (Path(env["wt"].path) / "feature.txt").read_text() == \
        "работа воркера, доработанная в main"


def test_old_path_still_conflicts_without_recreate(env):
    """Предпосылка теста выше: без пересоздания это по-прежнему конфликт."""
    from app.workspace import switch_worktree_branch

    res = switch_worktree_branch(
        env["wt"].path, env["wt"].branch, from_ref="main", force=True,
    )
    print("\nСТАРЫЙ ПУТЬ:", res.get("error", "")[:80])
    assert res["ok"] is False and res.get("conflicts") == ["feature.txt"]
