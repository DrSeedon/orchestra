# #251 — Grok 4.6: безопасность, X-поиск, очная ставка и интеграция

Дата: 2026-08-13. Контур: Grok Build по подписке `grok.com`; API-ключи не используются.

## Вопрос и критерий решения

- **Контекст:** Grok рассматривается как третий независимый пул, прежде всего ради доступа к
  первичным постам X, которых обычный веб-контур Orchestra не читает.
- **Изменение:** зарегистрировать `grok-4.6`, но удалить 4.5 только при измеренном перевесе 4.6
  на одном и том же X-задании; одновременно закрыть все обнаруженные исходящие каналы CLI.
- **Контроль:** `grok-4.5` и `grok-4.6` в одном `/usr/bin/grok` 1.0.3, под одним аккаунтом,
  конфигом, effort и корпусом; telemetry-проверка имеет разрешающее плечо, которое обязано
  реально отправить событие.
- **Решающий исход:** проверяемый X-result (permalink, автор, время, содержание, native X tool),
  затем собственный шум метрики. Красивый ответ и публичные benchmark-заявки сами по себе не
  являются правилом допуска.

## Гипотезы и фальсификаторы

1. **H1: 4.6 следует заменить 4.5, потому что она лучше на X retrieval.** Опровергается,
   если перевес меньше `+1/10`, не превосходит собственный шум, либо 4.6 регрессирует по
   permalink/фабрикации/native X results. **REFUTED** на 18 предзарегистрированных ходах.
2. **H2: подписочный CLI умеет читать X нативно.** Опровергается, если адресный fetch
   заведомо существующего поста не вызывает успешный `x_*` tool. **CONFIRMED**: 18/18 ходов
   имеют успешный native X tool, включая адресный `x_thread_fetch`.
3. **H3: выключенные ключи telemetry реально закрывают канал, а не только меняют конфиг.**
   Опровергается, если тот же локальный collector, который принимает product analytics и
   external OTEL в positive control, получает хотя бы один запрос из production-env.
   **CONFIRMED**: positive control принял `/events`, `/v1/logs`, `/v1/metrics`;
   production-env — ноль запросов.
4. **H4: итоговый `turn_completed.usage` — полная provider billing truth тяжёлого X-хода.**
   Опровергается расхождением с опубликованной формулой либо account delta. **UNCERTAIN**:
   одна из 18 сверок расходится на $0.05; точный account delta текущая подписка не раскрывает.

## 1. CLI и живой каталог

На VPS под `kesha` измерено:

```text
command -v grok  -> /usr/bin/grok
grok --version   -> grok 1.0.3 (1a29d5bc12) [stable]
grok models      -> Default model: grok-4.6; available: grok-4.6, grok-4.5
HOME             -> /home/kesha
user config      -> /home/kesha/.grok/config.toml (0644, kesha:kesha)
auth.json        -> 0600, kesha:kesha
```

**CONFIRMED — прямой замер.** Все 18 headless-ходов по явному `--model grok-4.5|grok-4.6`
завершились с rc=0. Это доказывает доступ обеих моделей текущему аккаунту в момент замера.

Наблюдавшееся в течение пяти минут «исчезновение 4.6» было не плавающим rollout провайдера.
Эксперимент показал: `[features] remote_fetch=false` отключает онлайн-каталог, после чего CLI
показывает статический fallback только с 4.5; удаление этого ключа немедленно возвращает 4.6
во всех worktree. **CONFIRMED — воспроизведено обеими ветвями.** `remote_fetch` оставлен
включённым: это control plane модели, а не telemetry.

Отсюда архитектурное разделение:

- `app/models.py` — статический реестр разрешённых Orchestra routes: runtime, provider,
  context и aliases;
- `grok models` — живой каталог доступности конкретного аккаунта;
- значение `model:` в `pipelines/default/pipeline.yaml` выбирает модель роли и ничего не
  регистрирует.

Статический реестр не должен обещать доступность провайдера. Приёмка новой модели требует
живого каталога и spawn; превращать весь реестр Orchestra в результат `grok models` нельзя,
потому что реестр также является локальным allowlist и хранит свойства маршрута.

## 2. Что из анонса Grok 4.6 подтверждено

Официальный анонс xAI от 12.08.2026 подтверждает: Intelligence Index 61 против 61 у Sol;
CursorBench 69.9% против 67.2%; FrontierCode 61.3% против 60.6%; AA-Briefcase 1577 против
1502; доступность в Cursor, Grok Build, API и других партнёрах; двойной included usage в
первую неделю только внутри Cursor и Grok Build [1]. Утверждение пересказа именно про
доступность в **Grok Bot** этим анонсом не подтверждено: там названы Cursor, Build, API и
партнёры, но не Bot. **CONFIRMED / одна первичная таблица; внешний независимый прогон бенчей
не воспроизводился.**

Контр-срез из той же таблицы важнее headline для Orchestra: 4.6 проигрывает Sol в DeepSWE
65.9% против 73% и Terminal-Bench 26% против 34.6% [1]. Значит 61 общего индекса не доказывает
преимущество в длинном shell/tool-loop.

Официальная pricing-таблица сохраняет порог `>=200k` и удваивает **все** token rates запроса:

| модель | `<200k`: input / cached / output | `>=200k`: input / cached / output |
|---|---:|---:|
| grok-4.5 | $2 / $0.30 / $6 | $4 / $0.60 / $12 |
| grok-4.6 | $2 / $0.50 / $6 | $4 / $1.00 / $12 |

xAI отдельно указывает $5/1000 X Search calls [2]. **CONFIRMED двумя уровнями:** первичная
дока [2][3] и 18 живых usage traces. В trace token-компонент сходится с обычным тарифом при
prompt `<200k` и с удвоенным при `>=200k`; исключение одной строки на $0.05 относится к
числу X calls, не к token-тарифу. 500k остаётся платным преимуществом, а cached-rate 4.6
на 67% выше 4.5.

## 3. Телеметрия: что закрыто и чем это доказано

Vendor README перечисляет независимые product analytics, feedback, trace upload и
Mixpanel; env имеет приоритет над config [4]. Отдельная vendor-дока подчёркивает, что external
OpenTelemetry независима от product telemetry и отдельно гейтится `GROK_EXTERNAL_OTEL` плюс
экспортерами [5]. `grok trace --help` показывает, что upload — явная подкоманда; `--local`
принудительно оставляет экспорт локальным. Автоматического запуска `trace` не обнаружено,
но его default без защиты допускает upload.

### Уже действует для прямого CLI

В `/home/kesha/.grok/config.toml` выключены:

- `[features] telemetry`, `feedback`, `codebase_indexing`;
- `events_url`, `events_api_key`, `mixpanel_token`, `mixpanel_enabled`;
- `trace_upload`;
- external OTEL master/exporters и content gates (`otel_log_user_prompts`,
  `otel_log_tool_details`).

У аккаунта измерен `coding_data_retention_opt_out=true`. Значения credentials не читались и
не выводились.

### После merge + рестарта для managed workers

`app/backend_grok.py` генерирует те же hard-off значения в изолированном `GROK_HOME`, а
`_build_env()` **после** host/MCP env переписывает все master switches, OTEL exporters и
`SENTRY_DSN`. Это защищает worker даже от унаследованного или переданного MCP окружения.

### Проверка, различающая успех и провал

На одном локальном HTTP collector `127.0.0.1:18766`:

```text
POSITIVE_CONTROL: rc=0; POST /events x19, /v1/logs x2, /v1/metrics x1
PRODUCTION_ENV:   hostile host/MCP values + GrokBackend._build_env() -> rc=0, 0 requests
```

То есть collector доказан принимающим; пустой production-result не может объясняться мёртвым
стендом. Positive и negative плечи запускали один и тот же реальный single-turn Grok, а не
только `grok models`; значит сгенерированный TOML также прошёл парсинг и model call завершился.
Воспроизводимый probe и санитизированный результат: `telemetry_probe.py`,
`telemetry-proof.json`. Дополнительно `grok trace <pilot-session>` запускался **без** `--local`, с hardened
env под `strace`: архив 207756 B создан локально, сетевых `connect()` нет. **CONFIRMED — прямой
wire measurement с разрешающим плечом.** Это доказывает закрытие известных каналов 1.0.3;
неизвестный будущий канал новой версии потребует повторного vendor-config scan.

## 4. Очная ставка 4.6 против 4.5 на X

Предрегистрация и порог заморожены до прогонов в `prereg.md`. Три задания, обеим моделям
побайтно один prompt, по три fresh session: 18 ходов. A — адресный fetch известного треда;
B — account/keyword discovery известного поста Artificial Analysis; C — semantic discovery.
Шкала 10 баллов и правило удаления: перевес 4.6 не меньше `+1.0`, строго больше медианного
собственного шума, ноль фабрикаций, A>=8 во всех повторах и не меньше успешных X results.

| метрика | grok-4.5 | grok-4.6 | 4.6 - 4.5 |
|---|---:|---:|---:|
| mean score, A+B+C | **7.56** | 7.11 | **-0.44** |
| mean score, только однозначные A+B | **9.33** | 8.67 | **-0.67** |
| exact permalink, A+B | **4/6** | 2/6 | -2 |
| native X success | 9/9 | 9/9 | 0 |
| strict JSON | **4/9** | 0/9 | -4 |
| completed X calls | **47** | 66 | +19 |
| median wall time | **34.616 s** | 44.977 s | +30% |

Score vectors: 4.5 = `[10,10,10,10,8,8,4,4,4]`; 4.6 =
`[8,10,10,8,8,8,4,4,4]`. Медианный собственный шум шкалы = 0. Порог удаления не пройден.
**CONFIRMED — прямой парный замер:** 4.6 не лучше 4.5 на причине допуска; 4.5 остаётся,
aliases `grok`/`grok-build` не переключаются.

Scorer написан после выполнения ходов, но реализует замороженные до прогонов точные anchors,
URL ids и timestamp arithmetic без модельного судьи; native tool points читаются только из
`tool_call_update`, поле `tools_used` ответа не используется. Пункт, названный в prereg
«нет фабрикации», воспроизводимо проверяет более узкое свойство — отсутствие структурного
противоречия URL/snowflake/timestamp. Полную достоверность скрытого tool-result body он не
доказывает; scorer явно сохраняет `fabrication_check_complete=false`, поэтому threshold не
может пройти даже гипотетически. В фактических данных он провален ещё раньше по отрицательной
дельте.

Обе модели действительно умеют нативный X: в trace видны `x_thread_fetch`,
`x_keyword_search`, `x_semantic_search`; адресный A успешен 6/6. В B все шесть ходов вызвали
`x_thread_fetch` с правильным `post_id=2087564648325530099`, хотя финальный ответ часто
опускал URL. Это отделяет качество retriever от качества formatter.

**Ограничение C:** формулировка оказалась неуникальной; обе модели нашли несколько более
новых реальных постов `@grok` с тем же смыслом. Замороженный exact-target score сохранён, но
C не используется как discriminator. Вывод сохраняется на A+B. Raw traces, scoring и
timings: `raw/`, `score.json`, `score_bench.py`.

## 5. Учёт расхода: доказанный механизм и границы находки

Путь данных в Orchestra однозначен:

1. `app/backend_grok.py:_turn_completed()` сохраняет последний ACP `usage` в
   `_pending_usage`; `_turn_end_event()` превращает его в один `TurnUsage` и один
   `cost_usd`.
2. `app/session_turns.py:handle_turn_end()` один раз вызывает `CostTracker` и
   `turn_usage_add()`.
3. `app/db.py:turn_usage_add()` пишет одну строку `turn_usage` на provider event id.
4. `app/usage_analytics.py` считает наблюдённый расход из `turn_usage.cost_usd`.

Второго источника, который суммирует промежуточные внутренние model/tool batches, нет.
**CONFIRMED — полный кодовый trace до аналитики.**

На 18 ходах: 113 completed `x_*` calls, 19 разных X batch-id, но `modelCalls=18` и 18
`turn_completed`. Сумма reported cost = **$8.2302408**. Если каждый completed X call биллится
по опубликованным $0.005, формула даёт **$8.2802408**: 17/18 строк сходятся в ноль, одна
расходится на **-$0.05**. Это $0.05 / $8.23 = **0.6%**, и только условная нижняя граница при
допущении, что все десять ранних completed calls второго batch действительно billable.

Следовательно, общее утверждение «Grok у нас занижается везде» **не доказано**. Доказан более
узкий механизм риска: один `turn_completed` становится одной строкой `turn_usage`, а одна
тяжёлая trace содержит два X batch и только один terminal usage; ни analytics, ни dashboard
не имеют второго provider source. Чем больше таких скрытых batches, тем потенциально больше
ошибка, но её масштаб за пределами этих 18 ходов неизвестен. Это тот же класс, что #175:
одноимённое поле стоимости не гарантирует одинаковую семантику двух runtimes.

Точный provider truth получить нельзя: текущий `GET /v1/billing` вернул
`monthlyLimit=0, used=0`; unified log даёт только округлённые `creditUsagePercent=8.0` и
недельное окно без числителя. Старые 20 000 modelCalls в #95 относятся к другому аккаунту и
тарифу и не переносятся. **CONFIRMED:** billing delta и ёмкость третьего пула в рабочих ходах
сейчас неизвестны.

Отозванный headline: из reported totals получалось, что 4.6 дороже 4.5 на 66%. Эту цифру
нельзя использовать: discrepancy находится на стороне 4.5, provider billing truth отсутствует,
а модели совершили разное число tool calls. Качественный вердикт 4.5 > 4.6 держится на score,
permalink, format, calls и wall time, не на долларах.

Fallback `_grok_cost()` **не переведён** на long-context tier: ACP даёт агрегат хода, а
опубликованный порог применяется к отдельному model request; multi-call ход может смешать
тарифы. Поэтому `costUsdTicks` остаётся единственным точным источником. Если ticks отсутствует,
fallback по-прежнему считает только short-tier tokens и не знает X calls — это известное
занижение, выбранное вместо ложной точности до появления per-request usage.

## 6. Настройки на ноутбуке — read-only сверка

Через reverse SSH прочитан только конфиг, ничего не запускалось тяжёлого и ничего не менялось:

```text
host: maxim-911aird
login-shell grok: 0.2.112 (9bbd559437)
~/.grok/config.toml: 0664 maxim:maxim
[features] telemetry=false
[telemetry] trace_upload=false, mixpanel_enabled=false, otel_enabled=false
telemetry/OTEL/Sentry env names: none
```

На ноуте дополнительно стоят UI/installer/marketplace параметры (`auto_update`,
`permission_mode=always-approve`, `fork_secondary_model=grok-4.5` и др.). Они не относятся к
утечкам и не перенесены на VPS. Полезная часть — три независимых telemetry-off — уже закрыта
на VPS шире (analytics, feedback, indexing, trace, Mixpanel, external OTEL, Sentry) и
продублирована hard pin в backend. В non-login SSH PATH ноутбука `grok` не виден; login zsh
его разрешает. Это свойство ноутбука, не VPS.

## 7. Регистрация и правило допуска третьего пула

`grok-4.6` добавлена в `MODELS`, `CONTEXT_LIMITS`, `BACKENDS`, `MODEL_PROVIDERS` и явный alias
`grok4.6`; цены остаются **вне** общего `TOKEN_PRICES`. Контекст 500k и обе cache rates
закрыты живыми traces. Регистрация не активирована: Python-реестр импортирован в долгоживущий
процесс. После общего рестарта нужна отдельная Orchestra spawn-проба, которая должна доказать
создание сессии и первый завершённый ход. До неё spawn не помечается ни PASS, ни FAIL.

Черновик admission rule, исходя из измеренного назначения отдельного пула:

1. **Разрешить адресный X retrieval** по известному permalink/account; основной route пока
   4.5. Требовать успешный `x_thread_fetch` и возвращать permalink + timestamp + дословный
   fragment. Если финальный URL потерян, reconstruct из фактического `post_id` trace.
2. **Разрешить keyword/account discovery как retriever**, но не принимать финальный prose без
   проверки каждого permalink/времени. В measured B нужный post найден 6/6, URL в ответе —
   только 2/6 у 4.6 и 2/3 у 4.5.
3. **Semantic discovery считать exploratory candidate list**, не доказательством «того самого
   поста» или тренда: C показал неуникальность ground truth.
4. **Не допускать синтез тренда/мнения по X без воспроизводимой выборки.** Текущий trace скрывает
   tool-result bodies, поэтому дословность содержательного fragment должна проверяться отдельно.
5. **Не сливать в Grok общий кодовый/full-cycle поток только ради свободного пула.** Этот тест
   измерял X retrieval, публичный Terminal-Bench у 4.6 хуже Sol, а ёмкость подписки неизвестна.
6. Перед spawn сверять модель с живым каталогом; статический registry — разрешение маршрута,
   не гарантия provider availability.

Это шире прежнего `retriever-only` лишь в discovery-внутри-X. Отдельный кошелёк повышает
ценность доступности, но не превращает непроверенные классы работы в разрешённые.

## 8. Что действует сейчас, а что ждёт рестарта

| Изменение/факт | Статус |
|---|---|
| официальный CLI 1.0.3, auth подписки, прямые 4.5/4.6 ходы | **действует сейчас** |
| user-level telemetry config и account retention opt-out | **действует сейчас для прямого CLI** |
| X capability и side-by-side verdict «4.5 остаётся» | **измерено, рестарта не требует** |
| `grok-4.6` в Orchestra registry | **нужен merge + общий рестарт** |
| managed-worker telemetry hard pin | **нужен merge + общий рестарт/новый backend process** |
| short-tier fallback `_grok_cost()` | **без изменения; long/multi-call остаётся неточным** |
| Orchestra spawn 4.6 и первый завершённый ход | **не проверены; только после рестарта** |
| удаление 4.5 / переключение aliases | **не делать: порог удаления провален** |

## Риски и затронутые файлы

- `app/models.py`: новый route загружается только рестартом; alias `grok` намеренно остаётся
  на 4.5.
- `app/backend_grok.py`: telemetry hard pins; fallback без runtime ticks не знает per-request
  tier и X calls, поэтому намеренно не объявлен точным.
- `tests/test_backend_grok.py`: route, provider, context, cached rates, telemetry hostile env
  и обе стороны порога 200k.
- `docs/grok-field-guide.md`: live 4.6, тариф и текущая невозможность exact billing.
- `docs/tasks/251/raw/`: 18 NDJSON traces; перед коммитом shape-scan по token/private-key
  паттернам дал ноль совпадений.

## Источники

1. [xAI, Introducing Grok 4.6, 12.08.2026](https://x.ai/news/grok-4-6) — первичный анонс и
   self-reported benchmark table.
2. [xAI pricing](https://docs.x.ai/developers/pricing) — первичная таблица обеих моделей,
   long-context rule и X Search tariff.
3. [xAI Grok 4.6 model card](https://docs.x.ai/developers/models/grok-4.6) — первичная карточка:
   500k, cached $0.50, higher-context pricing.
4. `/home/kesha/.grok/README.md:1349-1383` из установленного CLI 1.0.3 — vendor primary:
   product telemetry/feedback/sinks/env precedence.
5. `/home/kesha/.grok/docs/user-guide/24-monitoring-usage.md:14-112` — vendor primary:
   independent external OTEL and content gates.
6. `docs/tasks/251/prereg.md`, `score.json`, `usage-reconciliation.json`, `raw/*.jsonl`,
   `telemetry-proof.json`, `laptop-config-sanitized.md` —
   direct measurements, strongest tier.
