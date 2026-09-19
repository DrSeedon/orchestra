"""Check the shared root rules: one file, a symlink beside it, budget and KB index."""
import argparse
import os
from pathlib import Path
import re
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.kb_index import kb_topic_files, kb_topic_index

MAX_INSTRUCTION_BYTES = 16 * 1024
SOURCE = "AGENTS.md"
# `CLAUDE.md` — СИМЛИНК на источник, а не копия. Claude Code читает только `CLAUDE.md`
# (поддержка `AGENTS.md` заявлена с 2.1.277, но на 2.1.278 у нас не включается), Codex
# читает только `AGENTS.md`. Копия дважды разъезжалась с источником, и один раз
# Claude-агенты не видели правил владельца; симлинк разойтись не может физически.
LINK = "CLAUDE.md"


def check_kb_index(root: Path) -> None:
    """Every topic file must be listed once, with a description, inside ``kb/``.

    The root rules no longer carry the list — the platform injects it from
    ``kb/README.md`` into the system prompt (:func:`app.kb_index.kb_index_block`). This is
    what still catches a topic nobody indexed, which no agent would ever be shown.
    """
    missing = kb_topic_files(root) - kb_topic_index(root).keys()
    if missing:
        raise ValueError(f"KB topics missing from README: {', '.join(sorted(missing))}")


def _read(path: Path) -> bytes:
    return path.read_bytes()


def _validate(body: bytes, name: str) -> None:
    text = body.decode("utf-8")
    if not text.strip():
        raise ValueError(f"{name}: instructions must not be empty")
    if len(body) >= MAX_INSTRUCTION_BYTES:
        raise ValueError(f"{name}: {len(body)} bytes exceeds the <16 KiB budget")
    without_code = re.sub(r"```[\s\S]*?```|`[^`\n]*`", "", text)
    if re.search(r"(?<![\w\\])@(?=[\w./~])\S+", without_code):
        raise ValueError(f"{name}: root imports are not allowed; use on-demand links")


def check(root: Path) -> None:
    _validate(_read(root / SOURCE), SOURCE)
    link = root / LINK
    if not link.is_symlink():
        raise ValueError(
            f"{LINK} must be a symlink to {SOURCE}, not a copy: a copy drifts and then one "
            f"client silently runs on stale rules")
    target = os.readlink(link)
    if target != SOURCE:
        raise ValueError(f"{LINK} points at {target!r}, expected {SOURCE!r}")
    check_kb_index(root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        check(args.root)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Instruction contract: {error}\n")
    print(f"Instruction contract OK: {SOURCE} below 16 KiB, {LINK} is a symlink to it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
