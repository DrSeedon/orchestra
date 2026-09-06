"""Check the shared root rules; --sync explicitly regenerates the Claude copy."""
import argparse
import os
from pathlib import Path
import re
import sys
import tempfile

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.kb_index import kb_topic_files, kb_topic_index

MAX_INSTRUCTION_BYTES = 16 * 1024
FILES = ("AGENTS.md", "CLAUDE.md")


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
    if path.is_symlink():
        raise ValueError(f"{path.name}: expected a regular file, not a symlink")
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
    bodies = [_read(root / name) for name in FILES]
    for name, body in zip(FILES, bodies):
        _validate(body, name)
    if bodies[0] != bodies[1]:
        raise ValueError("AGENTS.md and CLAUDE.md differ; run --sync after editing AGENTS.md")
    check_kb_index(root)


def sync(root: Path) -> None:
    body = _read(root / "AGENTS.md")
    _validate(body, "AGENTS.md")
    check_kb_index(root)  # before any write: a bad index must leave both copies untouched
    for name in FILES:
        if (root / name).is_symlink():
            raise ValueError(f"{name}: refusing to overwrite a symlink")
    _write(root / "CLAUDE.md", body)
    check(root)


def _write(target: Path, body: bytes) -> None:
    if target.exists() and target.read_bytes() == body:
        return
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "wb") as output:
            output.write(body)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--sync", action="store_true")
    args = parser.parse_args()
    try:
        if args.sync:
            sync(args.root)
        else:
            check(args.root)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Instruction contract: {error}\n")
    print("Instruction contract OK: identical, non-empty UTF-8 root rules below 16 KiB each")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
