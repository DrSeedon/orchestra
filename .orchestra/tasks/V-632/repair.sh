#!/usr/bin/env bash
# V-632: finish the cog-second-brain layout migration and resolve the stale preserve journal.
# Usage: repair.sh <repo> <journal-backup-dir>. Preconditions are asserted; any mismatch aborts.
set -euo pipefail
R=$1; BACKUP=$2
STASH=fb3d4dacea5555353b666e47d0a4e9a27d1770a8
SOURCE_HEAD=2b0dff6d9927819fc49008878565a4c7cbd3abb3
cd "$R"

test "$(git rev-parse HEAD)" = 91dd892e3ad6d7d0fdf60f24db67557a2ecb4213
test -z "$(git diff --cached --name-only)"
test "$(git ls-files docs/tasks | sort | tr '\n' ' ')" = "docs/tasks/V-1/retro.md docs/tasks/V-19/retro.md docs/tasks/V-2/retro.md "
test -z "$(find docs/tasks -type f ! -name retro.md)"

for t in V-1 V-2 V-19; do
  test ! -e ".orchestra/tasks/$t/retro.md"
  git mv "docs/tasks/$t/retro.md" ".orchestra/tasks/$t/retro.md"
done
# git mv leaves the emptied directories; rmdir refuses anything non-empty.
rmdir docs/tasks/V-1 docs/tasks/V-2 docs/tasks/V-19 docs/tasks
test ! -e docs/tasks
test "$(git diff --cached --name-status -M | sort | tr '\t\n' '  ')" = "R100 docs/tasks/V-1/retro.md .orchestra/tasks/V-1/retro.md R100 docs/tasks/V-19/retro.md .orchestra/tasks/V-19/retro.md R100 docs/tasks/V-2/retro.md .orchestra/tasks/V-2/retro.md "
git commit -q -m "Orchestra: migrate project state to .orchestra"

# The stash's only content is an unstaged 2-line AGENTS.md edit; restore it as unstaged work.
git diff "$SOURCE_HEAD" "$STASH" -- AGENTS.md | git apply --check
git diff "$SOURCE_HEAD" "$STASH" -- AGENTS.md | git apply

J=$(git rev-parse --git-path orchestra-layout-preserve.json)
mkdir -p "$BACKUP"
mv -n "$J" "$BACKUP/orchestra-layout-preserve.json"
test ! -e "$J"
git log -1 --format='%H %an %s'
git status --short
