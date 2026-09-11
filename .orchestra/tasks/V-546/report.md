# V-546 — жёсткий стоп квотного гейта стал свойством полосы

Дата: 11.09.2026. Ветка `task-V-546/fix-lane-hard-stop`.

## Что сделано

Потолок жёсткого стопа больше не один на всех. `QuotaPolicy` получила поле
`lane_hard_stop_pct` и метод `hard_stop_for(lane)`; все места, где раньше читался
`policy.hard_stop_pct`, в решении по конкретной модели читают потолок ЕЁ полосы:

| место | было | стало |
|---|---|---|
| `line_limit` (`app/quota_gate.py:276`) | `min(policy.hard_stop_pct, …)` | `min(policy.hard_stop_for(lane), …)` |
| блок в `evaluate_worker_admission` (`:667`) | `utilization >= policy.hard_stop_pct` | `utilization >= hard_stop` |
| `_line_release_in_seconds` (аргумент `hard_stop_pct`) | общий стоп | потолок полосы |
| `QuotaDecision.hard_limit_pct` | общий стоп | потолок полосы |
| `rule` карты квот (`app/routes/system.py:1821`) | только `hard_stop_pct` | + `lane_hard_stop_pct` |

Дефолт без переменных: `sol` (в неё `lane_for_model` кладёт и Astra) — **95%**,
`luna` — **99%**, `claude` и `spark` не тронуты (у Claude свой пул, у Spark свой
кошелёк). Настройка тем же способом, что и остальное правило:
`QUOTA_LANE_HARD_STOP_PCT=sol=95,luna=90` из окружения или из `.env` с горячей
перечиткой по mtime (`_live_quota_env`, имя добавлено в `_QUOTA_ENV_NAMES`).

`hard_stop_for` берёт `min(общий, потолок полосы)` намеренно: общий стоп остаётся
общим ограничением сверху. Опустив `QUOTA_HARD_STOP_PCT` до 70, владелец опускает и
полосу со своим потолком 95, а не поднимает её.

Панель (`app/static/js/quota-lines.js`): `_qlHardStop(rule, lane)` — зеркало
`hard_stop_for`; кривая полосы упирается в её потолок, у полосы с более низким
потолком рисуется своя линия стопа (`data-ql-hard-lane`), и подписи «только жёсткие
N%» печатают число полосы. Без этого панель показывала бы Sol чужие 99% ровно там,
где гейт его уже не пускает.

## Проверки

Окружение: `/home/kesha/orchestra/.venv/bin/python -m pytest`, импортируемый модуль —
`/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-lane-hard-stop/app/quota_gate.py`.

**Важно про окружение прогона:** в env агента унаследована живая настройка владельца
`QUOTA_GATED_LANES=` (пустая). `_startup_quota_env` снимает её при импорте, и тогда
диагональ выключена у ВСЕХ полос — 21 тест квоты краснеет на нетронутом коде. Все
прогоны ниже сделаны через `env -u QUOTA_GATED_LANES`. Файл `.env` живого процесса не
трогался.

Зелёный прогон (`env -u QUOTA_GATED_LANES … -p no:randomly`):
`tests/test_quota_gate.py tests/test_quota_map_api.py tests/test_quota_admission_e2e.py
tests/test_quota_headroom_447.py tests/test_usage_readiness.py tests/test_mcp_quota_gate.py
tests/test_audit0901_sysquota.py tests/test_t344_quota_lines_browser.py` → **152 passed**.

### Мутации: какая мутация какой тест красит

| мутация | красные тесты |
|---|---|
| `hard_stop_for` → всегда `self.hard_stop_pct` (возврат единого потолка) | `test_ninety_six_percent_stops_the_expensive_lane_and_lets_luna_work[gpt-5.6-sol]`, `…[gpt-6-astra]`, `test_lane_ceilings_come_from_the_environment_and_reload_with_dotenv`, `test_a_reset_already_in_the_past_collapses_the_line_onto_the_hard_stop`, `test_decision_serializes_every_field_the_panel_draws` (5 failed / 88 passed) |
| `_ENV_LANE_HARD_STOP_DEFAULT = ()` (потолка полосы нет по умолчанию) | те же тесты гейта минус dotenv-тест, плюс `test_rule_constants_travel_with_the_payload` (5 failed / 88 passed) |
| из `rule` убран `lane_hard_stop_pct` | `test_rule_constants_travel_with_the_payload`, `test_rule_constants_reflect_environment_overrides` (2 failed / 14 passed) |
| `_qlHardStop` → `return hard` (панель игнорирует потолок полосы) | `test_lane_ceiling_is_drawn_and_capped_like_the_gate` (1 failed / 17 passed) |

Все мутации откатывались копией файла; после отката прогон снова зелёный (152 passed).

### Что проверяют новые тесты (`tests/test_quota_gate.py`)

- `test_ninety_six_percent_stops_the_expensive_lane_and_lets_luna_work` — оба плеча в
  ОДНОЙ точке телеметрии: при 96% Sol и Astra получают `blocked`, Luna в тот же момент
  `available`; `hard_limit_pct` равен 95 и 99 соответственно.
- `test_above_the_common_hard_stop_both_codex_lanes_are_closed` — 99.5%: стоят обе.
- `test_below_the_lane_ceiling_nothing_changed` — 94.9%: пропускаются все три модели.
- `test_claude_and_spark_keep_the_common_hard_stop` — 96% пропускает, 99% блокирует;
  потолок полос `claude`/`spark` остался 99.
- `test_lane_ceilings_come_from_the_environment_and_reload_with_dotenv` — значения из
  `.env`, перечитка по mtime, полоса, исчезнувшая из переменной, возвращается к общему
  стопу; Claude при этом не задет.
- `test_lowering_the_common_hard_stop_lowers_a_lane_that_has_its_own_ceiling` — `min`,
  а не подмена: общий стоп 70 опускает Sol с 95 до 70.
- `test_malformed_lane_ceilings_raise` — `sol`, `sol=abc`, `sol=101`, `=95`, `sol=95,`
  падают с ValueError, называющим переменную.

Точка окна в новых тестах — `progress=1.0`: там диагональ максимальна, поэтому вердикт
даёт именно жёсткий стоп, а не кривая.

### Изменённые существующие тесты (контракт поменялся вместе с правилом)

- `test_just_under_the_hard_stop_at_the_end_of_the_window_is_admitted` — теперь два
  числа: Luna 98.9%, Sol 94.9%.
- `test_a_reset_already_in_the_past_collapses_the_line_onto_the_hard_stop` — 97% → 94%,
  `limit_pct` сравнивается с потолком Sol (95), а не с общим стопом.
- `test_refusal_…` и `test_decision_serializes_every_field_the_panel_draws` — расход
  95% у Sol теперь упирается в жёсткий стоп, поэтому проверка отказа ПО ЛИНИИ взята на
  90%; в сериализации `hard_limit_pct` ожидается 95.
- `test_rule_constants_*` (`test_quota_map_api.py`) — в блоке `rule` появился
  `lane_hard_stop_pct`, второй тест проверяет и его чтение из окружения.
- `tests/conftest.py` — `QUOTA_LANE_HARD_STOP_PCT` добавлена в список гасимых
  переменных, чтобы `.env` оператора не протекал в обычные тесты.

## Предсуществующая краснота, не связанная с задачей

- `tests/test_api.py::TestTaskProjectIdentity` (9 ошибок) и `tests/test_frontend.py`
  (101 ошибка в прогоне) падают на
  `app.task_store.TaskConflict: task repository contains a duplicate identity/reference/request`
  и `project … needs one local project binding`. Проверено прямым сравнением: временно
  откатил свои правки в `app/` и `tests/conftest.py` — те же 9 ошибок в
  `TestTaskProjectIdentity` на нетронутом коде.
- `tests/test_merge_test_gate.py::test_browser_inventory_is_explicit` — известная
  краснота, названа в задаче.

## Остаточный риск

- Правки Python не действуют в живом процессе до рестарта Orchestra; рестарт не делал
  и не инициирую. JS панели подхватится без рестарта.
- Внешнего модельного ревью нет: пул Codex на 99%, `codex_review` отказал бы
  `weekly_quota_blocked`. Спорные места (семантика `min` в `hard_stop_for`, отсутствие
  валидации новой переменной на уровне модуля — она валидируется в `quota_policy()`
  так же громко, как и остальные) разобраны выше сам.
- Полный pytest в один процесс не гонялся (запрет задачи); прогон бился на наборы.
