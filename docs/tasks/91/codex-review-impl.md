## Summary

😏 Две секунды убрали, зато `switch` теперь может дождаться ровно середины `interrupt`. WAITING обработан правильно, но безопасное завершение turn ещё не гарантировано.

Ревью выполнено только по `/tmp/task91-t4.diff`; тесты не запускались по условию.

## Findings

**blocking: Сериализуйте switch с окончательной остановкой backend**

`app/routes/sessions.py:776-783`

`interrupt()` публикует событие до `await backend.interrupt()` (`app/session.py:939-945`). Ожидающий `switch` проснётся и начнёт менять worktree, пока backend ещё может писать в него. В отличие от merge, switch не захватывает `_lifecycle_lock` и не перепроверяет IDLE под ним. Это новое окно появилось потому, что раньше running-worker отклонялся сразу. Нужно обернуть switch в тот же lifecycle-lock и повторную проверку статуса, что используются для merge.

---

**question: Должно ли “persisted before publish” означать завершённую запись в БД?**

`app/session_turns.py:228-229`

`_persist()` лишь ставит coalesced persistence task в очередь — это прямо следует из комментария у `app/session.py:1453-1454`. Поэтому событие публикуется после планирования записи, но до её завершения. Тест подменяет `_persist()` синхронной функцией и доказывает только порядок вызовов. Если контракт требует реально сохранённый IDLE/WAITING, перед `publish_turn_finished()` нужен awaitable flush/ack persistence.

---

**suggestion: Проверяйте настоящие пути завершения каждого runtime**

`tests/test_session.py:321-322`

Параметризация по Claude/Codex/Grok/OpenCode меняет только `backend_type`, после чего четыре раза напрямую вызывает один и тот же `TurnManager.finish_turn_status()`. Тест останется зелёным, даже если persistent Claude или любой per-turn adapter перестанет доводить событие до этого метода. Нужны runtime-specific fake streams через общий обработчик; туда же стоит включить abnormal exit и удерживаемый `backend.interrupt()` для обнаружения гонки выше.

## Verdict

**NEEDS WORK**

Switch может продолжить lifecycle при ещё активном backend — это blocking race по заданной шкале. Заодно текущие тесты подтверждают helper, но не заявленный межruntime-контракт. Логическое завершение получилось как закрытие двери до щелчка замка: табличка уже висит, а дверь ещё открыта.

## Round (2026-07-28T06:20:21Z)

## Summary

😏 На этот раз замок действительно защёлкнулся. Все предыдущие пункты закрыты; новых blocking-регрессий в обновлённом diff не найдено.

## Findings

- **FIXED — blocking:** `switch_branch` захватывает `_lifecycle_lock`, повторно проверяет IDLE и только затем меняет Git. Регрессионный тест воспроизводит окно до подтверждения interrupt.

- **FIXED — suggestion:** runtime-тест теперь проводит `turn_end` через persistent/per-turn event loops согласно реальному `RuntimeDefinition`.

- **RESOLVED — question:** eventual `_persist()` соответствует уточнённому AC; физический SQLite flush не входит в контракт T4.

Новых blocking, suggestion или question findings нет. Заявленные результаты тестов: 319 passed, T4 subset — 13 passed; самостоятельно не запускались по условию.

## Verdict

**APPROVED**

Теперь `turn_finished` действительно сообщает о безопасной передаче lifecycle, а не кричит «заходите», пока interrupt ещё обувается.
