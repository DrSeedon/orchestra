# #236 frozen OpenRouter comparison

This directory freezes the candidate comparison before any inference request.  The
runner is copied to a scratch directory outside `/home/kesha/orchestra` and its
worktrees on Contabo.  It imports the production harness code read-only, but uses an
isolated SQLite database and per-run fixture directories.

## Candidates and order

The candidates are `stealth/ox-alpha`, `z-ai/glm-5.2:free`,
`nvidia/nemotron-3-ultra-550b-a55b:free`,
`nvidia/nemotron-3-super-120b-a12b:free`, and
`inclusionai/ling-3.0-flash:free`.  Each runs two repetitions of all three tasks.
Order is interleaved by task and repetition, with the second repetition reversed,
so a monotonic host-load trend cannot systematically favor one model.

## Tasks and graders

- `closed_edit`: repair a small registry filter.  Score is the fraction of six
  frozen `unittest` assertions that pass after the turn.
- `closed_trace`: inspect a decoy-heavy call graph and write `answer.json`.  Score is
  the fraction of four frozen exact fields that match.
- `open_audit`: audit a deliberately flawed budget/routing module.  The model chooses
  findings from eight preregistered categories (five real, three decoys).  Score is
  `2 * true_positives - false_positives`, clamped to 0..10.

Primary ranking metric: mean normalized task score.  Tie-breakers, in order:
completed tasks, fewer HTTP attempts per completed task, lower 429 rate, then lower
median task latency.  A model is eligible for closed work only if both closed tasks
score 1.0 in both repetitions.  It is eligible for the open/audit class only if
`open_audit >= 8/10` in both repetitions.  A single paid-cost observation or failed
free guard invalidates the remaining run; scores already collected stay evidence,
not approval.

## Free-only guard

Immediately before every `/chat/completions` attempt (including retries), the runner
fetches the exact current Models API row.  It permits the POST only when the exact ID
ends in `:free`, or when every currently declared price field is numeric zero.  Any
positive, malformed, or unknown price field fails closed.  Exact model IDs are used;
no `models` fallback list or paid fallback is sent.  Platform 429 stops that run
without retry; upstream 429 may use the production bounded retry.  A rolling limiter
allows at most 18 starts per 60 seconds and a global cap of 220 inference attempts.

The key is read from Contabo's live `.env` into process memory only.  It is never
copied, printed, placed in argv, or written to an artifact.  Raw artifacts contain
events, sanitized fixture outputs, price-guard rows, request/status counts, and
graders.  Both remote and local copies are scanned for credential-shaped strings
before commit.

