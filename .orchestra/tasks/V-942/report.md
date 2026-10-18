# V-942 — Telegram bot token in public origin

Token values are never printed; identifiers below are the first 6 hex chars of sha256 of the token.

## Done
- `.orchestra/tasks/V-919/v919_after.txt` (1 occurrence) and `v919_restart1118.txt` (2) now carry `<2 digits>********:***REDACTED-V942***`; the rest of the evidence is unchanged.
- `scripts/secret_scan.py`: rule `telegram-bot` = `[0-9]{8,10}:` + exactly 35 chars of `[A-Za-z0-9_-]`, left boundary "not a digit" (so `bot<id>:<payload>` in an API URL matches), right boundary "not payload alphabet". No placeholder layer (the format is the filter).
- `tests/test_secret_commit_gate.py`: positive case in `SECRETS` (generated, not literal), negative cases `test_telegram_mention_or_wrong_shape_passes` (`bot<id>:`, `bot1234567890: AAAA`, `<token>` placeholder, 34/36-char payload, 7-digit id, `12:34:56`). Without the rule the positive case fails (no finding). 37 passed with `uv run --frozen python -m pytest tests/test_secret_commit_gate.py -q`.

## Full history scan (branch `main`, 3752 commits, 33 825 distinct added/modified blobs, every path of every commit incl. merge diffs)
Telegram-token-shaped values found, 3 occurrences in 2 files, all in one commit, one distinct value (hash `ee7326` = current TG_BRIDGE_TOKEN):

| commit | path | hash |
|---|---|---|
| f25848e99 | .orchestra/tasks/V-919/v919_restart1118.txt | ee7326 |
| f25848e99 | .orchestra/tasks/V-919/v919_after.txt | ee7326 |

No other Telegram-shaped value exists in main history.

## Where the current TG_BRIDGE_TOKEN appears
- History of main: only f25848e99 (checked both as full token and as the payload part alone: same two files, nothing else).
- Working tree (this worktree): after masking, only the git-ignored `.env` copy (`git check-ignore` → ignored, not tracked).
- Not checked: other branches/refs, other worktrees, `data/`.

## Not done (by the boundaries)
History is not rewritten: f25848e99 still contains the token in public origin. The token must be revoked/rotated via BotFather; masking HEAD does not remove it from history.
