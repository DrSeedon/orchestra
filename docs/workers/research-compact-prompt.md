# Worker memory

- Claude CLI `429 You've hit your monthly spend limit` with
  `duration_api_ms=0` and cost `$0` can mean the 5h window is exhausted while
  supplemental capacity is disabled, not a payment limit. Before classifying
  it, check `/api/usage` → `anthropic.five_hour` and `extra_usage`.

- A preregistered analysis script must never be edited to work around a missing
  input. When one of two judges was unavailable, `analyze_results.py` refused to
  run. The right move is to **import** its bootstrap/CI functions from a separate
  script (identical seeds and math, lock hashes stay intact) and report the
  gate as UNDECIDED — not to patch the locked file. Re-verify all locked source
  hashes both before AND after the run.

- Before implementing an assigned fix for a judge/eval finding, open the RAW
  flagged outputs and the fixture. In #106 Q5, 3 of 5 "hallucinated read" flags
  were TRUE statements: the harness seeded the file on disk and passed
  `--tools Read`, but the ledger shown to judges is built only from the fixture
  transcript, so a live tool call is structurally invisible. Fixing the prompt
  would have "fixed" correct behaviour. An eval that cannot represent a true
  action will fail any candidate that performs it.

- Probe a "tool is unavailable" claim with the EXACT flags the code uses.
  `codex exec` from `/tmp` failed on a trust check (looks like a quota error but
  is not); rerun with the real flags gave the verbatim quota message and reset
  date. Cheap, and it separates "blocked" from "misconfigured".
