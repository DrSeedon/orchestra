<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

APPROVED. The failure path matches the immutable oracle: it probes identity before compensation, deletes only a guarded legacy row, records debt best-effort, and raises instead of returning a legacy DTO. Exact quote from app/tm.py: "Remove only the untouched legacy half of a failed shadow create."

> ⚠ Codex usage unaccounted: ValueError: Codex completed turn reported zero tokens
