from pathlib import Path
import subprocess
from datetime import datetime, timezone


PROJECT_CONTEXT_FILE = """schema_version = 1
scale = "production test platform"
users = "review coverage tests"
stack = "Python and SQLite"
philosophy = "snapshot-bound review"
what_matters = "review provenance and data integrity"
what_does_not_matter = "deployment ceremony"
"""

def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return proc.stdout.strip()

def _repo(tmp_path: Path, changed_path: str = "app/widget.py") -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "review-coverage@test")
    _git(repo, "config", "user.name", "review coverage")
    (repo / "README.md").write_text("base\n")
    owner = repo / ".orchestra/project-context.toml"
    owner.parent.mkdir()
    owner.write_text(PROJECT_CONTEXT_FILE, encoding="utf-8")
    _git(repo, "add", "README.md", ".orchestra/project-context.toml")
    _git(repo, "commit", "-m", "base")
    assert _git(repo, "show", "HEAD:.orchestra/project-context.toml") == PROJECT_CONTEXT_FILE.strip()
    target_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "switch", "-c", "task-462/worker")
    path = repo / changed_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("VALUE = 1\n")
    _git(repo, "add", changed_path)
    _git(repo, "commit", "-m", "production change")
    return repo, target_sha

def _save_session(db, *, session_id: str, name: str, scope: str, worktree: str,
                  role: str, is_orchestrator: bool) -> None:
    db.save_session({
        "id": session_id,
        "name": name,
        "scope": scope,
        "cwd": scope,
        "model": "gpt-5.6-sol",
        "system_prompt": "",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": worktree,
        "branch": "task-462/worker" if not is_orchestrator else "main",
        "base_branch": "main",
        "is_orchestrator": is_orchestrator,
        "role": role,
        "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "task_id": "462" if not is_orchestrator else "",
        "needs_switch": 0,
    })
