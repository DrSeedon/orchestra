## Summary

Да, соседний номер задачи опять отказался становиться доказательством происхождения. 🕵️

Рекомендация **`1–8 → пропустить task link` подтверждена fail-closed**. Ни один из восьми случаев не содержит точного доказательства связи с Orchestra Task Manager `#N`.

Проверка возможных совпадений:

- `#86` — UI-аналитика расходов, а не форензика эффективности Sol.
- `#81` — механизм auto-inject памяти, а не наполнение личного файла.
- `#84` — исследование обучения на коррекциях пользователя; тематически близко к self-improvement, но это другой intent.
- `#111` и `#114` в назначении №8 описывают исходный инцидент, а не выполняемую задачу.
- `#115` — отдельный research ручных merge.
- `#116` и `#117` созданы после `6926fea`; для `9ff4a7f` задача `#116` уже существовала, но её intent — freshness/typed errors, тогда как commit меняет rule triage и требования `report_bug`.

Физическая интеграция также подтверждена: случаи 1–3 имеют идентичные patch-id источникам; 4–5 содержат ожидаемые source blobs после разрешения конфликтов; №6 совпадает деревом с `99e5e5c`; module-части №7–8 совпадают с `8181ec1` и `7d6b1f0`; `9ff4a7f` имеет patch-id `35f0229`, создан fresh-branch cherry-pick и влит `ff-only`.

## Findings

### suggestion: Сузить утверждение об исходных назначениях subscription-strategy

В [manual-mapping-review.md:5](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/manual-mapping-review.md:5) отсутствие numeric ID заявлено в том числе для «исходного назначения работы», но среди приведённых SQLite evidence нет assignment row для `research-subscription`. Для №4–5 доказаны отсутствие номера в source/target subjects, session/branch и Task Manager matches, однако содержимое первоначального назначения frozen evidence не показывает. Это не меняет `skip`, но формулировку следует сузить либо добавить точную строку назначения.

### suggestion: Указать полные source chains для prompt-engineer squash

[manual-mapping-review.md:20](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/manual-mapping-review.md:20) и [manual-mapping-review.md:21](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/manual-mapping-review.md:21) называют только implementation commits:

- `c277632` также включает `8646a13` — обновление `prompt-engineer.md`; его tree полностью совпадает с target.
- `6926fea` также включает `0bddcfd` — следующее обновление личного файла; оба изменённых target blobs совпадают с source chain.

`8181ec1` и `7d6b1f0` указаны верно для module-изменений, но не объясняют весь squash и сами по себе не объяснили бы `add/add`. Дополнительные commits тоже ненумерованные, поэтому вывод о task link сохраняется.

### suggestion: Исправить порядковый номер кандидата

В [manual-mapping-review.md:37](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/manual-mapping-review.md:37) `9ff4a7f` назван «33-м recovery candidate». Frozen manifest содержит 32 entries, но только 31 recovery candidate; один объект имеет disposition `evidence_only_non_integration` ([recovery-input.json:3](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/recovery-input.json:3)). Поэтому `9ff4a7f` будет **33-й manifest entry, но 32-й recovery candidate**.

### question: Уточнить критерий включения `9ff4a7f`

Вопрос о включении [manual-mapping-review.md:27](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/manual-mapping-review.md:27) оправдан: manual integration и target SHA доказаны, task link отсутствует. Но frozen classifier требует явной интеграции named worker branch/worktree. Log `372616` вычисляет `B` для `prompt-engineer`, однако не выводит и не использует его — cherry-pick выполняется непосредственно по `35f0229`. Перед положительным решением стоит либо зафиксировать source-worker lineage, либо явно разрешить exact-source-SHA integrations в recovery policy.

## Verdict

**APPROVE** для операторского решения **`1–8 → skip`**: точного evidence для Orchestra Task Manager `#N` нет, а тематическая или временная близость недостаточна.

Для `9ff4a7f` безопасный ответ пока: **task link не добавлять; включение в recovery manifest решить отдельно после уточнения classifier, называя его 32-м candidate / 33-й entry**. Иначе получится классика: номер нашли рядом и решили, что багаж наш. 🎒

## Round (2026-08-01T10:06:26Z)

## Re-review status

Файл снова оказался untracked, потому что обычного diff было бы слишком просто. 🙃 Проверен полный текущий текст.

- **FIXED** — subscription-strategy больше не приписан утраченному assignment.
- **FIXED** — для №7–8 указаны полные source chains.
- **FIXED** — `9ff4a7f` корректно назван 33-й entry / 32-м recovery candidate.
- **FIXED** — lineage через inbox `372506` сформулирована точно, без ложного утверждения о worker-session storage.
- **FIXED** — операторский вопрос явно расширяет classifier на fail-closed exact-SHA chain.

Рекомендация **`1–8 → skip`** остаётся подтверждённой.

## New findings

Нет.

## Verdict

**APPROVE.** Документ безопасно обосновывает `1–8 → пропустить`, а вопрос по `9ff4a7f` теперь точный и не подменяет provenance тематической близостью. На этот раз номера сидят каждый на своём стуле. 🪑
