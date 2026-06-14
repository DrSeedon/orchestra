"""Auto-bootstrap: ensure workspace + default orchestrator on first startup."""

import logging
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.db import get_all_sessions, save_session
from app.models import DEFAULT_MODEL, resolve_model, backend_for_model

logger = logging.getLogger(__name__)

WORKSPACE_DIR = "/workspace/project"

_DEFAULT_CLAUDE_MD = """\
# Project

This workspace was auto-created by Orchestra.
"""

_DEFAULT_SYSTEM_PROMPT = (
    "You are an AI orchestrator. Manage workers, delegate tasks, report results."
)


async def ensure_bootstrap() -> None:
    """Idempotent bootstrap: workspace dir + default orchestrator DB record."""
    _fix_runtime_permissions()
    _ensure_workspace()
    _ensure_orchestrator()


def _fix_runtime_permissions() -> None:
    """Make volume-mounted dirs writable by agent — Docker creates them as root.

    Can't chown (CAP_CHOWN dropped). Use chmod a+rwx instead (no CAP_FOWNER needed
    for dirs owned by current user = root).
    """
    for d in ["/opt/orchestra/worktrees", "/opt/orchestra/data"]:
        if os.path.isdir(d):
            subprocess.run(["chmod", "-R", "a+rwX", d], capture_output=True)


def _resolve_uid(val: str) -> int | None:
    try:
        return int(val)
    except ValueError:
        pass
    import pwd
    try:
        return pwd.getpwnam(val).pw_uid
    except KeyError:
        return None


def _ensure_workspace() -> None:
    ws = Path(WORKSPACE_DIR)
    if ws.is_dir():
        return

    raw_uid = os.environ.get("ORCHESTRA_AGENT_UID")
    uid = _resolve_uid(raw_uid) if raw_uid else None
    run_kwargs: dict = {}
    if uid is not None:
        def _preexec():
            os.setuid(uid)
        run_kwargs["preexec_fn"] = _preexec

    try:
        subprocess.run(["mkdir", "-p", str(ws)], check=True, capture_output=True, **run_kwargs)
    except (OSError, subprocess.CalledProcessError) as e:
        logger.warning("Bootstrap: cannot create workspace %s: %s", WORKSPACE_DIR, e)
        return

    subprocess.run(["git", "init", "-b", "main"], cwd=str(ws), capture_output=True, **run_kwargs)
    subprocess.run(["git", "config", "user.email", "orchestra@seedon.ru"], cwd=str(ws), capture_output=True, **run_kwargs)
    subprocess.run(["git", "config", "user.name", "Orchestra"], cwd=str(ws), capture_output=True, **run_kwargs)
    # Make workspace writable by root (for git worktree operations) — chmod 777 on .git
    subprocess.run(["chmod", "-R", "a+rwX", str(ws)], capture_output=True)
    # safe.directory for root (Orchestra main process) — workspace owned by agent
    subprocess.run(["git", "config", "--global", "safe.directory", "*"], capture_output=True)
    # safe.directory for agent user (opencode daemon)
    subprocess.run(["git", "config", "--global", "safe.directory", "*"], capture_output=True, **run_kwargs)
    subprocess.run(["bash", "-c", f"cat > {ws}/CLAUDE.md << 'EOF'\n{_DEFAULT_CLAUDE_MD}\nEOF"],
                   capture_output=True, **run_kwargs)
    subprocess.run(["bash", "-c", f"echo 'opencode.json' > {ws}/.gitignore"],
                   capture_output=True, **run_kwargs)
    subprocess.run(
        ["git", "add", "CLAUDE.md", ".gitignore"],
        cwd=str(ws), capture_output=True, **run_kwargs,
    )
    subprocess.run(
        ["git", "commit", "-m", "bootstrap: init workspace"],
        cwd=str(ws), capture_output=True, **run_kwargs,
    )
    logger.info("Bootstrap: created workspace %s", WORKSPACE_DIR)


def _ensure_orchestrator() -> None:
    sessions = get_all_sessions()
    has_orch = any(
        bool(s.get("is_orchestrator")) or s.get("role") == "orchestrator"
        for s in sessions
    )
    if has_orch:
        logger.info("Bootstrap: skipping, orchestrator exists")
        return

    name = os.environ.get("BOOTSTRAP_ORCH_NAME", "orchestrator")
    model = resolve_model(os.environ.get("DEFAULT_MODEL", DEFAULT_MODEL))
    scope = WORKSPACE_DIR

    prompt_file = Path(scope) / "prompts" / "orchestrator.md"
    if prompt_file.is_file():
        system_prompt = prompt_file.read_text().strip()
    else:
        system_prompt = _DEFAULT_SYSTEM_PROMPT

    save_session({
        "id": str(uuid.uuid4()),
        "name": name,
        "scope": scope,
        "cwd": scope,
        "model": model,
        "system_prompt": system_prompt,
        "status": "idle",
        "session_id": None,
        "cost_usd": 0,
        "worktree_path": "",
        "branch": "",
        "is_orchestrator": 1,
        "role": "orchestrator",
        "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "backend_type": backend_for_model(model),
    })
    logger.info("Bootstrap: created default orchestrator '%s' (model=%s)", name, model)
