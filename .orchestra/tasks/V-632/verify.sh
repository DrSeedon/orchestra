#!/usr/bin/env bash
# V-632: byte-level check that nothing pinned before the repair was lost. Usage: verify.sh <repo>
set -euo pipefail
R=$1; cd "$R"
STASH=fb3d4dacea5555353b666e47d0a4e9a27d1770a8
SOURCE_HEAD=2b0dff6d9927819fc49008878565a4c7cbd3abb3
fail=0
# 1. Every dirty/untracked file recorded before the repair keeps its bytes (AGENTS.md checked below).
git cat-file blob refs/preserve/V-632/hashes-before | sed -n '/^# worktree/,/^# AGENTS/p' | grep -v '^#' > /tmp/v632-dirty.sha
sha256sum --quiet -c /tmp/v632-dirty.sha || fail=1
# 2. The migrated retro.md files are byte-identical to the pre-repair tracked blobs.
for t in V-1 V-2 V-19; do
  a=$(git rev-parse "refs/preserve/V-632/head-before:docs/tasks/$t/retro.md")
  b=$(git hash-object ".orchestra/tasks/$t/retro.md"); c=$(git rev-parse "HEAD:.orchestra/tasks/$t/retro.md")
  [ "$a" = "$b" ] && [ "$a" = "$c" ] || { echo "retro $t mismatch"; fail=1; }
done
# 3. AGENTS.md = committed HEAD version + exactly the stash hunk (both versions' content survives).
diff <(git diff "$SOURCE_HEAD" "$STASH" -- AGENTS.md | grep '^[-+][^-+]') \
     <(git diff HEAD -- AGENTS.md | grep '^[-+][^-+]') || { echo "AGENTS.md delta differs from stash"; fail=1; }
# 4. Only the migration changed HEAD's tree; the preserved objects are all still reachable.
[ "$(git diff --name-only --no-renames refs/preserve/V-632/head-before HEAD | sort | tr '\n' ' ')" = ".orchestra/tasks/V-1/retro.md .orchestra/tasks/V-19/retro.md .orchestra/tasks/V-2/retro.md docs/tasks/V-1/retro.md docs/tasks/V-19/retro.md docs/tasks/V-2/retro.md " ] || { echo "unexpected tree change"; fail=1; }
git merge-base --is-ancestor refs/preserve/V-632/head-before HEAD || { echo "history rewritten"; fail=1; }
for r in stash-fb3d4d stash-76ea1e worktree-before preserve-journal hashes-before; do
  git cat-file -e "refs/preserve/V-632/$r" || { echo "missing ref $r"; fail=1; }
done
[ "$(git stash list --format=%H | tr '\n' ' ')" = "$STASH 76ea1e77fc10ef1f71186190c3beca1d5cd83e86 " ] || echo "note: stash list now: $(git stash list --format=%H | tr '\n' ' ')"
[ $fail = 0 ] && echo VERIFY_OK || { echo VERIFY_FAIL; exit 1; }
