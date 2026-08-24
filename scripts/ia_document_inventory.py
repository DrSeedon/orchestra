"""Deterministic inventory of document sources pinned to Git blobs."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


class DocumentInventoryError(ValueError):
    """Raised when a source inventory cannot be reproduced exactly."""


_ALIAS_NAMESPACE = uuid.UUID("31500000-0000-4000-8000-000000000007")
_PROJECT_ID = "orchestra"


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DocumentInventoryError("inventory is not canonical JSON") from exc


def _manifest_head(manifest: Mapping[str, Any]) -> str:
    body = copy.deepcopy(dict(manifest))
    body.pop("manifest_head", None)
    return "sha256:" + hashlib.sha256(_canonical_bytes(body)).hexdigest()


def _glob_regex(pattern: str) -> re.Pattern[str]:
    pieces: list[str] = ["^"]
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            pieces.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            pieces.append(".*")
            index += 2
        elif pattern[index] == "*":
            pieces.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            pieces.append("[^/]")
            index += 1
        else:
            pieces.append(re.escape(pattern[index]))
            index += 1
    pieces.append("$")
    return re.compile("".join(pieces))


def _classifiers(value: Any) -> list[tuple[str, list[re.Pattern[str]]]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise DocumentInventoryError("classifiers must be a sequence")
    result = []
    for classifier in value:
        if not isinstance(classifier, Mapping):
            raise DocumentInventoryError("each classifier must be an object")
        source_class = classifier.get("source_class")
        patterns = classifier.get("patterns")
        if not isinstance(source_class, str) or not source_class:
            raise DocumentInventoryError("classifier source_class must be nonempty")
        if not isinstance(patterns, Sequence) or isinstance(patterns, (str, bytes)) or not patterns:
            raise DocumentInventoryError("classifier patterns must be a nonempty sequence")
        result.append((source_class, [_glob_regex(str(pattern)) for pattern in patterns]))
    return result


def _git_tree(repository_root: Path, source_commit: str) -> tuple[str, dict[str, str]]:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", f"{source_commit}^{{commit}}"],
            cwd=repository_root,
            text=True,
            stderr=subprocess.PIPE,
        ).strip()
        raw = subprocess.check_output(
            ["git", "ls-tree", "-r", "-z", "--format=%(objectname)%x09%(path)", commit],
            cwd=repository_root,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise DocumentInventoryError(f"cannot read frozen Git tree {source_commit!r}") from exc
    tree: dict[str, str] = {}
    for item in raw.split(b"\0"):
        if not item:
            continue
        blob, path = item.split(b"\t", 1)
        tree[path.decode("utf-8")] = blob.decode("ascii")
    return commit, tree


def _git_blobs(repository_root: Path, blob_ids: Sequence[str]) -> list[bytes]:
    process = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=repository_root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = "".join(f"{blob}\n" for blob in blob_ids).encode("ascii")
    output, error = process.communicate(payload)
    if process.returncode != 0:
        raise DocumentInventoryError(
            f"cannot read frozen Git blobs: {error.decode('utf-8', errors='replace').strip()}"
        )
    values: list[bytes] = []
    offset = 0
    for expected in blob_ids:
        try:
            header_end = output.index(b"\n", offset)
        except ValueError as exc:
            raise DocumentInventoryError("truncated git cat-file response") from exc
        header = output[offset:header_end].decode("ascii").split()
        if len(header) != 3 or header[:2] != [expected, "blob"]:
            raise DocumentInventoryError(f"unexpected Git blob response for {expected}")
        size = int(header[2])
        start = header_end + 1
        end = start + size
        if output[end:end + 1] != b"\n":
            raise DocumentInventoryError(f"truncated Git blob {expected}")
        values.append(output[start:end])
        offset = end + 1
    if offset != len(output):
        raise DocumentInventoryError("unexpected trailing Git blob response")
    return values


def inventory_api(request: Mapping[str, Any]) -> Mapping[str, Any]:
    """Classify a frozen Git tree and return its deterministic typed inventory."""

    if not isinstance(request, Mapping) or request.get("operation") != "classify":
        raise DocumentInventoryError("inventory operation must be 'classify'")
    repository_root = Path(str(request.get("repository_root") or ""))
    source_commit = str(request.get("source_commit") or "")
    raw_classifiers = copy.deepcopy(request.get("classifiers"))
    classifiers = _classifiers(raw_classifiers)
    commit, tree = _git_tree(repository_root, source_commit)

    scoped: list[tuple[str, str, str]] = []
    for path, blob in tree.items():
        matches = [
            source_class
            for source_class, patterns in classifiers
            if any(pattern.fullmatch(path) for pattern in patterns)
        ]
        if len(matches) > 1:
            raise DocumentInventoryError(f"path is classified more than once: {path}")
        if matches:
            scoped.append((path, blob, matches[0]))
    scoped.sort()
    if not scoped:
        raise DocumentInventoryError("frozen inventory is empty")

    entries = []
    class_counts: dict[str, int] = {}
    contents = _git_blobs(repository_root, [blob for _, blob, _ in scoped])
    for (path, blob, source_class), content in zip(scoped, contents, strict=True):
        kind = "evidence" if source_class == "immutable_evidence_cold_archive" else "resources"
        alias_id = uuid.uuid5(_ALIAS_NAMESPACE, f"{commit}:{path}:{blob}")
        entries.append({
            "path": path,
            "source_class": source_class,
            "source_commit": commit,
            "git_blob": blob,
            "source_sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
            "size": len(content),
            "alias": f"orch://project/{_PROJECT_ID}/{kind}/{alias_id}",
        })
        class_counts[source_class] = class_counts.get(source_class, 0) + 1

    manifest = {
        "schema_version": 1,
        "project_id": _PROJECT_ID,
        "source_commit": commit,
        "classifiers": raw_classifiers,
        "class_counts": dict(sorted(class_counts.items())),
        "entries": entries,
    }
    manifest["manifest_head"] = _manifest_head(manifest)
    return manifest
