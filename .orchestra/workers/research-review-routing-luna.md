# Personal memory — research-review-routing-luna

- When `codex_review` background execution fails but `/tmp/codex_review_*.jsonl` contains substantive reviewer text, preserve it as recovered evidence, mark the verdict uncompleted, apply only verifiable findings, and do not spend a duplicate round.
- For SQLite observed-use reports, record the WAL-safe backup watermark plus `MAX(id)`/`MAX(ts)` alongside counts so later reruns cannot silently change the denominator.
