## Summary

🙃 1166 тестов зелёные, но два края контракта остались неприкрыты. Блокирующих проблем нет; две реальные suggestions.

## Findings

### suggestion — Повторно запускайте compaction gate после Claude context refresh

**File:** `app/session_turns.py:221`

В новой или сброшенной Claude-сессии `_last_context` ещё неизвестен, поэтому `DeferredContext` даёт `context_known=False` и этот gate не ставит precompact-таймер. Фоновый `_refresh_context_from_api()` затем получает корректный процент, но таймер уже не планирует. В результате первый большой turn может остаться без precompact и auto-compact до следующего turn — регрессия относительно прежнего `_schedule_precompact_timer(0)`. После успешного deferred refresh нужно повторно запустить compaction scheduling.

### suggestion — Обрабатывайте `OverflowError` при нормализации чисел

**File:** `app/usage_contract.py:10-12`, `app/usage_contract.py:19-21`, `app/usage_contract.py:105-108`, `app/usage_contract.py:124-127`

`int(float("inf"))` выбрасывает `OverflowError`, который сейчас не перехватывается. Такое значение возможно даже из JSON вроде `1e309`, поэтому некорректные aggregate/context/max/percentage могут уронить turn вместо обещанного fail-soft перехода в ноль или `UnknownContext`. Добавьте `OverflowError` во все четыре блока преобразования.

## Verdict

⚠️ **Non-blocking changes requested.** Разделение aggregate/current, сохранение metadata/cost и time-window gate выглядят корректно, но Claude deferred-flow имеет функциональный пробел. Зелёный suite тут как compaction gate: всё спокойно, пока не попадаешь ровно между двумя проверками.

## Round (2026-07-28T14:52:08Z)

## Summary

🙃 Оба прежних замечания исправлены: `OverflowError` обрабатывается, Claude после первого deferred refresh планирует compaction ровно один раз. Новых блокирующих регрессий нет.

## Findings

### suggestion — Сохраняйте полный compaction gate при deferred refresh

**File:** `app/session_turns.py:157-160`

Флаг учитывает только `context_known`, но не `subscription_limited` и ранний выход при `max_turns`. Поэтому неизвестный Claude-контекст после refresh может запустить compaction, хотя основной lifecycle его намеренно запретил. Передавайте в refresh итоговое решение `allow_precompact`, а не только состояние контекста.

## Verdict

✅ **Approve with suggestion.** Предыдущие findings закрыты, `app/usage_contract.py` корректен, новых crash/corruption/security-проблем не найдено. Единый gate почти получился — один флаг пока ходит через служебный вход.
