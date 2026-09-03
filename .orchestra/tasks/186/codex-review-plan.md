## Summary

План опирается на реальные точки кода: `_collect_usage_snapshot` действительно получает свежий Anthropic usage раз в 300 секунд и сохраняет снимок; в `app/routes/tg.py` текстового send-endpoint нет; `undelivered_facts` — очередь фактов для следующего хода агента; `_quota_headroom` считает доступную ёмкость 5h, а не временной дефицит `D`.

Подтверждение sighted review — дословная строка из плана:

> должен быть запланирован юзером, а не сделан мимоходом (рвёт ходы агентов четырёх проектов).

Однако latch/delivery-контракт сейчас допускает потерю сообщения, а заявленная гарантия схемой не обеспечивается.

## Findings

blocking: [docs/tasks/186/plan.md:163](docs/tasks/186/plan.md#L163) — схема не обеспечивает монотонность «физически». `state TEXT NOT NULL` допускает любое значение и любой `UPDATE`, включая `alert → ok`; `PRIMARY KEY(window_id)` обеспечивает только одну строку на окно. Храповик целиком зависит от реализации `alert_state_advance`, то есть именно от code discipline, которую архитектурный раздел заявляет устранённой. Нужен schema-level `CHECK`, а атомарное продвижение должно быть выражено условным `INSERT ... ON CONFLICT ... DO UPDATE ... WHERE state='ok' AND excluded.state='alert'`; AC должна мутировать/обходить Python guard и доказывать, что downgrade отвергает сама БД.

blocking: [docs/tasks/186/plan.md:179](docs/tasks/186/plan.md#L179) — переход состояния и Telegram-доставка не образуют надёжный протокол. Если сначала записать `alert`, затем отправлять, ошибка/рестарт после записи навсегда теряет предупреждение: следующий цикл увидит уже `alert` и не повторит отправку. Если отправлять сначала, рестарт после успешной доставки, но до записи, создаст дубль. Требование «одно сообщение на переход» невозможно гарантировать описанными тремя колонками. Нужен durable pending/delivered state либо outbox с идемпотентным ключом `window_id + transition`; AC должна покрывать рестарт/исключение между записью перехода и подтверждением доставки.

blocking: [docs/tasks/186/plan.md:166](docs/tasks/186/plan.md#L166) — `no_data` несовместим с описанным однонаправленным состоянием. Одна колонка `state` не может одновременно сохранить latched `alert`, запомнить начало непрерывного молчания и отметить, что `no_data` уже отправлен. Если заменить `alert` на `no_data`, будет потерян храповик; если не заменять, негде хранить grace-period и дедупликацию сообщения. Формулировка «возврат из no_data в прежнее состояние» требует хранения прежнего состояния, которого в схеме нет. Следует отделить alert latch от telemetry-outage latch/timestamp и тестировать `alert → no_data → data` без downgrade и повторного alert.

blocking: [docs/tasks/186/plan.md:149](docs/tasks/186/plan.md#L149) — T2 требует первый снимок с ненулевым `seven_day_pct`, хотя честное новое окно закономерно начинается с `0`. Исключив такой снимок, реализация возьмёт baseline после первого расхода и вычтет этот расход из числителя; темп и `D` будут занижены именно в начале недели, где принимается решение. Исследование отдельно различает честный ноль после сброса и строки молчания. Критерием достоверности должны быть наличие процента и валидный provider response/reset identity, а не `pct != 0`; AC нужна фикстура `0 → рост`, доказывающая, что нулевой baseline сохранён.

blocking: [docs/tasks/186/plan.md:184](docs/tasks/186/plan.md#L184) — T1/T4 replay AC самодостаточны только как regression fixtures и могут пройти на overfit/hardcode по четырём неделям. Реализация может распознать даты либо интерполировать именно заданные точки, вернуть четыре ожидаемых `D` и правильное число сообщений, не реализуя общую формулу. Добавьте независимые синтетические траектории с аналитически вычисляемым результатом, временным сдвигом тех же данных и metamorphic properties: масштаб расхода вверх увеличивает `D`, сдвиг всех timestamps на целое число недель результата не меняет, изменение будущего `reset_at` предсказуемо меняет `work_hours_left`. Исторический replay после этого остаётся внешней валидацией, а не единственным oracle.

blocking: [docs/tasks/186/plan.md:189](docs/tasks/186/plan.md#L189) — AC-3 проверяет только исключения, но не зависание/задержку доставки. `_collect_usage_snapshot` — последовательный общий цикл, а `_tg_send_safe` ожидает future диспетчера и сетевой `bot.send_message`. Медленная TG-очередь может задержать следующий snapshot, dashboard telemetry и вход #187 без единого исключения. «Wrap and log» этого не предотвращает. Нужен bounded delivery budget либо быстрая durable enqueue после сохранения снимка; AC должна подвесить sender и доказать, что сборщик завершается в заданный малый срок и новый снимок продолжает сохраняться.

suggestion: [docs/tasks/186/plan.md:187](docs/tasks/186/plan.md#L187) — сообщение обязано содержать «остаток в ходах», но контракт `RunwayVerdict` не содержит ни числа ходов, ни измеренного коэффициента перевода процентов/часов в ходы, ни указанного источника. Такая AC допускает произвольное или захардкоженное число. Либо убрать «ходы» как не необходимую для цели величину, либо определить измеренный источник, формулу и отдельный тест.

suggestion: [docs/tasks/186/plan.md:142](docs/tasks/186/plan.md#L142) — проверена только дрожь около одной минутной границы. Нет AC на устаревший snapshot после смены окна, `reset_at <= now`, внеплановый сброс utilization при неизменном календарном `resets_at` и два конкурентных вызова `alert_state_advance`. Особенно нужен конкурентный тест: два evaluator должны атомарно получить ровно одного победителя перехода, иначе два процесса/вызова могут оба отправить alert.

## Verdict

План требует доработки перед реализацией. Фактические утверждения о текущем коде в основном верны, и повторный poller не нужен, но ключевая гарантия — ровно одно доставленное сообщение на latched-переход — сейчас не обеспечена ни схемой, ни протоколом доставки, ни acceptance criteria.

## Round (2026-08-11T10:38:10Z)

## Re-review status

1. FIXED — `CHECK`, trigger and conditional upsert now enforce the ratchet at the database boundary.

2. PARTIALLY FIXED — `delivered_at` closes the ordinary crash window, but pending delivery can still be stranded when the weekly window changes before retry.

3. FIXED — telemetry silence now has independent durable state and cannot overwrite the budget latch.

4. FIXED — honest zero utilization is retained as the window baseline and covered by a focused AC.

5. FIXED — analytic and metamorphic cases make hardcoding the four historical weeks insufficient.

6. FIXED — delivery has a bounded wait after snapshot persistence, with a hanging-sender acceptance test.

7. FIXED — the unsupported “remaining turns” estimate was removed.

8. PARTIALLY FIXED — stale/reset/concurrency cases were added, but the mid-window re-baseline lacks persistent identity and therefore cannot work across successive polls.

## New findings

blocking: [docs/tasks/186/plan.md:215](docs/tasks/186/plan.md#L215) — re-baselining cannot be implemented persistently from the described inputs. `runway_window_start_pct(reset_at)` will return the same original baseline on every poll because `reset_at` did not change. If `weekly_runway` locally replaces it with the current point whenever `utilization < window_start_pct`, every five-minute poll moves `window_start_at` forward again; elapsed work remains below six hours until utilization finally exceeds the pre-reset baseline, potentially suppressing the alert for most of the week. Persist the reset segment’s baseline/timestamp or make the DB query return the start of the latest monotonic segment. The AC must replay multiple post-reset polls, including a trajectory that stays below the old baseline for more than six working hours. A single evaluation at the drop will miss this defect. Rounding itself is monotonic, but a stale/out-of-order lower sample can trigger the same false reset; require confirmation or a reset-sized/continued drop before replacing the persistent baseline.

blocking: [docs/tasks/186/plan.md:91](docs/tasks/186/plan.md#L91) — retry lookup is scoped to “the row of the current window.” Sequence: advance old window → process stops before send → service remains down across weekly reset → first new snapshot evaluates only the new `window_id`; the old row remains `delivered_at IS NULL` forever. Either `alert_pending` must select pending transitions independently of the current window, or the plan must explicitly discard obsolete alerts and stop claiming at-least-once delivery. Add an AC where restart recovery occurs after `window_id` changes.

suggestion: [docs/tasks/186/plan.md:93](docs/tasks/186/plan.md#L93) — “success” is not defined at the `send_text_to_tg` boundary. Existing `send_file_to_tg` reports operational failures as normal `{"error": ...}` returns, not exceptions. If the new helper follows that convention and the caller marks delivery after any completed await, a disabled bridge, missing topic, or `None` result permanently loses the alert. Specify a typed success result and add an AC proving error/false/`None` leaves `delivered_at NULL`.

## Verdict

Not ready to implement. Most round-1 issues are resolved, but the current re-baseline rule can indefinitely postpone detection, and recovery across a window boundary can strand an undelivered alert.

## Round 2

Current-plan sighting proof:

> `runway_window_start_pct()` в `db.py` — **общий** с #187: он берёт его у меня, а не пишет свой
