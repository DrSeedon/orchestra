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
    _ensure_workspace()
    _ensure_orchestrator()


def _ensure_workspace() -> None:
    ws = Path(WORKSPACE_DIR)
    if ws.is_dir():
        return

    try:
        ws.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning("Bootstrap: cannot create workspace %s: %s", WORKSPACE_DIR, e)
        return

    subprocess.run(["git", "init"], cwd=str(ws), capture_output=True)
    (ws / "CLAUDE.md").write_text(_DEFAULT_CLAUDE_MD)
    subprocess.run(
        ["git", "add", "CLAUDE.md"],
        cwd=str(ws), capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "bootstrap: init workspace"],
        cwd=str(ws), capture_output=True,
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
