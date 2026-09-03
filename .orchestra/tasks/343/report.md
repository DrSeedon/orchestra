# #343 — одно правило допуска по квоте, прежние системы вырезаны

Коммит: `36606f6d`, ветка `task-343/impl-quota-rule`.
Объём: 51 файл, **+1224 / −11043**. `app/static/` не тронут (граница #344).

## Что теперь решает допуск

Единственный владелец — `app/quota_gate.py`. Ни одного другого места, читающего расход
для решения о спавне, в коде не осталось.

```
норма    = progress * 100                       # доля пройденного окна
допуск   = 10 + (1 - 10) * progress             # 10 п.п. в начале → 1 п.п. к сбросу
предел   = min(99, норма + допуск)              # line_limit()
```

| полоса | gated | блокируется когда |
|---|---|---|
| `claude`, `sol` | да | `utilization >= 99` **или** `utilization > предел` |
| `luna`, `spark` | нет | `utilization >= 99` |
| оркестраторы | — | **никогда**, ни на 99, ни на 100 |

Отказ строго ВЫШЕ линии (`>`, не `>=`) — граница принадлежит разрешению.

Пулы и начало окна (одна формула `resets_at − window_minutes` на оба вида окна):
`anthropic.seven_day` (фиксированный вторник), `codex.primary` (скользящее),
`codex_spark.primary` — **свой счётчик**, потому что на 19.08 Codex показывал 100%
при Spark 39%.

Истории правило не помнит: после сброса и расход, и доля окна начинаются заново, поэтому
специального кода под обнуление нет. `resets_at` в прошлом → `progress` зажат в `1.0`, и
линия там равна жёсткому стопу, то есть вырождается корректно.

## Fail-open решён сквозным образом, а не в одной точке

`require_worker_admission` отказывает **только** на `state="blocked"`. `unknown`
пропускают одинаково спавн, `/send`, дренаж очереди, компакт и `codex_review`.

Прежняя дыра #227 была не в полярности, а в её РАССОГЛАСОВАНИИ: спавн пропускал на
`quota=unknown`, а следующий обязательный `/send` тем же вопросом отвечал 429 — сессия
рождалась мёртвой. Побочный эффект правки: в `mcp_stdio.py` схлопнулись ~100 строк
легаси-провода (`wire_version`, `decision_state`, окно свежести, имя политики) — все эти
ветки существовали ради решения «отказывать ли при сомнении».

## Что вырезано целиком

`app/quota_controller.py` (shadow #291) · `app/quota_runway.py` + `deficit_hours`/
`min_work_hours` (наблюдающая половина #314) · `app/quota_alert.py` ·
`app/runtime_router.py` (инертный audit-контур #187) · `_quota_headroom` и производный
блок недели в `/limits` · `worker_model_policy` + `model_policy_override_reason` (гейт
#227) · таблицы `quota_controller_*`, `quota_alert_state`, `quota_silence`,
`runtime_routing_*` · `usage_exchange_rate` · `AgentSession.fast_mode`/`task_class` и три
`_server_*` метода, осиротевшие сносом shadow-контроллера.

Удалено 9 эндпоинтов (сверено машинно, `route_surface` показал ровно их и ни одного
лишнего): `/api/usage/quota-controller` +`/policy` GET/PUT +`/policy/rollback`
+`/reserve` POST/DELETE, `/api/usage/routing-policy` GET/PUT, `.../explain`.
`/api/usage` больше не отдаёт `quota_headroom`; `/api/usage/analytics` — `quota_controller`.

**Не сделано намеренно:** таблицы вырезанных систем НЕ дропаются из живой БД. Код их
больше не создаёт и не читает, они инертны; `DROP` по чужим данным необратим и требует
отмашки. Скажи — снесу отдельной командой.

## Приёмка: что доказано прогоном

Все четыре пункта закрыты `tests/test_quota_admission_e2e.py` — на реальном пути
`create_session`, а не на арифметике:

- Sol и Claude **не создаются** выше линии и **создаются** под ней (обе стороны);
- Luna и Spark **создаются** на том самом значении, что останавливает Sol, и
  **не создаются** на 99%;
- оркестратор создаётся при 100% (и квоту не читает вовсе);
- `unknown` пропускает и спавн, и последующий `/send`.

**Мутации** (`cp` → мутация → `touch` → прогон → `mv` → `touch`, `grep -c` маркера до и
после отката обеими цифрами, зелёный повтор после отката):

| мутация | результат |
|---|---|
| `utilization > limit` → `> limit + 1000` | 2 красных — только тесты «выше линии» |
| `GATED_LANES` += `luna`,`spark` | 4 красных — только тесты негейтящихся полос |
| `codex_spark` → `codex` в `_model_target` | 3 красных — разделение счётчиков Spark |
| снять `not is_orch` в `manager.py` | 1 красный — тест оркестратора |

**Полный прогон без `-x`:** `4 failed, 2872 passed, 85 skipped` (35 мин).
Было 31 падение — 27 починены. Оставшиеся 4 доказаны предсуществующими прогоном на
нетронутой базе (`git stash`): `test_tailwind_css`, `test_workspace::TestMergeTarget`,
`test_seamless_restart::test_t2_...` красные 3 из 3; `test_undelivered::
test_debounce_task_no_longer_swallows` — флак по wall-clock (`asyncio.sleep(0.5)`),
на базе 2 падения из 4 прогонов. Сверено и с `main`: между базой ветки и `main` нет
изменений в `app/` и `tests/` вовсе.

Тестов вырезанных систем не осталось: единственное совпадение грепа —
`assert "quota_controller" not in payload`, регрессионный сторож.

## Найденные попутно проблемы

1. **`tests/test_mcp_quota_gate.py` был красным на `main`** — фикстура отвечала на
   `/api/sessions/{name}/send`, а спавн давно ходит в `/initial-deliveries`. Починил
   заодно (файл всё равно переписывался).
2. **`@router.get("/api/usage/quota-controller")` висел над `_attach_runway_observation`**,
   а не над `quota_controller_status` — декоратор регистрировал не ту функцию. Ушло
   вместе с эндпоинтом, но это был живой баг.
3. **`test_undelivered::test_debounce_task_no_longer_swallows` — флак** по wall-clock, не
   мой; тот самый класс, про который предупреждает `CLAUDE.md`. Не чинил: вне задачи.
4. Три предсуществующих красных (`test_tailwind_css`, `test_workspace`,
   `test_seamless_restart`) — чужой долг, не трогал.

## Фронту (#344)

Контракт отдан ДО начала правок и не менялся: `docs/tasks/343/api-contract.md`.
Роут `GET /api/usage/quota-map`, вердикты и `limit_pct`/`tolerance_pp`/`progress`
считаются на сервере, константы правила едут в `rule`. В `app/static/js/` остаются
читатели снятых ключей (`quota_headroom` в `usage.js`, `quota_controller.runway` в
`analytics.js`) — это его территория, предупреждён отдельным сообщением.
