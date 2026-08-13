# #227 — серверный model gate для worker spawn

## Результат

`spawn_worker` больше не полагается на соблюдение текстового model-routing. Политика живёт в
`pipelines/default/pipeline.yaml`, типизированно грузится общим pipeline loader и проверяется в
`SessionManager` до создания worktree, старта backend и публикации сессии.

- Всегда разрешены `gpt-5.6-sol`, `gpt-5.6-luna`, `gpt-5.3-codex-spark`.
- Явно запрещены `claude-fable-5[1m]` и `gpt-5.6-terra`; прочие не перечисленные worker-модели
  тоже отклоняются.
- `claude-opus-5[1m]` управляется разрывом `anthropic.seven_day.utilization -
  codex.primary.utilization`: блокировка при `>=6` п.п., разблокировка при `<=3` п.п.; внутри
  полосы сохраняется предыдущее состояние. После холодного старта значение внутри deadband
  консервативно считается заблокированным. При текущих `63% / 8%` разрыв равен `55` п.п.
- Полоса 3 п.п. выведена из формы телеметрии: оба отображаемых целых счётчика могут сдвинуться
  на один пункт за выборку, то есть совместный шаг разрыва достигает 2 п.п.; deadband взят на
  один пункт шире.
- Роли с `kind: orchestrator` освобождены от worker policy.
- `model_policy_override_reason` работает только с непустой причиной; причина пишется в warning.
- Недоступная, malformed или зависшая телеметрия пропускает спавн и пишет error. Общий дедлайн
  чтения `/api/usage` — 12 секунд, меньше 30-секундного MCP request budget.
- Битый YAML/типизированный manifest остаётся fail-closed по существующему контракту pipeline
  loader; fail-open относится к runtime model gate и его телеметрии.

## Окно несовместимости MCP ↔ route

- **Новый MCP + старый route.** Обычный спавн не содержит нового поля и идёт прежним путём.
  При явном исключении новый MCP посылает поле, старый Pydantic request его игнорирует как extra;
  старый manager ещё не имеет гейта, поэтому спавн проходит, но причина исключения не логируется.
- **Старый MCP + новый route.** Поля нет, route подставляет `""`; новый manager применяет policy
  как к спавну без исключения. Sol/Luna/Spark проходят, перекошенный Opus и статически запрещённые
  модели получают 409. Исключение недоступно до реконнекта агента на новый MCP.

После мержа код manager/route начнёт действовать только после рестарта Orchestra. Манифестные
списки и пороги после активации кода горячие: pipeline loader перечитывает YAML по
`(имя, путь, mtime_ns, размер)`.

## Проверки

- Красный оракул до реализации: `10 failed` на отсутствующих policy seam/manifest field.
- Узкий регресс: `290 passed in 20.20s`.
- Мутация на зелёном: удалён единственный вызов `_enforce_worker_model_policy` (`marker-before=1`)
  → `test_skewed_pools_reject_opus_worker_before_publish` красный `DID NOT RAISE`; после отката,
  `touch` и `marker-after=1` → `1 passed`.
- Codex review, раунд 1: blocking — у telemetry lookup не было общего timeout.
- После фикса Codex дословно: `Re-review status: **FIXED**.` / `New findings: None.` /
  `Verdict: **APPROVED**`. Его независимый прогон timeout-оракула: `1 passed in 5.73s`.

Полный suite не запускался по условию задачи. Попытка полного `tests/test_manager.py` была
остановлена как непропорционально долгая; этот прогон не используется как evidence.
