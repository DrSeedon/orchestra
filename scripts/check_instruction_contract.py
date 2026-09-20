"""Check the shared root rules: ONE file, nothing beside it, budget and KB index."""
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
# Второго корневого файла правил быть не должно ни в каком виде. Codex читает `AGENTS.md`
# сам; Claude Code — модом `agents-md` (включён глобально на машине). Пока рядом лежала
# копия, она дважды разъехалась с источником, и один раз Claude-агенты работали на
# устаревших правилах владельца, ничего об этом не сообщив.
FORBIDDEN = "CLAUDE.md"


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
    beside = root / FORBIDDEN
    if beside.is_symlink() or beside.exists():
        raise ValueError(
            f"{FORBIDDEN} must not exist beside {SOURCE}: a second root rules file is a second "
            f"source of truth, and Claude Code reads {SOURCE} through the agents-md mod")
    check_kb_index(root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        check(args.root)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Instruction contract: {error}\n")
    print(f"Instruction contract OK: {SOURCE} below 16 KiB, no {FORBIDDEN} beside it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
