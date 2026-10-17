# item-08

Commit under review (in /home/kesha/orchestra, read-only): `208c7fcae99b53232394a1bf7382f3db90284937`
Subject / date:
#180: #180: _run_exec rejects blind review artifacts
2026-08-14

The diff reviewed is `git -C /home/kesha/orchestra show 208c7fcae99b53232394a1bf7382f3db90284937 -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Reviewed the complete diff from `44b74f771889ccafbb113cf1274e415af5605050` to `ced2214fdffaa66617b18b9e44e69aa3ad73053f`. The change rejects successful background runs when the artifact lacks a `## Verdict` section or contains known blind-review markers.

## Findings (blocking/suggestion/question)

- **Suggestion — marker matching can reject a valid review.** [`app/bg_jobs.py`](app/bg_jobs.py:43) searches the entire artifact and captured process output for literal `bwrap:` and related strings. A review that mentions one of those strings as evidence or in a quoted example will be marked blind even if it contains a valid verdict. Consider detecting execution-failure markers in a narrower context, or distinguishing error output from review content.

## Verdict

NEEDS WORK
