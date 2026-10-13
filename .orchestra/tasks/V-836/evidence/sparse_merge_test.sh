set -u
R=/home/kesha/orchestra
echo "fs: $(findmnt -no FSTYPE /)"
for r in /home/kesha/orchestra /home/kesha/projects/seedon /home/kesha/projects/dnd-game-master; do echo "refs $(basename $r): $(git -C $r for-each-ref | wc -l) branches: $(git -C $r for-each-ref refs/heads | wc -l)"; done
D=/tmp/v836-sm; trash "$D" 2>/dev/null || true
git clone -q -s --no-checkout $R $D; cd $D
git config user.email t@t; git config user.name t
git sparse-checkout init --no-cone >/dev/null 2>&1
printf '/*\n!/.orchestra/tasks/\n/.orchestra/kb/\n' > .git/info/sparse-checkout
git checkout -q -b main-sp origin/main 2>/dev/null || git checkout -q -b main-sp HEAD
echo "files on disk: $(find . -path ./.git -prune -o -type f -print | wc -l); tasks dir exists: $([ -d .orchestra/tasks ] && echo yes || echo no)"
# worker branch edits file OUTSIDE sparse set + file inside
git checkout -q -b w1
mkdir -p .orchestra/tasks/ZZ; echo hi > .orchestra/tasks/ZZ/report.md; echo x >> README.md 2>/dev/null || echo x > README.md
git add -A 2>&1 | head -1 | sed "s#^#git add -A (no --sparse): #"; git add --sparse -A; git commit -q -m "w1: out-of-cone + in-cone"
git checkout -q main-sp
git merge --squash w1 >/dev/null 2>&1 && echo "merge --squash in sparse worktree: OK" || echo "merge --squash: FAIL"
git commit -q -m "squash w1" && echo "commit OK"
git ls-tree -r HEAD --name-only | grep -c "ZZ/report.md" | sed 's/^/out-of-cone file in main tree: /'
echo "ZZ on disk after merge: $([ -e .orchestra/tasks/ZZ/report.md ] && echo yes || echo no)"
# conflicting change outside cone in 2 branches
git checkout -q -b w2 HEAD~1; echo a > .orchestra/tasks/ZZ/report.md 2>/dev/null || { mkdir -p .orchestra/tasks/ZZ; echo a > .orchestra/tasks/ZZ/report.md; }; git add --sparse -f -A; git commit -q -m w2 || true
git checkout -q main-sp; git merge --squash w2 >/dev/null 2>&1 && echo "conflicting merge: no conflict reported" || { echo "conflicting merge: conflict reported"; git status --short | head -3; }
cd /; trash "$D"; trash-rm "v836-sm"
