## Summary

🙃 `maxsize=256`, конечно, не мешает построить бесконечную очередь из ожидающих эту очередь. План хорошо декомпозирован, но две гонки всё ещё допускают исчерпание памяти и повреждение следующего медиабатча.

## Findings

1. **blocking — Ограничьте ожидающих производителей reliable-очереди**
   [plan.md:28](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/polish-tg/docs/tasks/polish-tg/plan.md:28)

   `Queue(maxsize=256)` ограничивает элементы внутри очереди, но не ожидающие `put()` корутины. После 257-го производителя последующие вызовы могут бесконечно накапливать futures и память. Нужен ограниченный admission либо доказанный предел upstream-производителей с нагрузочным тестом concurrent overflow/reset.

2. **blocking — Не храните media generation только в очищаемом `_BufState`**
   [plan.md:149](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/polish-tg/docs/tasks/polish-tg/plan.md:149)

   После `stop_bridge()` `_buffers` очищается, поэтому новый `_BufState` может повторить прежнюю пару `(generation, reservation)`. Переживший restart старый resolver тогда снова станет валидным и повредит новый батч. Нужен process-lifetime epoch или уникальный неприменяемый повторно token; AC должен покрывать `stop → restart → collision`.

3. **suggestion — Версионируйте telemetry entry во время отправки**
   [plan.md:84](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/polish-tg/docs/tasks/polish-tg/plan.md:84)

   Если новое событие того же ключа поступит, пока предыдущий digest находится в Bot API attempt, завершение старой отправки может удалить уже обновлённое значение. Зафиксируйте version/generation отправляемого snapshot и очищайте entry только при совпадении версии; добавьте тест с update во время заблокированного send.

4. **suggestion — Определите отдельного владельца image delivery**
   [plan.md:110](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/polish-tg/docs/tasks/polish-tg/plan.md:110)

   Требования одновременно запрещают изображению удерживать stream cursor и требуют вернуть фактический результат Telegram. Без явно заданной bounded image lane реализация либо будет ждать send в `stream_logs()`, либо создаст неограниченные фоновые задачи. Укажите capacity, full policy, owner и способ асинхронно связать completion с текстовым fallback.

5. **suggestion — Очищайте registry при удалении оркестратора или топика**
   [plan.md:126](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/polish-tg/docs/tasks/polish-tg/plan.md:126)

   План очищает stream/status registries только при остановке bridge. После `remove_topics_for_orchs()` старый stream продолжит жить, а сохранённый registry entry может помешать корректному созданию нового stream для повторно созданного топика. Добавьте cancel/await/remove и тест delete→recreate.

6. **suggestion — Сериализуйте создание одного топика**
   [plan.md:130](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/polish-tg/docs/tasks/polish-tg/plan.md:130)

   Идемпотентный stream registry не предотвращает два параллельных `ensure_topics()`: оба могут увидеть отсутствующую запись и создать разные Telegram topics. Нужен per-orchestrator in-flight guard и concurrent acceptance test; отдельно зафиксируйте риск удалённого успеха после локального 5-секундного timeout.

7. **suggestion — Дожидайтесь завершения отменённых владельцев**
   [plan.md:92](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/polish-tg/docs/tasks/polish-tg/plan.md:92)

   `cancel()` лишь запрашивает отмену. Если registries очистить и сразу запустить bridge заново, старый dispatcher или status task может ещё отправить запрос либо изменить rate state параллельно новому владельцу. `stop/reset` должны cancel и await владельцев до очистки состояния и возврата.

## Verdict

**NEEDS REVISION**

Два blocking-дефекта нарушают заявленные boundedness и generation-safety. Остальная структура пригодна для реализации после уточнения этих контрактов — сейчас это турникет на 256 мест с бесконечной толпой в тамбуре.

## Round (2026-07-25T13:57:31Z)

## Re-review status

🙃 Git спрятал `plan.md` как untracked-файл, поэтому обычный diff был пуст; проверена полная версия через diff с `/dev/null`.

| # | Статус | Результат |
|---|---|---|
| 1 | **FIXED** | Reliable admission ограничен `256 + 64`, overflow завершается явно, добавлен concurrent/reset AC. |
| 2 | **FIXED** | Media token использует уникальные epoch и reservation identity, включая stop→restart AC. |
| 3 | **FIXED** | Telemetry version сохраняет обновление, пришедшее во время send. |
| 4 | **FIXED** | Images получили bounded ingress, одного owner, completion future и независимый text fallback. |
| 5 | **FIXED** | Удаление топика отменяет и дожидается registry owners; delete→recreate покрыт. |
| 6 | **FIXED** | Создание сериализовано, ambiguous result сохраняется и запрещает blind retry. |
| 7 | **FIXED** | Stop/reset теперь cancel и await владельцев до очистки registries. |

## New findings

- **NEW BUG — suggestion:** T1 гарантирует разрешение admission waiters, но не completion futures уже находящихся в 256 queued entries. При reset ожидающие результат direct callers могут зависнуть после очистки очереди. Добавьте AC: queued, admitted и in-flight submissions завершаются typed stopped/cancelled result.

- **NEW BUG — suggestion:** для image/mirror workers не определён класс внутри shared rate authority. Если они занимают reliable queue/admission slots, optional traffic может вызвать overload и потерю primary text. Нужен отдельный best-effort lane либо saturation AC, доказывающий резервирование reliable capacity для primary.

Новых blocking-противоречий нет.

## Verdict

**APPROVED**

Оставшиеся замечания — suggestions и не блокируют Phase 3. Турникет теперь ограничен; осталось не раздать места ответов зеркалам и картинкам.
