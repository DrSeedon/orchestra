## Summary

Ну да, `SERENA_HOME` оказался скорее пожеланием, чем изоляцией 🧪

- Sentinel убедительно подтверждает исправление выбора worktree-root и чтение правильного содержимого в 1.6.1. Однако заявленная изоляция эксперимента неверна.
- Один HTTP instance для разных worktree обоснованно отвергнут как неподдерживаемая конфигурация. Документ не доказывает техническую невозможность, но для эксплуатационного решения этого достаточно.
- Breaking-change audit достаточен для MVP-интеграции: проверены CLI, конфиги, tool surface и основной `find_symbol` workflow.
- Rollback и безопасное сохранение live-сессий описаны недостаточно.

## Findings

### Blocking

Нет.

### Suggestion

1. **Исправить утверждение о герметичности sentinel-теста.**  
   [research.md:145](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-branch-switch/docs/tasks/112/research.md:145)

   Строка 150 утверждает, что отдельный `SERENA_HOME` исключил live registry/config, но оба raw-прогона загрузили `/home/maxim/.serena/serena_config.yml`; before-output также содержит живой список проектов. Это не опровергает root fix: auto-detected root изменился с main на worktree, после чего `find_symbol` вернул правильные sentinels. Но эксперимент не был изолирован так, как заявлено. Следует либо повторить его с реально поддерживаемым перенаправлением конфигурации, либо сузить формулировку доказательства.

2. **Сделать rollback воспроизводимым и долговечным.**  
   [research.md:242](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-branch-switch/docs/tasks/112/research.md:242)

   Единственные копии launcher/config лежат в `/tmp`, а сам rollback не выполнялся. После очистки `/tmp` инструкция «восстановить два launcher» становится невыполнимой, хотя старый Python package ещё установлен. Нужен постоянный backup либо точная команда восстановления 1.1.2 в изолированной среде, плюс staged-проверка rollback без переключения live executable.

3. **Определить drain-протокол перед P0 recycle.**  
   [research.md:270](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-branch-switch/docs/tasks/112/research.md:270)

   Формулировка «только idle sessions» не гарантирует сохранение активного turn: между проверкой idle и disconnect может прийти новое сообщение. Согласованный restart прямо допускает прерывание turns. Для обещания сохранить live-сессии нужны блокировка новых sends, ожидание завершения turn, reconnect с сохранённым session ID, проверка нового Serena root и только затем снятие блокировки. Без этого top-3 сохраняют данные сессий, но не непрерывность текущей работы.

### Question

- Под «один global instance небезопасен» имеется в виду неподдерживаемая эксплуатационная схема или доказанная невозможность session-level изоляции? [H2](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-branch-switch/docs/tasks/112/research.md:36) надёжно обосновывает первое официальным same-project ограничением. Для второго понадобился бы source-level разбор ownership `active_project`/cache либо конкурентный тест двух HTTP sessions. На текущую рекомендацию не делить instance между worktree это не влияет.

## Verdict

**VERDICT: вывод о worktree-root fix принимается; operational plan требует доработки.**

1. Sentinel действительно подтверждает исправление 1.6.1, хотя тест не был герметичным.
2. Один global HTTP instance не следует использовать для разных worktree.
3. Compatibility audit достаточен, но rollback пока ненадёжен.
4. Top-3 меры не доказывают сохранение активных turns без отдельного drain/reconnect протокола.

Иначе получится контролируемый recycle примерно как контролируемое падение со стула: намерение есть, а непрерывность всё равно закончилась. 🪑

## Round (2026-08-01T07:43:45Z)

## Summary

Ну всё, `/tmp` больше не назначен системой резервного копирования 😏

Все замечания первого раунда закрыты:

- Sentinel повторён герметично и подтверждает чтение правильного worktree.
- Rollback воспроизводим без временных backup-файлов и проверен staged.
- Небезопасный автоматический recycle исключён; необходимый drain-протокол описан явно.
- Shared-global вывод корректно ограничен неподдерживаемой эксплуатационной схемой.

## Findings

### Blocking

Нет.

### Suggestion

Нет.

### Question

Нет.

Новых фактических ошибок или противоречий в research и плане не обнаружено.

## Verdict

**VERDICT: APPROVED.** Документ корректен для MVP-решения; все предыдущие замечания закрыты, оставшиеся риски названы без завышенных обещаний.

Теперь план похож на rollback, а не на поиски вчерашнего launcher по остывшему `/tmp` 🔎
