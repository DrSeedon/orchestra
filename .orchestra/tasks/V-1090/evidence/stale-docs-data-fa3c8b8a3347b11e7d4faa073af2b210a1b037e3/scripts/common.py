"""Shared paths and helpers."""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TASKS = os.path.join(ROOT, "tasks")

# Variables of the parent session that must not reach a tested agent or a scoring run.
_SCRUB = re.compile(r"^(CLAUDE|ANTHROPIC|OPENAI|CODEX|AWS_|GOOGLE_|VERTEX|BEDROCK|MCP_)", re.I)
_SCRUB_EXACT = {"DISABLE_TELEMETRY", "DISABLE_PROMPT_CACHING", "DISABLE_FEEDBACK_COMMAND",
                "DISABLE_AUTOUPDATER", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME", "VIRTUAL_ENV"}


def clean_env(extra=None):
    env = {k: v for k, v in os.environ.items()
           if not _SCRUB.match(k) and k.upper() not in _SCRUB_EXACT}
    env.update(extra or {})
    return env


def load_task(task_id):
    with open(os.path.join(TASKS, task_id, "task.json"), encoding="utf-8") as fh:
        return json.load(fh)
