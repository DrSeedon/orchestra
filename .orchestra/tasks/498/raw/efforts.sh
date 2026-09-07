#!/bin/bash
# #498 row 2: which reasoning efforts gpt-6-astra actually accepts through the CLI.
# One probe per level; record exit code and the verbatim tail of the output.
cd /tmp/astra498/burn 2>/dev/null || cd /tmp
for e in none minimal low medium high xhigh max ultra bogus; do
  out=$(timeout 300 codex exec --skip-git-repo-check --ignore-user-config \
        --json -c "model_reasoning_effort=$e" -c approval_policy=never \
        -m gpt-6-astra "Reply with exactly: OK_$e" </dev/null 2>&1)
  rc=$?
  usage=$(printf '%s\n' "$out" | grep -o '"usage":{[^}]*}' | tail -1)
  last=$(printf '%s\n' "$out" | tail -1 | cut -c1-400)
  echo "### effort=$e rc=$rc"
  echo "usage: ${usage:-<none>}"
  echo "tail: $last"
  echo
done
echo EFFORTS_DONE
