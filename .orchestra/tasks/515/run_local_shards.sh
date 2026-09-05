#!/usr/bin/env bash
# Локальный прогон ТОЙ ЖЕ раскладки, что в .github/workflows/ci.yml — чтобы отделить
# «падает везде» от «падает только на раннере». `timeout` обязателен: 05.09 шард с
# tests/test_frontend.py завис на 2 часа и утащил с собой осиротевший uvicorn.
set -u
cd "$(dirname "$0")/../../.." || exit 1
out=".orchestra/tasks/515/raw/local-shards"
mkdir -p "$out"
for s in 0 1 2 3 4 5; do
  mapfile -t files < <(git ls-files 'tests/test_*.py' | sort | awk -v s="$s" -v n=6 '(NR - 1) % n == s')
  timeout --kill-after=60 900 /usr/bin/time -v -o "$out/shard-$s.time" \
    uv run pytest -q -rf --timeout=30 "${files[@]}" > "$out/shard-$s.log" 2>&1
  printf '%s\n' "$?" > "$out/shard-$s.rc"
  printf 'SHARD=%s RC=%s %s\n' "$s" "$(cat "$out/shard-$s.rc")" "$(tail -n 1 "$out/shard-$s.log")"
done
