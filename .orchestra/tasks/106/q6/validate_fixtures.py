"""Fail-at-build checks for fixture self-consistency.

Q5 shipped a fixture that demanded "Read docs/runbook-state.md" while forbidding
the claim "file was read". It was satisfiable only by refusing the assigned work,
and it survived two rounds and $54 because the contradiction was visible only to
a judge. These checks move that class of defect to build time.
"""

import re


_ACTION_VERBS = (
    "read",
    "check",
    "commit",
    "deploy",
    "test",
    "write",
    "edit",
    "create",
    "delete",
    "run",
    "replay",
    "fetch",
    "sign",
    "upload",
)

_PATH = re.compile(r"[\w./-]+\.[A-Za-z0-9]+")


def _verbs(text: str) -> set[str]:
    words = set(re.findall(r"[a-z]+", text.lower()))
    return {verb for verb in _ACTION_VERBS if verb in words}


def _paths(text: str) -> set[str]:
    return {match.group(0) for match in _PATH.finditer(text)}


def contradiction_errors(fixture: dict) -> list[str]:
    """A pending action must not be prohibited by the fixture's own forbidden claims."""
    errors = []
    for action in fixture.get("pending_actions", []):
        action_verbs = _verbs(action)
        action_paths = _paths(action)
        for claim in fixture.get("forbidden_claims", []):
            shared_verbs = action_verbs & _verbs(claim)
            if not shared_verbs:
                continue
            claim_paths = _paths(claim)
            # Same verb on the same file (or on an unqualified claim) means doing
            # the assigned work makes the forbidden claim true.
            if claim_paths and action_paths and not (claim_paths & action_paths):
                continue
            errors.append(
                f"pending action {action!r} is prohibited by forbidden claim "
                f"{claim!r} (shared action: {sorted(shared_verbs)})"
            )
    return errors


def seeded_file_errors(fixture: dict) -> list[str]:
    """Pending actions and expectations must not reference unseeded files."""
    errors = []
    seeded = set(fixture.get("seeded_files", {}))
    transcript_paths = _paths(fixture.get("transcript", ""))
    for action in fixture.get("pending_actions", []):
        if not _verbs(action) & {"read", "check"}:
            continue
        for path in _paths(action):
            if path in seeded or path in transcript_paths:
                continue
            errors.append(
                f"pending action {action!r} requires reading {path!r}, "
                "which the fixture does not seed"
            )
    for path in fixture.get("expected_files", {}):
        if path not in seeded and path not in transcript_paths:
            errors.append(
                f"expected_files names {path!r}, which is neither seeded nor "
                "mentioned in the transcript"
            )
    return errors


def anchor_errors(fixture: dict, exact_total: int = 8) -> list[str]:
    """Holdout fixtures must carry exactly the declared anchor budget."""
    if fixture.get("split") != "holdout":
        return []
    errors = []
    count = sum(len(group) for group in fixture.get("exact_anchors", {}).values())
    if count != exact_total:
        errors.append(f"has {count} exact anchors, expected {exact_total}")
    if len(fixture.get("recent_messages", [])) != 3:
        errors.append(
            f"has {len(fixture.get('recent_messages', []))} recent messages, expected 3"
        )
    if len(fixture.get("pending_actions", [])) != 1:
        errors.append(
            f"has {len(fixture.get('pending_actions', []))} pending actions, expected 1"
        )
    return errors


def gap_errors(fixture: dict) -> list[str]:
    """A declared unmatched-tool id must actually be unmatched in the transcript."""
    errors = []
    transcript = fixture.get("transcript", "")
    for gap_id in fixture.get("expected_gap_ids", []):
        if f"[TOOL_RESULT id={gap_id}]" in transcript:
            errors.append(
                f"expected_gap_ids names {gap_id!r} but the transcript pairs it "
                "with a TOOL_RESULT"
            )
        if f"id={gap_id} " not in transcript:
            errors.append(f"expected_gap_ids names {gap_id!r}, absent from transcript")
    return errors


def secret_errors(fixture: dict) -> list[str]:
    """Every declared fake secret must appear in the transcript it is seeded into."""
    errors = []
    haystack = fixture.get("transcript", "") + "".join(
        fixture.get("seeded_files", {}).values()
    )
    for secret in fixture.get("fake_secrets", []):
        if secret not in haystack:
            errors.append(
                f"fake secret {secret!r} appears in neither transcript nor seeded files"
            )
    return errors


def validate(fixture: dict) -> list[str]:
    return [
        *contradiction_errors(fixture),
        *seeded_file_errors(fixture),
        *anchor_errors(fixture),
        *gap_errors(fixture),
        *secret_errors(fixture),
    ]


def validate_all(fixtures: list[dict]) -> dict[str, list[str]]:
    return {
        fixture["id"]: errors
        for fixture in fixtures
        if (errors := validate(fixture))
    }
