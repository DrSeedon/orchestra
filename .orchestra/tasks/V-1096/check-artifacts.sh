#!/usr/bin/env bash
# Run from the supplied repository root; performs artifact-only, offline checks.
set -euo pipefail
task_dir=.orchestra/tasks/V-1096
manifest="$task_dir/source-manifest.json"
facts="$task_dir/facts.json"

jq -e '
  .repositories | length == 4 and all(.[];
    (.sha | test("^[0-9a-f]{40}$")) and .tree_truncated == false)
' "$manifest" > /dev/null
jq -e --slurpfile manifest "$manifest" '
  (.facts | length == 61) and
  ([.facts[].id] == [range(1;62) | "R" + (if . < 10 then "0" else "" end) + tostring]) and
  ([.facts[].source.line] == $manifest[0].skill_inventory.bullet_lines) and
  all(.facts[];
    . as $f |
    $f.source.commit == $manifest[0].repositories[0].sha and
    $f.source.url == ("https://github.com/unclebob/ub-mode/blob/" + $f.source.commit + "/SKILL.md#L" + ($f.source.line | tostring)) and
    ([.rule,.mechanism,.claim,.toolrequirements_supportedlanguages,.actualenforcement,
      .failuremode,.Orchestraequivalent.rules,.Orchestraequivalent.code,
      .Orchestraequivalent.tests,.gap,.adoptioncostconditions,.license] | all(.[]; length > 0)))
' "$facts" > /dev/null
printf 'PASS: 61 unique rule IDs and exact upstream bullet-line inventory; all required fields present.\n'

jq -e '
  . as $m |
  ($m.sources | length == 43) and
  all($m.sources[];
    . as $s |
    ($s.sha256 | test("^[0-9a-f]{64}$")) and
    ($s.git_blob_sha1 | test("^[0-9a-f]{40}$")) and
    $s.line_count > 0 and
    ($s.url | contains("/blob/" + $s.commit + "/" + $s.path)) and
    any($m.repositories[]; .repo == $s.repository and .sha == $s.commit) and
    (if $s.consulted_ranges == "all" then true else
       all($s.consulted_ranges[]; .[0] >= 1 and .[1] <= $s.line_count and .[0] <= .[1])
     end))
' "$manifest" > /dev/null
printf 'PASS: 43 consulted sources have pinned identity, hashes and valid read ranges.\n'

jq -r '.local_context[] | "\(.sha256)  \(.path)"' "$manifest" | sha256sum -c
printf 'PASS: supplied local context files unchanged.\n'

awk -F '|' '/^\| R[0-9][0-9] / { n++; if (NF != 13) bad++ }
  END { print "Inventory table rows=" n ", malformed=" (bad+0); exit(n != 61 || bad > 0) }' "$task_dir/report.md"

jq -Rs -e --slurpfile manifest "$manifest" '
  [scan("https://github[.]com/unclebob/[^)[:space:]]+")] |
  length > 0 and all(.[];
    capture("^https://github[.]com/unclebob/(?<repo>[^/]+)/(blob|commit)/(?<sha>[0-9a-f]{40})(/|$)") as $p |
    any($manifest[0].repositories[]; .repo == $p.repo and .sha == $p.sha))
' "$task_dir/report.md" > /dev/null
printf 'PASS: all upstream GitHub report citations use one of the four pinned commits.\n'

if rg -l -- '(AKIA|ASIA)[A-Z0-9]{16}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9_-]{24,}|[0-9]{6,12}:[A-Za-z0-9_-]{30,}|-----BEGIN ([A-Z ]+ )?PRIVATE KEY-----' \
  "$task_dir/report.md" "$facts" "$manifest" "$task_dir/notes.md"; then
  printf 'FAIL: secret-shaped material requires inspection.\n'
  exit 1
fi
printf 'PASS: no supported credential-shaped material in publication artifacts (heuristic, not proof).\n'
if test -e .git; then
  printf 'Git metadata present; manual status/commit verification remains necessary.\n'
else
  printf 'Git metadata absent: commit/clean cannot be verified in broker copy; platform owns import.\n'
fi
printf 'All artifact checks passed. Product/companion pytest and runtime smoke were not run.\n'

