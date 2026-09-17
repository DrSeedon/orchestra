# V-582 — харнес-маршруты приходят из живого каталога, допуск решается по нему

Ветка `task-V-582/fix-harness-routes`. Правки Python **заработают только после рестарта
владельцем**: в живом процессе сейчас старый `validate_harness_model_spec`.

## 1. Зашитых харнес-маршрутов в каталоге больше нет

Из `SELECTABLE_MODEL_SPECS` (`app/models.py`) убраны оба: `z-ai/glm-5.2:free` и
`nvidia/nemotron-3-ultra-550b-a55b:free`. На их месте — комментарий о том, почему харнес
в манифесте не объявляется вовсе. Состав харнес-маршрутов теперь приходит ровно из одного
места — `app/model_catalog.py` (кеш живого каталога OpenRouter в kv `model_catalog_cache`,
регистрация через `apply_model_catalog`).

Сверка с живым каталогом 17.09.2026 (прямой GET `openrouter.ai/api/v1/models`):

| маршрут | живой каталог |
|---|---|
| `z-ai/glm-5.2:free` | `tools=False`, `ctx=32768` (наша запись обещала tools и 256000) |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | `tools=True`, `ctx=1000000` |

То есть один из двух зашитых маршрутов противоречил живым данным прямо в момент правки,
а второй жив и сегодня проходит протокол (см. §4) — при том, что 16.09 он же игнорировал
результат инструмента. Это и есть довод против зашитого списка: состояние маршрута
меняется в течение суток, наша запись о нём — нет.

## 2. Допуск решается по живым данным

`validate_harness_model_spec` (`app/models.py`) больше не смотрит на наш
`spec.supported_parameters` и наш `spec.available`. Порядок проверок:

1. рантайм `harness`, точный суффикс `:free` — как раньше, это наш собственный контракт;
2. `live_catalog_entry(spec.id)` (новая функция в `app/model_catalog.py`) — маршрута нет
   в каталоге, который мы забрали у провайдера → отказ «is not in the OpenRouter catalog
   we fetched»;
3. `harness_capable(live)` (бывший приватный `_cached_harness_eligible`, переименован и
   стал публичным, оба прежних вызова внутри модуля переведены) — живые данные говорят
   «нет tools» → отказ «does not advertise tool support in OpenRouter's own catalog»;
4. `live["available"]` — маршрут исчез из выдачи и удержан как совместимость → прежний
   отказ «no longer available on OpenRouter».

Fail-closed остаётся fail-closed и усиливается: с пустым кешем каталога не проходит ни
один харнес-маршрут. Это осознанный размен — раньше пустой кеш означал «работают два
зашитых маршрута», теперь означает «харнеса нет, обнови каталог».

Цена вызова: чтение kv + `json.loads` каталога (435 записей, ~0.5 мс) на каждый вызов
валидатора. `/api/models` дёргается heartbeat'ом раз в 3 с и валидирует каждый харнес-
маршрут отдельно — при 17 зарегистрированных это ~9 мс раз в 3 с. Кеш-слой не вводил
намеренно: инвалидация делается только двумя писателями kv, а тесты и внешние правки
кеша молча получали бы устаревший ответ.

## 3. Проба стала инструментом репозитория

`scripts/probe_free_models.py`. Разовый `.orchestra/tasks/V-581/probe_free_models.py`
удалён вместе со своим закоммиченным `__pycache__/*.pyc` — второй копии пробы быть не
должно; доказательства V-581 (`probe.log`, `probe-results.json`, `probe-retry.*`) на месте.

```
python scripts/probe_free_models.py --out .orchestra/tasks/V-582/probe-results.json \
    --budget-seconds 1080 --timeout 90
python scripts/probe_free_models.py --model cohere/north-mini-code:free
```

Ключи: `--out` (машиночитаемый JSON; без него JSON уходит в stdout, человекочитаемая
строка на маршрут — всегда в stderr), `--model` (повторяемый), `--limit`,
`--requests-per-route` (потолок расхода, по умолчанию 2 — минимум протокола),
`--budget-seconds`, `--timeout`. Код возврата 0, если прошёл хотя бы один маршрут.

Классификация исхода:

- `ok` — вызвал инструмент, передал осмысленный аргумент И ответил по результату;
- `result_ignored` — **вызвал инструмент и проигнорировал ответ**; именно этим болел
  nemotron-3-ultra 16.09, и это НЕ прохождение;
- `wrong_argument`, `no_tool_call` — отказ самой модели;
- `rate_limited`, `http_403`, `timeout` — отказ провайдера, отделён от отказа модели;
- `not_probed` — не дошёл бюджет времени; маршрут назван, а не выпал молча.

Регрессия без сети: `tests/test_probe_free_models.py` (5 тестов, `_post` подменяется),
центральный — «вызвал и проигнорировал» обязан быть непрошедшим.

## 4. Свежий прогон пробы — состав прошедших изменился

Команда (ключ из `.env`, в отчёт не копируется):

```
python scripts/probe_free_models.py --out .orchestra/tasks/V-582/probe-results.json \
    --budget-seconds 1080 --timeout 90
```

17.09.2026 09:04, 127.2 с, 18 кандидатов `:free` с заявленным `tools`, потолок 2 запроса
на маршрут (16.09 допускалась третья попытка на 429 — сегодня нет, это граница задачи).
Результат: **прошли 9 из 18**, но состав другой.

| маршрут | 16.09 | 17.09 |
|---|---|---|
| `nvidia/nemotron-3-ultra-550b-a55b:free` | result_ignored | **ok** (4.5 с) |
| `nex-agi/nex-n2.5-mini:free` | timeout 90 с | **ok** (2.5 с) |
| `nvidia/nemotron-3.5-lightning:free` | ok (32.5 с) | **timeout 90 с** |
| `google/gemma-4-26b-a4b-it:free` | ok со второй попытки | **rate_limited** (повтор не разрешён бюджетом) |
| `dots-3-note-preview`, `ling-3.0-flash-sante`, `ling-3.0-flash-fin`, `nemotron-3-super-120b`, `cohere/north-mini-code`, `liquid/lfm-2.5-2.6b`, `nex-n2.5-pro` | ok | ok |
| `inclusionai/ling-3.0-flash-vl:free` | result_ignored | result_ignored |
| `nvidia/nemotron-3-nano-omni-...-reasoning:free` | no tool call | no tool call |
| `thinkingmachines/inkling*:free` | 403 «only available on agentic harnesses» | то же |
| `poolside/laguna-s-2.1`, `laguna-xs-2.1`, `gemma-4-31b-it` | 429 | rate_limited |

Вывод честно: «те же 9» — совпадение числа, а не состава. За сутки перевернулись четыре
маршрута, причём в обе стороны. Полные данные — `probe-results.json` рядом с этим файлом.

## 5. Тесты

Абсолютный путь импортированного app-модуля:
`/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-harness-routes/app/models.py`
(и `.../app/model_catalog.py`), интерпретатор `/home/kesha/orchestra/.venv/bin/python`.

```
python -m pytest tests/test_models.py tests/test_model_catalog.py \
  tests/test_model_catalog_frontend.py tests/test_model_flags.py tests/test_model_gates.py \
  tests/test_catalog_api.py tests/test_runtime_registry.py tests/test_harness_production.py \
  tests/test_harness_inject.py tests/test_harness_tools.py tests/test_audit0901_harness.py \
  tests/test_backend_harness_turn_usage_422.py tests/test_openrouter_counter.py \
  tests/test_model_registry_503.py tests/test_change_model_unloaded.py \
  tests/test_model_text_control_flow.py tests/test_probe_free_models.py tests/test_wf_run.py -q
→ 188 passed in 54.12s

python -m pytest tests/test_session.py tests/test_mcp_stdio.py \
  tests/test_validate_spawn_unknown_role.py tests/test_audit0901_session.py \
  tests/test_sessions_conditional.py -q
→ 380 passed in 49.50s
```

Оба плеча допуска (`tests/test_model_catalog.py`, сеть не задействована — живой каталог
подменяется записью в kv):

- отрицательное — `test_t2_admission_refuses_route_the_live_catalog_no_longer_backs`:
  наш spec утверждает `tools`, живые данные говорят `supports_tools=False` → отказ;
  затем маршрут вовсе убран из каталога → отказ;
- положительное — `test_t2_admission_passes_route_the_live_catalog_still_backs`.

**Мутация.** Вернул старую проверку по статическому полю (`"tools" not in
spec.supported_parameters` + `not spec.available`) на место живой: красным стал РОВНО
`test_t2_admission_refuses_route_the_live_catalog_no_longer_backs`
(`1 failed, 10 passed`), положительное плечо осталось зелёным. Оба теста — в этом диффе.

Изменения в тестах по существу правки, а не ради зелёного:

- `tests/conftest.py` — фикстура `live_harness_route`: подменяет запись провайдера о
  маршруте и регистрирует его через `apply_model_catalog`, на teardown снимает;
- `tests/test_model_gates.py`, `tests/test_harness_inject.py`, `tests/test_wf_run.py`,
  `tests/test_session.py` — харнес-модели берутся из подменённого каталога, а конкретные
  чужие вендорские id заменены на `vendor/*:free`: тест не должен зависеть от того, жив
  ли сегодня чей-то маршрут;
- удалён `test_t1_manifest_harness_models_start_fail_closed` — его предмет (харнес-записи
  в манифесте) больше не существует; fail-closed по умолчанию для каталожного маршрута
  проверяет соседний `test_t1_registered_catalog_model_defaults_to_hidden_and_forbidden`.

## 6. Что проверено сверх тестов и что осталось риском

Читал живую БД read-only (`file:...?mode=ro`):

- кеш каталога в kv от 10.09, 435 записей, харнес-пригодных 17. `z-ai/glm-5.2:free`
  в нём ОТСУТСТВУЕТ → после рестарта он исчезает из реестра совсем (правильно: маршрут
  мёртв). `nvidia/nemotron-3-ultra-550b-a55b:free` в кеше есть с `tools=True` →
  регистрируется как раньше;
- `model_flags` в kv: у обоих маршрутов стоит `{agents:true, dashboard:true}`. Для glm
  это теперь висячая запись без модели — флаги оверлей, перечисление идёт по `MODELS`,
  так что нигде не всплывёт. nemotron сохраняет включённые флаги;
- сессий на `:free`-маршруте сейчас нет ни одной (592 сессии, совпадений `model LIKE
  '%:free%'` — ноль), то есть ничья живая сессия правкой не ломается.

Остаточные риски, названные явно:

1. Кеш каталога недельной давности. До первого обновления (кнопка на экране моделей →
   `refresh_catalog`) допуск решает по снимку 10.09, а не по сегодняшнему каталогу. Это
   всё равно живые данные провайдера, но не сегодняшние; сегодняшние отличаются —
   в текущем каталоге `:free`-маршрутов 20, а `z-ai/glm-5.2:free` уже без tools.
2. Проба — снимок, а не приговор: §4 показывает, что маршрут переворачивается за сутки.
   Одиночный `result_ignored` не повод выпиливать маршрут навсегда, а одиночный `ok` не
   повод считать его надёжным.
3. `thinkingmachines/inkling*:free` (1M контекста) отдают 403 «only available on agentic
   harnesses» — нужна регистрация приложения в OpenRouter, обычный ключ не пускают.
   Отдельная работа, в эту задачу не входила.

## 7. Внешнее ревью

Не делалось: `codex_review` отбит квотой — `weekly_quota_blocked`, полоса `luna` на 100%
при жёстком стопе 99%. По правилу замену ревьюеру не искал. Независимого мнения по этой
правке нет; всё, на чём она стоит, — проверки из §5 и §6.
