"""KB topic index — one parser for the root contract check and the agent prompt.

The list of topics has exactly one source: ``<scope>/.orchestra/kb/README.md``. Both the
committed-rules check (`scripts/check_instruction_contract.py`) and the system prompt the
platform assembles read it through here, so a second copy cannot drift away from the first.
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# `- [<slug>](<topic>.md) — <description>` — the description is what the agent is shown.
_ENTRY = re.compile(r"- \[[^\]]+\]\(([^)]+)\) — (.+)")

_HEADER = """## Project knowledge base

Index only — the topics are NOT loaded. Pick 1–3 anchors, run
`rg -n -i -F --glob '*.md' '<anchor>' .orchestra/kb`, then read the matched fact with its
status and date. Paths below are relative to the repository root."""


def kb_topic_files(root: str | Path) -> set[str]:
    """Topic files present under ``<root>/.orchestra/kb/`` (README itself excluded)."""
    kb = Path(root) / ".orchestra" / "kb"
    return {p.relative_to(kb).as_posix() for p in kb.rglob("*.md") if p != kb / "README.md"}


def kb_topic_index(root: str | Path) -> dict[str, str]:
    """Map topic path → description, in README order. ``{}`` when the project has no index.

    :raises ValueError: an entry that leaves the topic inventory, repeats a topic, or has
        no description. A listed topic the agent cannot open is worse than one it never
        saw: it spends a turn guessing where the file went.
    """
    kb = Path(root) / ".orchestra" / "kb"
    readme = kb / "README.md"
    if not readme.is_file():
        return {}
    topics = kb_topic_files(root)
    entries: dict[str, str] = {}
    for line in readme.read_text(encoding="utf-8").splitlines():
        match = _ENTRY.fullmatch(line)
        if not match:
            continue
        path, description = match.groups()
        if path.startswith("../"):
            continue
        if path not in topics or not (kb / path).resolve().is_relative_to(kb.resolve()):
            raise ValueError(f"KB index points outside its topic inventory: {path}")
        if path in entries:
            raise ValueError(f"KB topic indexed more than once: {path}")
        if not description.strip():
            raise ValueError(f"KB topic needs a description: {path}")
        entries[path] = description.strip()
    return entries


def kb_index_block(scope: str) -> str:
    """The KB index block injected into an agent's system prompt, or "" when there is none.

    A project without a KB gets nothing at all — an empty heading reads as "this project
    has no knowledge worth reading", which is a claim we have no evidence for.
    """
    if not scope:
        return ""
    try:
        entries = kb_topic_index(scope)
    except OSError as exc:
        # Unreadable README is an environment fault, not a broken index: refusing here
        # would take down every spawn in that project over a permission bit.
        logger.warning("KB index unreadable in %s: %s", scope, exc)
        return ""
    if not entries:
        return ""
    lines = "\n".join(
        f"- [{description}](.orchestra/kb/{path})" for path, description in entries.items()
    )
    return f"{_HEADER}\n\n{lines}"
