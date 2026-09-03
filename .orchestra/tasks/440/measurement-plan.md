# #440 measurement contract

Frozen cutoff: `2026-09-02T03:49:33.877143+00:00` (latest laptop `usage_snapshots.ts` at freeze).

## Q1 primary measurement

- Database: `/mnt/data/Projects/Python/orchestra/data/orchestra.db`, opened as
  `file:/mnt/data/Projects/Python/orchestra/data/orchestra.db?mode=ro`.
- Start: `kv['turn_usage_collector_started_at'] = 2026-07-26T04:48:33.960178+00:00`.
- Snapshot rows: `start <= usage_snapshots.ts <= cutoff`, ordered by `ts`.
- Pairing: every adjacent snapshot pair; keep a pair only when both five-hour values exist,
  elapsed time is at most 900 seconds, the right timestamp is before the left row's declared
  reset, and the rounded counter does not decrease.
- Token assignment: `turn_usage.runtime='claude'` and `left.ts < turn_usage.ts <= right.ts`.
  Time bounds are Python-generated ISO strings passed as SQL parameters; SQLite `datetime()` is
  not used.
- Model class comes only from `turn_usage.model`: literal `haiku`, `sonnet`, or `opus` in the
  lower-cased value. An unknown model invalidates the pair instead of inventing a rate.
- Credits are calculated row by row, then summed. Rates are exact fractions from the source:
  Haiku `2/15, 10/15`; Sonnet `6/15, 30/15`; Opus `10/15, 50/15`.
- Cache-write arm: `ceil((input_tokens + cache_create_tokens) * input_rate +
  output_tokens * output_rate)`. No-write arm: the same expression without
  `cache_create_tokens`. `cache_read_tokens` is zero-priced in both.
- Predicted movement: `100 * credits / 11_000_000` five-hour percentage points.
- A pair matches the rounded counter iff
  `abs(predicted_movement - (right_pct-left_pct)) <= 1.0`: two independently rounded endpoints
  leave a one-percentage-point-wide difference tolerance.
- Primary denominator: eligible pairs containing at least one assigned Claude `turn_usage` row.
  Secondary denominators: all eligible pairs (includes vacuous no-traffic pairs), positive observed
  movement, and observed movement at least 2 p.p.
- Report numerator/denominator for both cache-write arms, not only average error.

Post-freeze sensitivity (added after the first frozen run, not substituted for the primary): repeat
the active and `>=2 p.p.` summaries after excluding pairs whose right endpoint is 100%, because the
rounded counter is right-censored at its cap. Also report paired discordance (`write-only` versus
`no-write-only` matches); a larger unpaired total alone does not identify the cache-write rule.

## Q2 checks

- Model mix: compare exact model-rate credits with a counterfactual that prices every row as Opus;
  report row counts and credit delta.
- Reasoning: scan saved Claude transcript assistant usages and test
  `output_tokens_details.thinking_tokens <= output_tokens` per record; official provider docs are
  the semantic cross-check.
- Input/write sign: decompose predicted credits into fresh-input, cache-write, and output raw
  fractional components.
- Ceiling: compute the five-hour ceiling implied by `15.68 p.p./MTok` for pure Opus output, but
  do not call it measured without raw full-account interval data.
- Window identity: verify the source column and production mapping for `five_hour`/300 minutes.

## Q3 checks

- Count non-integer values in both quota tables.
- Search stored CLI transcripts/debug files for `rate_limit_event`, `unifiedWindows`, and
  `message_limit`.
- Inspect the production CLI/SDK schemas and Orchestra's event dispatch for whether an unrounded
  value can traverse the live stream and whether it is persisted.
- Reproduce the source's float-bucket fraction recovery on
  `0.16327272727272726 -> 449/2750`. A live account ceiling is reported only if actual stored
  unrounded samples exist; no provider call is made to create samples.

## Pre-freeze disclosure

An exploratory laptop query ran before this file was frozen. It was used to expose the vacuous
success rate from zero-traffic pairs and choose the active-pair primary denominator. Its counts are
not cited as final results; the frozen script/result is the evidence used in `research.md`.
