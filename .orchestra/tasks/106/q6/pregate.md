# #106 Q6 — pre-gate design and fix verification

Purpose: prove the three approved fixes work **before** committing ~$26 to a full
confirmatory round. This produces no verdict and no gate decision.

## The three fixes

### 1. Prompt — unsupported negatives (the real Q5 defect)

`q6/candidates.py`, appended to the evidence rule:

> Do not assert the negative either: absence of a tool event means the outcome is
> unknown, not that the action did not happen. Write `no evidence of X` rather
> than `X did not happen`. A measured empty diff supports only `not modified`; it
> never supports `not read`.

Q5 line 42 forbade only the *positive* claim, which is why
`reversal-canary` produced "No files were read or modified" twice.

### 2. Harness — live tool events reach the judge (Cause A)

`run_evaluation.py`: `--output-format json` → `stream-json --verbose`, plus a new
`parse_stream()` that extracts the final result **and** live `tool_use` /
`tool_result` pairs. `candidates.py::_event_ledger` takes `live_events` and
appends them to the transcript-derived events.

**Verified on a real model run** (`q6-confirm-targeted-promotion`,
`num_turns=3`, 4 live events captured):

```
TOOL EVENTS
[ASSISTANT TOOL_USE id=toolu_01WkGSZ… name=Read input={"file_path": "…/docs/continuity-state.md"}]
[TOOL_RESULT id=toolu_01WkGSZ…] 1→# Continuity state …
[ASSISTANT TOOL_USE id=toolu_01GXCMW… name=Edit input={…}]
[TOOL_RESULT id=toolu_01GXCMW…] The file … has been updated successfully
```

In Q5 this ledger read `no structured tool events` and the Read was unprovable.

Preserved behaviour, checked explicitly:
- redaction still applies to live events — neither a fixture-specific
  `sk-FAKE-…` nor a generic `ghp_FAKE_…` survives into the ledger;
- an unmatched `tool_use` still emits `[GAP unmatched tool event id=…: result absent]`.

### 3. Corpus — contradictory fixtures removed

Dropped `q5-confirm-file-unchanged-no-read` **and** `q5-dev-unchanged-no-read`
(the dev twin has the identical flaw): each forbids claiming a read while
assigning a read as its pending action, so it is passable only by refusing the
assigned work. Corpus is now **2 dev / 21 holdout**, namespaced `q6-*`, with all
`Q5` branding removed from tool ids and fake secrets.

`test_q6.py`: **8 passed** (`/tmp/pytest-q6.log`).

## Pre-gate run (awaiting your go)

Targets both fixed causes, not just the prompt:

| Slice | Purpose | Outputs |
|---|---|---|
| `reversal-canary` ×3 reps ×2 variants | does the prompt fix remove unsupported *negatives*? | 6 |
| `targeted-promotion` ×3 ×2 | do live tool events reach the judge on a read+write path? | 6 |
| `tool-gap-archive` ×3 ×2 | does the GAP marker still fire (no regression)? | 6 |
| judge, 3 batches | do the flags actually disappear? | — |

Cost at measured Q5 unit rates: 18 × $0.1176 + 3 × $0.1733 = **$2.64**.

Pass condition, fixed in advance: **zero** false unchanged-file-action flags
against the candidate across all 18 outputs, and the live-tool ledger non-empty
wherever the model used a tool. Anything else means the defect is deeper and a
full Q6 should not be funded yet.

## Still open — not decided here

- **Q6 fixtures are Q5 content renamed**, minus the two removed. They were
  already used for candidate selection, so they are *not* a fresh holdout. A real
  confirmatory Q6 needs newly authored fixtures; the pre-gate does not, because
  it tests mechanism, not effect size.
- **G7 stays UNDECIDED** without the Codex judge (available 2026-08-08). Recorded
  as a limitation, not closed single-handed.
- **G5 remains absolute.** Not softened.
