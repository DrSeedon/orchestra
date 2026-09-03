<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Миграция решила сначала снести стены, а потом проложить проводку — смело, но для продакшена так себе 😏

## Summary

План пока не одобряю: есть блокеры в порядке T3/T2, миграции живых worktree, защите dirty work и доказательствах сохранности данных.

## Findings

### Blocking

1. **[P1] T3 физически удаляет старые пути раньше T2**

   После T3 старые roots исчезают, но runtime consumers переводятся только в T2, который явно зависит от T3. Перезапуск между этими этапами оставит `pipeline`, memory и knowledge на старых путях; fallback запрещён. Это ломает startup. Даже тест порядка использует только `source.find`, поэтому может пройти на мёртвом коде или комментарии.

   **File:** [plan.md:173-178](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/docs/tasks/430/plan.md:173), [plan.md:194-211](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/docs/tasks/430/plan.md:194), [test:116-121](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/tests/test_orchestra_layout_430.py:116)

2. **[P1] Fleet migration не защищена от гонки с live/resumable worktree**

   T1 должен писать через `git mv` и commit во все live/resumable worktrees, но план не задаёт write barrier, lock или иной способ удержать worktree неизменным между dirty-check и commit. Агент может начать запись после проверки, а чистый worker branch получит отдельный migration commit и конфликт при последующем merge.

   **File:** [plan.md:173-178](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/docs/tasks/430/plan.md:173)

3. **[P1] T5 не может быть green до T3**

   T5 требует, чтобы `docs/` уже содержал ровно пять файлов, но именно T3 выполняет перенос `docs/kb`, `docs/tasks`, `docs/workers`, `docs/archive` и остальных директорий. При заявленном порядке T5 → T3 собственный `t5_` shard неизбежно падает либо T5 начинает владеть частью T3, создавая пересечение ответственности.

   **File:** [plan.md:72-76](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/docs/tasks/430/plan.md:72), [plan.md:227-232](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/docs/tasks/430/plan.md:227), [test:238-245](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/tests/test_orchestra_layout_430.py:238)

4. **[P1] Dirty-work test не покрывает dirty managed files**

   Тест меняет только root `README.md`. Миграция может всё ещё без отказа переместить или закоммитить изменённый `docs/kb/<file>` либо untracked-файл внутри managed directory, что нарушает требование «dirty auto mode mutates nothing». Нужен отдельный immutable-safe regression test для tracked и untracked изменений внутри переносимого root.

   **File:** [plan.md:175-177](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/docs/tasks/430/plan.md:175), [test:106-114](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/tests/test_orchestra_layout_430.py:106)

5. **[P1] Repair procedure проверяется только по подстрокам**

   Контракт требует абсолютный repository path, классы ошибки и одну исполняемую команду, заканчивающуюся `--repair <absolute-repository>`. `_assert_repair_message` проверяет лишь наличие кода, имени скрипта и `--repair`; неправильный или неполный путь пройдёт, а команда никогда не исполняется.

   **File:** [plan.md:162-170](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/docs/tasks/430/plan.md:162), [test:55-59](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/tests/test_orchestra_layout_430.py:55)

6. **[P1] Move receipt является самоподтверждаемым**

   T3-тест читает готовый `move-receipt.json` и доверяет `mismatches=[]` и `checked_files >= 16000`; `verify_orchestra_move.py` не запускается и ни один SHA/размер конкретного файла не сверяется. Можно сгенерировать правдоподобный receipt без preservation proof.

   **File:** [plan.md:203-210](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/docs/tasks/430/plan.md:203), [test:190-198](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/tests/test_orchestra_layout_430.py:190)

7. **[P1] Historical evidence проверяется агрегатами, а не полным набором bindings**

   Требуется проверить все 12 759 привязок, но oracle принимает любое значение `historical_path_blob_sha_checked >= 12759`. Он не доказывает, что проверены именно ожидаемые записи, и не проверяет напрямую неизменность каждого `source_path`/blob/SHA.

   **File:** [plan.md:203-205](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/docs/tasks/430/plan.md:203), [test:258-263](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/tests/test_orchestra_layout_430.py:258)

### Suggestion

8. **[P2] Prompt-last не имеет машинного гейта**

   T4 требует отдельный commit после runtime/location changes, но acceptance не проверяет topology коммитов. Prompt можно изменить раньше и всё равно получить green функциональные тесты. Добавьте проверку commit order по frozen refs либо отдельный release receipt.

   **File:** [plan.md:215-223](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/docs/tasks/430/plan.md:215)

## Verdict

**NOT APPROVED.** Граф ацикличен, но его порядок не deploy-safe, а ключевые гарантии восстановления и сохранности сейчас подтверждаются доверенными артефактами и слабыми агрегатными проверками.

У переезда уже есть опись коробок, но грузчики всё ещё могут снести стену до проводки — почти идеальный ремонт.

## Round (2026-09-01T18:25:27Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Переезд стал аккуратнее, но часть доказательств всё ещё проверяет опись, которую сам переезд и составил 😏

## Summary

Re-review только `plan.md` и immutable oracle. Статусы предыдущих находок:

| Finding | Status | Evidence |
|---|---|---|
| P1.1 atomic move/runtime | **STILL BROKEN** — порядок исправлен, граница commit не доказана | [plan.md:246-249](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/docs/tasks/430/plan.md:246), [test:409-423](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/tests/test_orchestra_layout_430.py:409) |
| P1.2 worktree race | **STILL BROKEN** — локальный lock/race oracle добавлены, но stale worktrees и resume-order не проверяются | [plan.md:195-207](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/docs/tasks/430/plan.md:195), [test:206-224](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/tests/test_orchestra_layout_430.py:206) |
| P1.3 T2/T3 ownership | **FIXED** | [plan.md:227-262](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/docs/tasks/430/plan.md:227) |
| P1.4 dirty preservation | **STILL BROKEN** — проверяется статус, но не байты dirty-файлов | [test:172-186](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/tests/test_orchestra_layout_430.py:172) |
| P1.5 repair command | **STILL BROKEN** для missing-layout: partial команда исполняется, missing — нет | [test:143-158](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/tests/test_orchestra_layout_430.py:143) |
| P1.6 move receipt | **STILL BROKEN** по freshness baseline; независимая проверка самих файлов стала сильной | [test:357-377](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/tests/test_orchestra_layout_430.py:357) |
| P1.7 historical evidence | **STILL BROKEN** — набор записей строится из текущего дерева | [test:454-461](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/tests/test_orchestra_layout_430.py:454) |
| P2.8 prompt-last receipt | **STILL BROKEN** — проверяется наличие изменений, но не эксклюзивность commit boundary | [test:409-423](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/tests/test_orchestra_layout_430.py:409) |

## Findings (blocking/suggestion/question)

### Blocking

1. **[P1] Fleet migration может сломать stale worker branches**

   T4 мигрирует live/resumable worktrees после T3, но не требует, чтобы каждый worktree уже содержал T3 commit. Старый branch может получить `.orchestra/` при сохранённых старых runtime consumers; fallback запрещён. `repo_mutation_lock` сериализует запись, но не решает несовместимость версии кода. Oracle также проверяет миграцию до `knowledge_runtime_mode`, но не до `auto_resume_all`.

   **File:** [plan.md:202-207](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/docs/tasks/430/plan.md:202)

2. **[P1] Dirty refusal не доказывает сохранность содержимого**

   `before_status` сравнивается после операции, но содержимое `README.md`, tracked managed-файла и untracked managed-файла не снапшотится. Реализация может перезаписать dirty bytes, сохранив тот же статус `M` или `??`, и oracle останется зелёным.

   **File:** [test_orchestra_layout_430.py:172-186](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/tests/test_orchestra_layout_430.py:172)

3. **[P1] `ORCHESTRA_LAYOUT_MISSING` не имеет проверенной repair-процедуры**

   Для partial state команда запускается и завершается успешно, но для missing state проверяются только токены команды. Не доказано, что `--repair <absolute-repo>` действительно восстанавливает или выдаёт следующий пригодный fail-loud результат.

   **File:** [plan.md:182-184](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/docs/tasks/430/plan.md:182), [test_orchestra_layout_430.py:153-158](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/tests/test_orchestra_layout_430.py:153)

4. **[P1] `before_ref` можно подменить валидным, но устаревшим commit**

   Oracle принимает любой 40-символьный ref из receipt и сравнивает перенос с ним. Нет проверки, что это ref после свежего merge main и непосредственно перед move. Поэтому preservation proof может быть корректным относительно старого состояния, пропустив изменения между ним и реальным переездом.

   **File:** [plan.md:246-255](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/docs/tasks/430/plan.md:246), [test_orchestra_layout_430.py:357-361](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/tests/test_orchestra_layout_430.py:357)

5. **[P1] Release receipt не запрещает ранние prompt-изменения**

   Проверяется, что между `location_commit` и `prompt_commit` есть хотя бы один prompt path и `app/main.py`. Prompt-файл может уже измениться в `location_commit`, а runtime consumer — только после него; receipt всё равно пройдёт. Это не доказывает заявленную атомарную границу T3 и prompt-last.

   **File:** [plan.md:269-272](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/docs/tasks/430/plan.md:269), [test_orchestra_layout_430.py:409-423](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/tests/test_orchestra_layout_430.py:409)

6. **[P1] Historical binding set не является frozen exact set**

   Oracle собирает записи из текущих `*.json`, принимает `len(records) >= 12_759`, а затем считает digest этого же найденного набора. Удаление одной записи может пройти при наличии запаса записей; подмена записи также будет проверена как валидная. Нужен независимый ожидаемый набор IDs/bindings из frozen inventory.

   **File:** [plan.md:283-286](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/docs/tasks/430/plan.md:283), [test_orchestra_layout_430.py:454-461](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/move-dot-orchestra/tests/test_orchestra_layout_430.py:454)

## Verdict

**NOT APPROVED.** Крупные структурные исправления внесены, но остаются риски поломки stale worktrees и принятия миграции с потерянными dirty bytes, устаревшим baseline или неполной историей.

Коробки теперь подписаны, но часть грузчиков всё ещё сверяется с описью, которую сам только что составил.
