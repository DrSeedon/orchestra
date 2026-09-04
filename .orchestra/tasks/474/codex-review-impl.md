<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Apparently the digest learned to ignore unrelated `main` commits, but not untracked files 🙃 The pinned diff contains one blocking review-coverage hole; no files were edited.

## Findings

- **blocking [P1] — Bind coverage to untracked production paths** — `app/review_coverage.py:75-80, 142-148`

  `production_diff_sha256` hashes only committed `git diff` output, which omits untracked files. Since `changed_paths` includes untracked `app/` and `scripts/` files, adding `app/new.py` after review leaves both digests unchanged. With the same target SHA, the first SQL branch still matches the receipt, authorizing unreviewed production content. The `<>''` guard only protects the second branch and does not fix this same-target case. Include current production-path/content state in the review identity or reject target-bound matches when paths differ.

- **suggestion [P2] — Restrict timeout-plugin detection to pytest usage errors** — `app/merge_test_gate.py:393-401`

  The new branch matches arbitrary output text without checking pytest’s usage-error exit code. A real failing test that emits `unrecognized arguments ... --timeout` would be reported as `INCONCLUSIVE` instead of `FAILED`. Require the pytest usage-error status (`4`) and an anchored diagnostic.

## Verdict

**Overall correctness:** ❌ Incorrect — confidence: 0.99. The committed-content twin tests are non-vacuous, but they miss the same-target plus untracked-production-file scenario. Сейчас это охранник, который сверяет хэш паспорта и не замечает второго человека в той же куртке.

## Round (2026-09-04T11:40:23Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Round 2

## Summary

Раунд 1: оба замечания FIXED. Severity correction согласен: untracked-файл давал неверное admission-решение, но показанный dirty-worktree guard не позволяет ему дойти до executor. 🙃

Новые проверки нашли два blocking-дефекта: initial admission всё ещё может упасть на неразрешимом target ref, а skip receipt может вставить `NULL` в новый `NOT NULL` столбец.

## Findings

- **blocking [P1] — STILL BROKEN: guard initial target resolution** — `app/merge_operations.py:1040-1046`

  Новый `try` защищает `_target_head` только в `_revalidate_review_coverage`. Initial `_prepare_admission_snapshot` по-прежнему вызывает `_target_head(...)` напрямую, поэтому удалённая ветка или переехавший worktree во время initial admission всё ещё выбрасывает `ValueError` вместо structured refusal. Добавленный тест проверяет только revalidation seam.

- **blocking [P1] — NEW BUG: default the new field in skip receipts** — `app/db.py:3231-3232`

  `review_receipt_record_skip` теперь включает `production_diff_sha256` в `stable`, но строит `values` через `receipt.get(key)` без нормализации. Любой skip payload без нового ключа передаст `NULL` в `review_receipts.production_diff_sha256`, вызвав `NOT NULL constraint failed`; replay такого receipt также будет считаться конфликтом. `review_receipt_create` и `reserve` этот случай обрабатывают, skip writer — нет.

- **suggestion [P2] — Canonicalize snapshot paths identically** — `app/review_coverage.py:65-67`

  На обычном clean tree JSON совпадает: обе стороны сортируют пути и используют одинаковые `json.dumps` options. Но `production_paths()` нормализует `\` в `/`, а `production_snapshot()` сохраняет имя Git-файла как есть; чистый репозиторий с literal backslash в `app/` или `scripts/` path получит false block из-за разных `production_paths_json`.

## Verdict

**Overall correctness:** ❌ Incorrect — confidence: 0.98.

Fix 3b сохраняет прежнее поведение для непустого pinned admission и не меняет legacy acceptance path. Но blocking-дефекты остаются: один вход всё ещё падает до fail-closed helper, а skip-полоса может разбиться о `NOT NULL`. Теперь у гейта правильный паспорт, но один вход без охраны, а skip-очередь кидает имя в коробку с запретом на пустоту.

## Round (2026-09-04T11:48:10Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Round 3

## Summary

Round-2 findings: all FIXED. The stable-tuple removal is safe because `production_snapshot_sha256` already commits `target_sha` and the exact `raw`; distinct `production_diff_sha256` values would require a SHA-256 collision.

The new refusal branch is correctly fail-closed, and pinned admissions retain their previous behavior. One backward-compatibility edge remains.

## Findings

- **suggestion [P2] — Preserve legacy path serialization** — `app/review_coverage.py:65-69`

  New receipts normalize paths through `production_paths()`, while old receipts retain the previous raw Git spelling. A clean repository containing a literal backslash in an `app/` or `scripts/` filename would therefore compare `app/foo\bar.py` with `app/foo/bar.py` and be falsely blocked. Ordinary paths are unaffected; normalize stored JSON during comparison or migration.

## Verdict

**Overall Correctness:** ✅ Correct — confidence: 0.96.

The two round-2 blockers are closed. The tests are non-vacuous: they assert relevant preconditions and mutation outcomes. No blocking issue remains.

`USAGE_ERROR_EXIT_CODE = 4  # pytest EXIT_USAGEERROR`

Система почти закончила проверять билеты; теперь только старый билет с обратным слэшем требует отдельного кондуктора.
