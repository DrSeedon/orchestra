# #187 Phase 3 — T1 hot policy и deterministic runtime decision

## Результат

T1 реализован как проверяемо инертный кандидат нового owner'а маршрутизации. Новый
`RuntimeRouter` принимает доверенный server-owned класс задачи, валидирует единственный
versioned policy document, получает свежую quota observation, применяет deterministic
single/dual-runtime matrix и до выхода к side-effect boundary атомарно пишет audit decision и
недельный `reserve_only` latch. Существующие spawn/turn/reconnect/review paths пока продолжают
работать через `quota_gate`; активация и удаление второго owner остаются T3 и не входят в этот
merge.

Policy GET/PUT/explain доступны как inert control plane. PUT требует настоящую dashboard cookie;
`INTERNAL_TOKEN` не является operator authority, а любая неполная пара
`DASHBOARD_USER`/`DASHBOARD_PASSWORD` fail-closed. `mode=manifest_default` остаётся начальным
режимом и не включает quota routing сам по себе.

## Код и данные

- `app/runtime_router.py` — строгие `RoutingPolicyV1`/task classes, pure evaluator,
  `DatabaseRoutingStore`, serialized admission и recompute при policy/latch CAS mismatch;
- `app/db.py` — узкий policy CAS, `runtime_routing_decisions`, immutable
  `runtime_routing_latches`, atomic decision+latch commit и read projections;
- `app/auth.py` — operator-cookie guard и запрет session validation при partial credentials;
- `app/routes/system.py` — GET/PUT/explain; legacy exact-model readiness сохранён до T3;
- `tests/test_runtime_router*.py` — policy/runtime matrix, API/auth, DB schema, transactions,
  forced interleavings и live-store integration.

Финальный инкремент после ранее смерженной инертной основы: 8 файлов, `+825/-32` до добавления
этого отчёта. Формула runway и baseline query не скопированы: используются
`quota_runway.weekly_runway`, `quota_runway.as_utc` и `db.runway_window_start_pct` из #186.

## Транзакционный контракт

`replace_routing_policy_document` — compare-and-swap узко по
`kv['runtime_routing_policy_v1']`; generic `kv_set` не появился. Decision commit выполняет один
`BEGIN IMMEDIATE`, повторно проверяет policy revision и точное множество Anthropic latch ids,
затем вставляет decision и новые latch rows. Любое расхождение отменяет транзакцию и заставляет
router перечитать policy/telemetry/baseline/latches и пересчитать решение.

Latch выражен наличием `(provider, window_id)`: `CHECK(state='reserve_only')`, запрет прямых
`UPDATE` и `DELETE`, защита от payload-changing `INSERT OR REPLACE`. Повторное решение использует
точный `ON CONFLICT(provider, window_id) DO NOTHING`; `first_decision_id` и `latched_at` всегда
остаются от первого решения окна. Широкий `INSERT OR IGNORE` не используется и не может скрыть
constraint failure.

Decision row остаётся аудитом. Право на единственный workload side effect принадлежит T2 stable
`delivery_id` + queue CAS; claim в decision table намеренно не добавлен, чтобы не завести второго
owner.

## Инертность

Команда против pre-T1 parent показала нулевой diff всех существующих workload paths:

```bash
git diff --exit-code 13b85507 -- \
  app/manager.py app/session.py app/mcp_stdio.py app/routes/sessions.py app/quota_gate.py
# exit=0
```

`rg` нашёл новый router вне его модуля только в трёх control-plane routes
`status/replace/explain`. Legacy вызовы `get_worker_admission`/`require_worker_admission`
остались в `manager.py`, `session.py` и старом readiness route. Значит merge T1 не меняет runtime
ни одного текущего workload, не переключает session/model и не требует рестарта для активации.
Полный вывод — в `measurements/t1-verification.md`.

## Проверки и мутации

- focused router/quota/auth regression: `194 passed in 26.84s`;
- четыре async admission/PUT/policy/latch race-теста: три последовательных прогона по `4 passed`;
- восемь обратных мутаций покраснили свои проверки: DB delete, broad `OR IGNORE`, смена
  `first_decision_id`, premature commit, policy recompute, admission lock, latch CAS и partial-auth
  guard входят в зафиксированный набор;
- `git diff --check` — clean; `uv.lock` не изменён.

Полный `pytest -x -q` запускался дважды под глобальным lock и оба раза остановился на одном чужом
live-state frontend test после `677 passed`: `test_header_has_orch_tabs` принят в **#197**.
Прогон без него дошёл до `1118 passed` и остановился на независимо красном live-home test
`test_encoding_matches_real_cli_directories`, который уже принадлежит **#195**. Оркестратор
признал оба baseline-дефекта чужими; T1 их не меняет. Сырые результаты и изолированные повторы —
в `measurements/t1-verification.md`.

## Codex review

Первый зрячий раунд привёл дословную строку из реализации, запустил named suite (`56 passed`) и
нашёл два blocking: stale latch snapshot между evaluate/commit и forgeable cookie при пустом
password. Оба подтверждены, исправлены и закрыты обратными мутациями.

Второй раунд дал **APPROVED**, пометил оба finding как `FIXED` и привёл проверенную дословную
строку из `app/db.py`: `runtime routing latch snapshot changed before decision commit`. Полный
непереписанный журнал обоих раундов — `codex-review-impl.md`.

## Breaking / rollout / TODO

Breaking changes: none; новый контур инертен. Live service не перезапускался, policy quota mode не
активировался, живые workers/sessions/models не трогались.

Следующие тикеты по принятому плану:

- T2 — stable `delivery_id`, durable ingress и at-most-once queue/CAS;
- T3 — атомарная миграция всех callers, удаление legacy exact-model owner и rollout только в
  согласованное окно рестарта.

#174 остаётся optional integration; T1 работает с нынешней summary/history семантикой.
