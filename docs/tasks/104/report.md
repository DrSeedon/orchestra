# Task #104 — Telegram tool-result image deduplication

## Result

`stream_logs` now treats a truthy `_ImageSubmission` as ownership transfer to the
existing isolated image lane:

- the tool command remains visible immediately;
- an accepted Bash/Grep/Glob/Read result image suppresses the duplicate text in
  the primary Telegram chat;
- a render or admission rejection keeps the previous textual result fallback;
- a configured mirror still receives the textual result;
- a later media-edit failure keeps the already-sent image marker and uses the
  existing `image_lost` accounting.

The special branch for a `Read` tool returning an original image was not changed.

## Files

- `app/tg_bridge.py` — branch on `_ImageSubmission` acceptance without bypassing
  mirror delivery.
- `tests/test_tg_bridge.py` — deterministic accepted/rejected stream tests,
  including mirror assertions and no wall-clock thresholds.
- `docs/tasks/104/codex-review-impl.md` — two-round implementation review.

## Verification

Command:

```text
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_tg_bridge.py -q
```

Result:

```text
142 passed in 3.00s
```

The focused tests also cover the pre-existing late-failure contract:
`test_failed_photo_edit_leaves_marker_and_counts_loss`.

## Adversarial review

Codex round 1 found that an early `continue` suppressed mirror results. The code
and tests were changed so both accepted and rejected submissions reach
`_mirror_send`.

Codex also questioned suppressing text before asynchronous media completion.
That finding was resolved by the explicit task contract: accepted handoff leaves
the pre-sent marker on later edit failure, while waiting for completion would
block stream progress and adding a second fallback path was expressly excluded.
Round 2 verdict: **APPROVED**, no new findings.

## Breaking changes

None. The only intended visible change is removal of the duplicate primary-chat
text result when its image replacement has been accepted.
