"""Resolution of immutable task evidence used by promoted facts."""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.ia.namespace import NamespaceError, parse_uri


class EvidenceResolutionError(ValueError):
    """Raised when fact provenance cannot be tied to canonical task evidence."""


_PROVENANCE_FIELDS = {
    "task_id",
    "evidence_uri",
    "path",
    "anchor",
    "git_commit",
    "measurement",
}
_GIT_COMMIT = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceResolutionError(f"cannot read canonical evidence: {path}") from exc
    if not isinstance(value, dict):
        raise EvidenceResolutionError(f"canonical evidence is not an object: {path}")
    return value


class EvidenceResolver:
    """Resolve exact provenance entries against a T2 ``TaskStore``."""

    def __init__(self, task_store: Any) -> None:
        root = getattr(task_store, "canonical_root", None)
        if root is None:
            raise EvidenceResolutionError("task store has no canonical evidence root")
        self._root = Path(root)

    def resolve(self, provenance: Sequence[Mapping[str, Any]]) -> Sequence[Mapping[str, Any]]:
        """Return detached evidence records after exact identity/source validation."""

        if (
            not isinstance(provenance, Sequence)
            or isinstance(provenance, (str, bytes))
            or not provenance
        ):
            raise EvidenceResolutionError("promoted facts require immutable provenance")

        resolved: list[dict[str, Any]] = []
        project_id: str | None = None
        for raw in provenance:
            if not isinstance(raw, Mapping) or set(raw) != _PROVENANCE_FIELDS:
                raise EvidenceResolutionError("provenance does not match the exact fact contract")
            if any(not isinstance(raw[name], str) or not raw[name] for name in _PROVENANCE_FIELDS):
                raise EvidenceResolutionError("provenance fields must be non-empty strings")
            if _GIT_COMMIT.fullmatch(raw["git_commit"]) is None:
                raise EvidenceResolutionError("provenance git commit is not canonical")
            try:
                address = parse_uri(raw["evidence_uri"])
            except (NamespaceError, TypeError) as exc:
                raise EvidenceResolutionError("provenance evidence URI is invalid") from exc
            if address.record_type != "task.evidence" or address.task_id != raw["task_id"]:
                raise EvidenceResolutionError("provenance crosses record or task identity")
            if project_id is not None and address.project_id != project_id:
                raise EvidenceResolutionError("provenance crosses project identity")
            project_id = address.project_id

            evidence_path = (
                self._root
                / "projects"
                / address.project_id
                / "tasks"
                / str(address.task_id)
                / "evidence"
                / f"{address.stable_id}.json"
            )
            evidence = _read_object(evidence_path)
            expected = {
                "record_type": "task.evidence",
                "stable_id": address.stable_id,
                "uri": raw["evidence_uri"],
                "task_id": raw["task_id"],
                "project_id": address.project_id,
                "canonical_path": raw["path"],
                "anchor": raw["anchor"],
                "git_commit": raw["git_commit"],
            }
            if any(evidence.get(name) != value for name, value in expected.items()):
                raise EvidenceResolutionError("provenance does not match canonical evidence")
            if _SHA256.fullmatch(str(evidence.get("content_sha256") or "")) is None:
                raise EvidenceResolutionError("canonical evidence has no content digest")

            state_path = evidence_path.parents[1] / "state.json"
            state = _read_object(state_path)
            if (
                state.get("stable_id") != raw["task_id"]
                or state.get("project_id") != address.project_id
                or raw["evidence_uri"] not in (state.get("evidence_refs") or [])
            ):
                raise EvidenceResolutionError("task state does not own the evidence reference")
            resolved.append(copy.deepcopy(evidence))
        return resolved
