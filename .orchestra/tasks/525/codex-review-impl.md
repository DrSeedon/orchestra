<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Ну да, symlink — это, видимо, тоже «внутри репозитория», если смотреть только на строку пути 🙃

## Summary

Обнаружены два дефекта в изменённых проверках:

- target через symlink может указывать за пределы репозитория;
- claim-check пропускает некоторые чистые Markdown-конструкции без утверждения.

Заявленные тесты не запускались: окружению не хватает `python-dotenv`. Они также покрывают более узкий набор случаев, чем сами фиксы.

## Findings

- `blocking: scripts/check_kb_contract.py:325-327 — проверка containment не учитывает symlink и Windows drive-relative paths → разрешать target только после resolve(strict=True) и проверки через relative_to(repo.resolve())`

  `Path(target).is_absolute()` и проверка `..` не защищают от target вроде `inside.md`, если `inside.md` — symlink на файл вне репозитория. Такой файл проходит `is_file()`, после чего `openers[pointer]` помечает указатель покрытым. На Windows аналогично потенциально опасны drive-relative пути вроде `C:foo`, которые не являются `is_absolute()`.

- `suggestion: scripts/check_kb_contract.py:389-390 — stripping оставляет pure markup с буквами → обработать reference links, autolinks, HTML tags и корректные nested code spans`

  Например, `` `foo` `` уже удаляется, но `[a][b]`, `<http://x>`, `<b>` и `` ``foo`` `` сохраняют `\w` и проходят как claims, хотя человеческого утверждения там нет.

Тест `test_moved_to_target_must_stay_inside_the_repository` проверяет только absolute/traversal targets, а `test_a_head_made_only_of_markup_is_not_a_claim` — только inline code и inline links; symlink и перечисленные формы markup не покрыты. `test_a_claim_around_code_spans_still_passes` проверяет один положительный пример.

## Verdict

Есть один blocking-дефект и один suggestion. Исправления в текущем виде нельзя считать полностью корректными: gate всё ещё может закрыть внешний pointer через symlink и пропускает часть чистой разметки.

Пока gate проверяет не сам дом, а только адрес на конверте: symlink и HTML спокойно проходят внутрь.

## Round (2026-09-07T04:15:51Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Apparently the symlink was evicted, but the race condition kept its desk 😏

## Round 2

## Summary

- Containment finding: FIXED for ordinary symlinks, missing parents, repository-root symlinks, and root comparison.
- Stripper finding: FIXED for the previously identified markup forms.
- New issue: a TOCTOU race remains between `resolve()` and `is_file()`.

The pinned test suite passes: `67 passed`.

## Findings

- `blocking: scripts/check_kb_contract.py:327-331 — target can be swapped after resolve() and before is_file() → check file-ness on the resolved path`

  `resolved` may point inside the repository, then a concurrent process can replace `target` with a symlink to an external file before `(repo / target).is_file()` runs. The gate then records the pointer as covered even though the final target is outside the repository. Use `resolved.is_file()` after the containment check, avoiding a second traversal through the mutable original path.

No realistic false-positive claim was found from the new `_MARKUP_PATTERNS` ordering. Missing parents correctly fail `is_file()`, and the repository-root comparison is correct.

## Verdict

Both prior findings are closed, but the new containment implementation still has one blocking TOCTOU issue. The stripper changes look correct, and all 67 relevant tests pass.

The gate now checks the right address, then leaves the door unlocked for one filesystem tick.
