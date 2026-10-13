"""Check agent docs locally with `uv run --frozen python scripts/check_instruction_contract.py`."""
import argparse
import os
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.kb_index import kb_topic_files, kb_topic_index

MAX_INSTRUCTION_BYTES = 16 * 1024
SOURCE = "AGENTS.md"
# `CLAUDE.md` — СИМЛИНК на источник, а не копия, и убирать его нельзя. Мод `agents-md`
# (20.09.2026) научил читать `AGENTS.md` только CLI Claude Code; НАШИ сессии идут через
# Agent SDK — и воркеры Orchestra (`app/backend_claude.py`), и бот Кеши, — а SDK грузит
# ровно `CLAUDE.md` и мод не подхватывает ни через `setting_sources`, ни через `plugins`
# (проверено прогоном 20.09). Без симлинка Claude-воркер молча теряет правила проекта:
# ровно это случилось дважды — 19.09 (#V-600, откачено) и 20.09.
LINK = "CLAUDE.md"

_MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\((?:<([^>]+)>|([^\s)]+))(?:[^)]*)\)")
_CODE_SPAN = re.compile(r"(?<!`)`([^`\n]+)`")
_FENCED_CODE = re.compile(r"```[\s\S]*?```|~~~[\s\S]*?~~~")
_FILE_SUFFIXES = {
    ".md", ".py", ".yaml", ".yml", ".json", ".toml", ".js", ".css", ".sh",
    ".sql", ".txt", ".svg", ".png", ".log", ".db",
}
_CODE_PATH = re.compile(
    r"(?<![\w./~+-])(?:\.\.?/|(?:\.[\w.-]+/)+|[\w@+-]+/)"
    r"[\w@+-]+(?:/[\w@+-]+)*(?:\.[\w@+-]+)?"
)
_BARE_FILE = re.compile(
    r"(?<![\w./~+-])([\w@+-]+\.(?:md|py|yaml|yml|json|toml|js|css|sh|sql|txt|svg|png|log|db))"
    r"(?=$|[\s`):,;])",
    re.IGNORECASE,
)
_BRANCH_ONLY_PATHS = {
    # Historical artifact exists only in the named unmerged worker branch.
    "root-cause-plan.md",
}
_OPTIONAL_AGENT_CONFIG_PATHS = {
    # Example hierarchy path; projects need not have a .claude directory.
    ".claude/AGENTS.md",
}
_IGNORED_RUNTIME_EXAMPLES = {
    # git check-ignore can check the generated DB path even in a clean checkout without data/.
    "data/orchestra.db",
}


def check_kb_index(root: Path) -> None:
    """Every topic file must be listed once, with a description, inside ``kb/``.

    The root rules no longer carry the list — the platform injects it from
    ``kb/README.md`` into the system prompt (:func:`app.kb_index.kb_index_block`). This is
    what still catches a topic nobody indexed, which no agent would ever be shown.
    """
    missing = kb_topic_files(root) - kb_topic_index(root).keys()
    if missing:
        raise ValueError(f"KB topics missing from README: {', '.join(sorted(missing))}")


def _is_relative_reference(target: str) -> bool:
    parsed = urlsplit(target)
    return not parsed.scheme and not parsed.netloc and not target.startswith(("/", "~", "#"))


def _check_target(source: Path, target: str, root: Path, errors: set[str]) -> None:
    if not _is_relative_reference(target):
        return
    path = unquote(urlsplit(target).path)
    if not path:
        return
    resolved = (source.parent / path).resolve()
    if not resolved.exists():
        errors.add(f"{source.relative_to(root)}: {target}")


def check_documentation_links(root: Path) -> None:
    """Check Markdown links and relative file paths in agent-facing docs.

    Code spans that are absolute/home paths, Git revision:path specs, URLs, slash
    identifiers (MIME types, API routes, repository slugs, and branch names), or
    placeholders are not relative repository-file references.
    """
    sources = [root / "AGENTS.md", *sorted((root / ".orchestra" / "kb").glob("*.md"))]
    root_entries = {item.name for item in root.iterdir()}
    errors: set[str] = set()
    for source in sources:
        text = source.read_text(encoding="utf-8")
        text_without_fences = _FENCED_CODE.sub("", text)
        markdown_text = _CODE_SPAN.sub("", text_without_fences)
        for match in _MARKDOWN_LINK.finditer(markdown_text):
            target = match.group(1) or match.group(2)
            if target and _is_relative_reference(target):
                _check_target(source, target, root, errors)

        for line in text_without_fences.splitlines():
            for match in _CODE_SPAN.finditer(line):
                span = match.group(1).strip()
                if (span.startswith(("/", "~/")) or "git show " in span
                        or "<" in span or ">" in span or "](" in span):
                    continue
                candidates = set(_CODE_PATH.findall(span))
                candidates.update(_BARE_FILE.findall(span))
                for target in candidates:
                    if "/" not in target and "~/" in line:
                        continue
                    if target in (_BRANCH_ONLY_PATHS | _OPTIONAL_AGENT_CONFIG_PATHS
                                  | _IGNORED_RUNTIME_EXAMPLES):
                        continue
                    if re.match(r"^[\w.-]+\.[A-Za-z]{2,}/", target):
                        continue
                    path = (root / target).resolve()
                    root_relative = (target.startswith(("./", "../"))
                                     or target.split("/", 1)[0] in root_entries)
                    if (path.suffix.lower() not in _FILE_SUFFIXES
                            and not path.is_dir() and not root_relative):
                        continue
                    if not path.exists():
                        errors.add(f"{source.relative_to(root)}: `{target}`")
    if errors:
        raise ValueError("Broken relative references:\n  " + "\n  ".join(sorted(errors)))


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
    check_documentation_links(root)


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
