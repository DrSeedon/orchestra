#!/bin/bash
# usage: setup.sh name srcrepo  "extra negation lines"
set -e
n=$1; src=$2; shift 2
cd /tmp/v821
for kind in full sparse; do
  [ -d $n-$kind ] && continue
  git clone -q -s --no-checkout $src $n-$kind
done
cd $n-full
s=$(date +%s.%N); git checkout -q main 2>&1 | tail -2; e=$(date +%s.%N); echo "$n full checkout $(echo "$e-$s"|bc) s"
cd ../$n-sparse
git sparse-checkout init --no-cone
printf '/*\n!/.orchestra/tasks/\n' > .git/info/sparse-checkout
for x in "$@"; do echo "$x" >> .git/info/sparse-checkout; done
cat .git/info/sparse-checkout
s=$(date +%s.%N); git checkout -q main 2>&1 | tail -2; e=$(date +%s.%N); echo "$n sparse checkout $(echo "$e-$s"|bc) s"
for kind in full sparse; do echo "$n $kind: $(du -sm --apparent-size /tmp/v821/$n-$kind --exclude=.git | cut -f1) MB working tree, du real $(du -sm --exclude=.git /tmp/v821/$n-$kind|cut -f1) MB"; done
