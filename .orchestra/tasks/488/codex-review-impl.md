<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

Naturally, the quarantine filters an honest instruction more reliably than hostile formatting. 🙃

Reviewed the pinned diff `c8a6fd7...4963725` and the five requested files only. Repository identity correctly resolves through the common Git directory. The focused test suite passed: `21 passed`.

Risk routing treated this as a high-risk review/receipt-gate surface. Four findings remain, including one blocking quarantine bypass.

## Findings

### blocking [P1] Quarantine reserved fields regardless of Markdown prefix

**File:** [app/mcp_stdio.py:3548](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/project-context-file/app/mcp_stdio.py:3548) | **Confidence:** 0.99

The regex accepts only bare or `-`/`*` bullets. Caller-controlled forms such as `> - Scale: tiny prototype` and `1. Users: one user` survive `_task_review_context()` unchanged. Because caller calibration appears after the trusted foundation, the reviewed subject can still present conflicting reserved fields and weaken severity calibration—the exact bypass this change intends to prevent. Canonicalize Markdown container prefixes before matching, or recognize every supported list/blockquote form.

### suggestion [P2] Preserve legitimate instructions mentioning project context

**File:** [app/mcp_stdio.py:3693](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/project-context-file/app/mcp_stdio.py:3693) | **Confidence:** 1.00

Every line containing `PROJECT CONTEXT` anywhere is discarded. For example, `Review how PROJECT CONTEXT warnings are surfaced.` becomes `(no additional task instructions supplied)`. This silently removes valid review requirements in every mode. Match only actual context headings rather than an unanchored substring.

### suggestion [P2] Record the implementation subject’s pinned HEAD

**File:** [app/mcp_stdio.py:3636](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/project-context-file/app/mcp_stdio.py:3636) | **Confidence:** 0.96

Implementation mode pins `subject["worker_head"]` for the diff, but provenance independently resolves the current `HEAD` afterward. If the worker commits between those operations, the receipt claims a different reviewed HEAD from the SHA actually passed to `git diff`. Use the already-pinned `worker_head` for implementation provenance.

### suggestion [P2] Preserve a digest for invalid-but-readable sources

**File:** [app/mcp_stdio.py:3674](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/project-context-file/app/mcp_stdio.py:3674) | **Confidence:** 0.98

`source_sha256` is assigned only after successful validation. A readable file with malformed TOML, an unknown key, or an invalid value therefore produces a warning receipt with an empty digest, contradicting the documented provenance contract and preventing exact identification of the rejected bytes. Hash `raw` immediately after `git show`; only genuinely missing sources should lack a digest.

## Verdict

**NEEDS WORK — blocking finding present.**

Common-directory identity, pinned-base loading, explicit unknown warnings, and mode command construction otherwise look compatible. The quarantine must be closed before relying on repository-owned calibration as a review-integrity boundary.

At present it’s a quarantine where numbered guests enter freely while the inspector’s note gets confiscated. 🚧

## Round (2026-09-04T15:28:14Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

Well, all four fixes actually stayed fixed—reckless competence. 🔍

- **FIXED:** blockquote, numbered-list, task-list, and heading-form reserved fields are quarantined.
- **FIXED:** ordinary instructions mentioning `PROJECT CONTEXT` survive.
- **FIXED:** implementation provenance uses the pinned `worker_head`.
- **FIXED:** invalid-but-readable context retains its SHA-256 digest.

Repository identity resolves through `/mnt/data/Projects/Python/orchestra/.git`. Focused verification passed: `22 passed in 2.91s`.

## Findings

### suggestion [P2] Recognize complete Markdown heading syntax

**File:** [app/mcp_stdio.py:3554](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/project-context-file/app/mcp_stdio.py:3554) | **Confidence:** 0.99

The heading matcher still preserves valid forms where formatting closes after the colon or an ATX heading has closing hashes: `**PROJECT CONTEXT:**` and `## PROJECT CONTEXT ##`. This does not let reserved field values through, so it is non-blocking, but it contradicts the contract that actual project-context headings are quarantined and leaves inconsistent prompt framing.

## Verdict

**APPROVED with one non-blocking suggestion.**

The pinned-base loader, repository identity, warning behavior, receipt provenance, caller-field quarantine, and all three `codex_review` modes remain compatible. Risk-based review calibration kept the remaining Markdown mismatch non-blocking because the reserved values themselves are still removed.

Evidence from the changed implementation:

> `provenance["source_sha256"] = hashlib.sha256(raw).hexdigest()`

The lock works; one label above the door is still wearing a fake moustache. 🥸
