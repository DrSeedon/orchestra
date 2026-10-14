#!/bin/bash
# Before/after browser replays for V-831. "before" temporarily restores the committed JS.
set -u
cd /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-dashboard
S=.orchestra/tasks/V-831/stream-timing
BK=$(mktemp -d)
cp app/static/js/chat.js app/static/js/live-activity.js "$BK/"
git show HEAD~1:app/static/js/chat.js > app/static/js/chat.js
git show HEAD~1:app/static/js/live-activity.js > app/static/js/live-activity.js
PYTHONPATH=. timeout 200 uv run --frozen python $S/browser_replay.py before $S/cli_opus_write_prodenv.jsonl $S/cli_opus.jsonl
cp "$BK/chat.js" "$BK/live-activity.js" app/static/js/
git diff --stat app/static/js/
PYTHONPATH=. timeout 200 uv run --frozen python $S/browser_replay.py after-js-only $S/cli_opus_write_prodenv.jsonl $S/cli_opus.jsonl
PYTHONPATH=. timeout 200 uv run --frozen python $S/browser_replay.py after $S/cli_opus_write_prodenv_fgts.jsonl $S/cli_opus.jsonl
