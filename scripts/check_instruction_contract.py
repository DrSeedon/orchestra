"""Check the shared root rules; --sync explicitly regenerates the Claude copy."""
import argparse
import os
from pathlib import Path
import re
import tempfile

MAX_INSTRUCTION_BYTES = 16 * 1024
FILES = ("AGENTS.md", "CLAUDE.md")
INDEX_START = "<!-- kb-topics:start -->"
INDEX_END = "<!-- kb-topics:end -->"


def topic_index(root: Path) -> str:
    kb = root / ".orchestra/kb"
    topics = {p.relative_to(kb).as_posix() for p in kb.rglob("*.md")
              if p != kb / "README.md"}
    entries = {}
    for line in (kb / "README.md").read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"- \[[^\]]+\]\(([^)]+)\) — (.+)", line)
        if not match:
            continue
        path, description = match.groups()
        if path.startswith("../"):
            continue
        if path not in topics or not (kb / path).resolve().is_relative_to(kb.resolve()):
            raise ValueError(f"KB index points outside its topic inventory: {path}")
        if path in entries:
            raise ValueError(f"KB topic indexed more than once: {path}")
        entries[path] = description
    missing = topics - entries.keys()
    if not entries or missing:
        raise ValueError(f"KB topics missing from README: {', '.join(sorted(missing)) or 'empty index'}")
    return "\n".join(f"- [{description}](.orchestra/kb/{path})"
                     for path, description in entries.items())


def canonical_body(root: Path) -> bytes:
    text = _read(root / "AGENTS.md").decode("utf-8")
    if text.count(INDEX_START) != 1 or text.count(INDEX_END) != 1:
        raise ValueError("AGENTS.md must contain exactly one generated KB topic block")
    before, rest = text.split(INDEX_START)
    if INDEX_END not in rest:
        raise ValueError("KB topic block markers are reversed")
    _, after = rest.split(INDEX_END)
    return (before + INDEX_START + "\n" + topic_index(root) + "\n" + INDEX_END + after).encode("utf-8")


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
    if bodies[0] != canonical_body(root):
        raise ValueError("root KB topic index is stale; update kb/README.md then run --sync")


def sync(root: Path) -> None:
    body = canonical_body(root)
    _validate(body, "AGENTS.md")
    for name in FILES:
        if (root / name).is_symlink():
            raise ValueError(f"{name}: refusing to overwrite a symlink")
    for name in FILES:
        _write(root / name, body)
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
