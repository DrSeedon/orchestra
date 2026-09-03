#!/usr/bin/env python3
"""Delivery check for the #462 forward-only policy activation ticket."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CANONICAL = ROOT / ".orchestra/pipelines/default/prompts/skills/codex-debate.md"
CODEX_NATIVE = ROOT / ".codex/skills/codex-debate/SKILL.md"
ANCHORS = (
    "review-coverage-v1",
    'mode="implementation"',
    'outcome="skipped"',
)


canonical = CANONICAL.read_text(encoding="utf-8")
native = CODEX_NATIVE.read_text(encoding="utf-8")
assert canonical == native, "T4 delivery: native Codex skill drifted from canonical owner"
missing = [anchor for anchor in ANCHORS if anchor not in canonical]
assert not missing, f"T4 delivery: review coverage anchors missing: {missing}"
print("review-coverage-v1 reaches canonical and native Codex skill")
