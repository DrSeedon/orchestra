#!/usr/bin/env bash
# Каждый файл с красными в полном прогоне — отдельным процессом pytest, только его красные узлы.
cd "$(dirname "$0")/../../.."
export PATH=$HOME/.local/bin:$PATH
out=.orchestra/tasks/V-624/${ISOLATE_OUT:-isolated.txt}; : > $out
for f in $(cut -d: -f1 .orchestra/tasks/V-624/failed-final.txt | sort -u); do
  nodes=$(grep "^$f::" .orchestra/tasks/V-624/failed-final.txt)
  res=$(timeout 600 uv run --frozen python -m pytest -q -p no:cacheprovider $nodes 2>&1 | grep -E '^[0-9]+ (passed|failed)|^=+ .*(passed|failed)' | tail -1)
  echo -e "$f\t$(echo "$nodes" | wc -l)\t$res" >> $out
done
echo DONE >> $out
