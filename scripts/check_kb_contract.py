#!/usr/bin/env python3
"""Validate only new or changed structured facts in project-local .orchestra/kb."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


FACT_PREFIX = "- `fact:"
FACT_RE = re.compile(r"^- `fact:([^`]+)` — .+")
KEY_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
HUNK_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@"
)
ANCHOR_RE = re.compile(r"`[^`]+`|«[^»]+»")
VALID_SECTIONS = {"Established", "Rejected", "Historical observations"}
VALID_RELATIONS = {
    "depends_on",
    "explains",
    "contradicts",
    "supersedes",
    "evidence_for",
    "related",
}
LINK_RE = re.compile(r" · links: `([^`]+)` → \[[^\]]+\]\(([^)]+)\)")
APPROVAL_RE = re.compile(r" · approved: `([^`#]+)#([^`]+)`")
SCHEMA_RENAMES = (
    ("\u0423\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d\u043e", "Established"),
    ("\u041e\u0442\u0432\u0435\u0440\u0433\u043d\u0443\u0442\u043e", "Rejected"),
    ("\u041f\u0440\u043e\u0431\u0435\u043b\u044b", "Gaps"),
    ("\u041e\u0422\u041e\u0417\u0412\u0410\u041d\u041e", "RETRACTED"),
    ("\u0438\u0441\u043a\u0430\u0442\u044c:", "search:"),
    ("\u0441\u0432\u044f\u0437\u0438:", "links:"),
)
LEGACY_SECTION_NAMES = {
    "\u0423\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d\u043e",
    "\u041e\u0442\u0432\u0435\u0440\u0433\u043d\u0443\u0442\u043e",
    "\u041f\u0440\u043e\u0431\u0435\u043b\u044b",
    "\u041e\u0422\u041e\u0417\u0412\u0410\u041d\u041e",
}


@dataclass(frozen=True)
class DiffLine:
    relative_path: str
    line_number: int
    text: str


def _strip_git_prefix(raw: str) -> str:
    path = raw.split("\t", 1)[0].strip()
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def _range_count(raw: str | None) -> int:
    return int(raw) if raw is not None else 1


def parse_changed_lines(diff_text: str) -> tuple[list[DiffLine], list[DiffLine]]:
    added: list[DiffLine] = []
    deleted: list[DiffLine] = []
    current_path: str | None = None
    old_path: str | None = None
    old_line: int | None = None
    new_line: int | None = None
    old_remaining = 0
    new_remaining = 0
    for raw in diff_text.splitlines():
        if old_line is not None and new_line is not None:
            if raw.startswith("\\"):
                continue
            if raw.startswith("+"):
                if current_path is not None:
                    added.append(DiffLine(current_path, new_line, raw[1:]))
                new_line += 1
                new_remaining -= 1
            elif raw.startswith("-"):
                if current_path is not None:
                    deleted.append(DiffLine(current_path, old_line, raw[1:]))
                old_line += 1
                old_remaining -= 1
            else:
                old_line += 1
                new_line += 1
                old_remaining -= 1
                new_remaining -= 1
            if old_remaining == 0 and new_remaining == 0:
                old_line = None
                new_line = None
            continue
        if raw.startswith("--- "):
            path = _strip_git_prefix(raw[4:])
            old_path = None if path == "/dev/null" else path
            continue
        if raw.startswith("+++ "):
            path = _strip_git_prefix(raw[4:])
            current_path = old_path if path == "/dev/null" else path
            continue
        match = HUNK_RE.match(raw)
        if match:
            old_line = int(match.group(1))
            old_remaining = _range_count(match.group(2))
            new_line = int(match.group(3))
            new_remaining = _range_count(match.group(4))
    return added, deleted


def resolve_changed_path(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute():
        raise ValueError("changed path is absolute")
    if ".." in candidate.parts:
        raise ValueError("changed path contains '..' traversal")
    if candidate.parts[:1] == (".orchestra",):
        if candidate.parts[:2] != (".orchestra", "kb"):
            raise ValueError("changed path is outside .orchestra/kb")
        candidate = Path(*candidate.parts[2:])
    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("changed path resolves outside project-local KB") from exc
    if resolved.suffix != ".md":
        raise ValueError("changed KB path must be a Markdown file")
    if not resolved.is_file():
        raise ValueError("changed KB file does not exist")
    return resolved


def _sections(lines: list[str]) -> dict[int, str | None]:
    current: str | None = None
    result: dict[int, str | None] = {}
    for number, line in enumerate(lines, start=1):
        if line.startswith("## "):
            current = line[3:].strip()
        result[number] = current
    return result


def _fact_key(line: str) -> str | None:
    match = FACT_RE.match(line)
    return match.group(1) if match else None


def _schema_rename_only(old: str, new: str) -> bool:
    renamed = old
    for source, target in SCHEMA_RENAMES:
        renamed = renamed.replace(source, target)
    return renamed == new


def _repo_root(root: Path) -> Path:
    resolved = root.resolve()
    if resolved.name != "kb" or resolved.parent.name != ".orchestra":
        raise ValueError("KB root must be the project-local .orchestra/kb directory")
    return resolved.parent.parent


def validate_link(root: Path, source: Path, line_number: int, line: str, key: str) -> list[str]:
    prefix = f"{source}:{line_number}"
    errors: list[str] = []
    if "candidate-link" in line:
        errors.append(f"{prefix}: candidate-link belongs in .orchestra/tasks, not canonical KB")

    has_link = " · links:" in line
    has_approval = " · approved:" in line
    if not has_link:
        if has_approval:
            errors.append(f"{prefix}: approved receipt has no canonical связи field")
        return errors

    matches = LINK_RE.findall(line)
    if len(matches) != 1 or line.count(" · links:") != 1:
        errors.append(f"{prefix}: связи must contain exactly one typed Markdown target")
        return errors
    relation, raw_target = matches[0]
    if relation not in VALID_RELATIONS:
        errors.append(f"{prefix}: unknown link relation '{relation}'")

    target_part = Path(raw_target)
    target: Path | None = None
    if target_part.is_absolute():
        errors.append(f"{prefix}: link target must not be absolute")
    elif ".." in target_part.parts:
        errors.append(f"{prefix}: link target must not contain '..' traversal")
    else:
        resolved_root = root.resolve()
        candidate = (source.parent / target_part).resolve()
        try:
            candidate.relative_to(resolved_root)
        except ValueError:
            errors.append(f"{prefix}: link target resolves outside project-local KB")
        else:
            if candidate == source.resolve():
                errors.append(f"{prefix}: self-link is not allowed")
            elif candidate.suffix != ".md":
                errors.append(f"{prefix}: link target must be a Markdown topic")
            elif not candidate.is_file():
                errors.append(f"{prefix}: link target does not exist: {raw_target}")
            else:
                target = candidate

    approval = APPROVAL_RE.search(line)
    if approval is None:
        errors.append(f"{prefix}: canonical связи requires an approved plan/ticket anchor")
        return errors
    raw_receipt, anchor = approval.groups()
    receipt_part = Path(raw_receipt)
    receipt_parts = receipt_part.parts
    if (
        receipt_part.is_absolute()
        or ".." in receipt_part.parts
        or len(receipt_parts) != 4
        or receipt_parts[:2] != (".orchestra", "tasks")
        or re.fullmatch(r"[1-9][0-9]*", receipt_parts[2]) is None
        or receipt_parts[3] != "plan.md"
    ):
        errors.append(
            f"{prefix}: approval receipt must be a .orchestra/tasks/<numeric-id>/plan.md anchor"
        )
        return errors
    try:
        repo_root = _repo_root(root)
    except ValueError as exc:
        errors.append(f"{prefix}: {exc}")
        return errors
    receipt = (repo_root / receipt_part).resolve()
    tasks_root = (repo_root / ".orchestra/tasks").resolve()
    try:
        receipt.relative_to(tasks_root)
    except ValueError:
        errors.append(f"{prefix}: approval receipt resolves outside .orchestra/tasks")
        return errors
    if not receipt.is_file():
        errors.append(f"{prefix}: approval receipt does not exist: {raw_receipt}")
        return errors

    receipt_match = re.search(
        rf'<a id="{re.escape(anchor)}"></a>\s*'
        r"source `fact:([^`]+)`;\s*relation `([^`]+)`;\s*target `([^`]+)`\.",
        receipt.read_text(encoding="utf-8"),
    )
    if receipt_match is None:
        errors.append(f"{prefix}: approval anchor '{anchor}' was not found")
        return errors
    receipt_source, receipt_relation, receipt_target = receipt_match.groups()
    expected_target = (
        target.relative_to(repo_root).as_posix() if target is not None else None
    )
    if (
        receipt_source != key
        or receipt_relation != relation
        or expected_target is None
        or receipt_target != expected_target
    ):
        errors.append(
            f"{prefix}: approval tuple does not match source fact, relation, and target"
        )
    return errors


def validate_fact_line(
    root: Path,
    path: Path,
    line_number: int,
    line: str,
    section: str | None,
    key_counts: dict[str, int],
) -> list[str]:
    errors: list[str] = []
    prefix = f"{path}:{line_number}"
    match = FACT_RE.match(line)
    if not match:
        return [f"{prefix}: malformed fact; expected '- `fact:kebab-key` — claim'"]
    key = match.group(1)
    if not KEY_RE.fullmatch(key):
        errors.append(f"{prefix}: fact key must be lowercase kebab-case")
    if key_counts.get(key, 0) != 1:
        errors.append(f"{prefix}: duplicate fact key fact:{key}")
    if section not in VALID_SECTIONS:
        errors.append(
            f"{prefix}: structured facts belong only in Established, Rejected or Historical observations"
        )
    search_field = re.search(r"(?:^|[ ·;])search:", line)
    if search_field is None:
        errors.append(f"{prefix}: missing 'search:' literal anchors")
    else:
        anchors_field = line[search_field.end():]
        for delimiter in (" · evidence:", " · links:", " · approved:"):
            anchors_field = anchors_field.split(delimiter, 1)[0]
        anchors = ANCHOR_RE.findall(anchors_field)
        if not 1 <= len(anchors) <= 6:
            errors.append(f"{prefix}: 'search:' requires 1–6 quoted literal anchors")
    if " · evidence:" not in line:
        errors.append(f"{prefix}: missing inline evidence")
    else:
        evidence = line.split(" · evidence:", 1)[1]
        evidence = evidence.split(" · ", 1)[0].strip()
        if not evidence:
            errors.append(f"{prefix}: inline evidence must not be empty")
    errors.extend(validate_link(root, path, line_number, line, key))
    return errors


def validate(root: Path, diff_path: Path) -> list[str]:
    if not root.is_dir():
        return [f"{root}: KB root is not a directory"]
    if not diff_path.is_file():
        return [f"{diff_path}: unified diff does not exist"]

    errors: list[str] = []
    added_lines, deleted_lines = parse_changed_lines(
        diff_path.read_text(encoding="utf-8")
    )
    replacement_keys: dict[str, set[str]] = {}
    for changed in added_lines:
        key = _fact_key(changed.text)
        if key is not None:
            replacement_keys.setdefault(changed.relative_path, set()).add(key)
    for removed in deleted_lines:
        try:
            path = resolve_changed_path(root, removed.relative_path)
        except ValueError as exc:
            errors.append(f"{removed.relative_path}:{removed.line_number}: {exc}")
            continue
        if removed.text.startswith(FACT_PREFIX):
            key = _fact_key(removed.text)
            if key is None or key not in replacement_keys.get(removed.relative_path, set()):
                label = f"fact:{key}" if key is not None else "structured fact"
                errors.append(
                    f"{path}:{removed.line_number}: deleted {label} must be replaced "
                    "by a valid fact with the same stable key"
                )

    cache: dict[Path, tuple[list[str], dict[int, str | None], dict[str, int]]] = {}
    for added in added_lines:
        try:
            path = resolve_changed_path(root, added.relative_path)
        except ValueError as exc:
            errors.append(f"{added.relative_path}:{added.line_number}: {exc}")
            continue
        if path not in cache:
            lines = path.read_text(encoding="utf-8").splitlines()
            counts: dict[str, int] = {}
            for current in lines:
                key = _fact_key(current)
                if key is not None:
                    counts[key] = counts.get(key, 0) + 1
            cache[path] = (lines, _sections(lines), counts)
        lines, sections, counts = cache[path]
        if added.line_number > len(lines) or lines[added.line_number - 1] != added.text:
            errors.append(
                f"{path}:{added.line_number}: diff line does not match the current KB file"
            )
            continue
        if "candidate-link" in added.text and not added.text.startswith(FACT_PREFIX):
            errors.append(
                f"{path}:{added.line_number}: candidate-link belongs in .orchestra/tasks, not canonical KB"
            )
        if added.text.startswith("## ") and added.text[3:].strip() in LEGACY_SECTION_NAMES:
            errors.append(
                f"{path}:{added.line_number}: legacy KB section heading; use English schema names"
            )
        if added.text.startswith(FACT_PREFIX):
            key = _fact_key(added.text)
            if key is not None and any(
                removed.relative_path == added.relative_path
                and _fact_key(removed.text) == key
                and _schema_rename_only(removed.text, added.text)
                for removed in deleted_lines
            ):
                continue
            errors.extend(
                validate_fact_line(
                    root,
                    path,
                    added.line_number,
                    added.text,
                    sections.get(added.line_number),
                    counts,
                )
            )
        elif re.match(r"^\s+(?:search:|evidence:|links:|approved:)", added.text):
            errors.append(
                f"{path}:{added.line_number}: fact fields must stay on the fact bullet line"
            )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--diff", required=True, type=Path)
    args = parser.parse_args(argv)
    errors = validate(args.root, args.diff)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("KB contract OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
