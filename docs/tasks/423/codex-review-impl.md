<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Git умеет даже конфликтный путь слегка соврать о самом себе 😏 В целом AC выполнен для обычных имён файлов, но есть один P2-дефект.

## Summary

Conflict paths reach raw and normalized results; `CONFLICT` and resolution action override `NO_COMMITS_MERGED`; clean empty squash retains the old code.

Verified:

- `tests/test_merge_conflict_report_423.py` — `2 passed`
- `tests/test_merge_reason_preservation_416.py` — `3 passed`
- `tests/test_merge_operations.py tests/test_workspace.py` — `153 passed`

The acceptance test uses only temporary Git repositories; `data/orchestra.db` remained absent before and after. No files were modified.

## Findings

### [P2] suggestion: Preserve exact conflict paths with NUL output

**File:** `app/workspace.py:1630-1638` | **Confidence:** 0.99

The fallback uses `git diff --name-only` with `.strip().splitlines()`. Git C-quotes valid filenames containing newlines or other special characters, so a conflict on `line\nbreak.txt` is reported as `"line\nbreak.txt"` instead of the actual path, and that incorrect value reaches both raw and normalized results. Use `--name-only -z` and split on `\0`, matching the existing precheck path.

## Verdict

**Overall Correctness:** ❌ Incorrect | **Confidence:** 0.97

No blocking crash or data-loss issue found, but exact conflict-path preservation is incomplete for valid Git filenames in the post-merge failure path. Всё работает, пока файл не решил быть `line\nbreak.txt`.
