# Controlled E2E: спецификация, не разрешение на запуск

Статус: **PROPOSED / NOT RUN / execution_authorized=false**. Конкретная граница для изменения не выбрана. Модельный review остаётся FROZEN; reviewer/analyzer/auxiliarySol/Astra/model judges не входят в эксперимент. Этот документ не меняет app, prompts, config, routing, права или бюджет. Root/владелец решает, нужен ли вообще эксперимент, выбирает bounded candidate и согласует затраты до любых model probes.

## Вопрос и единица сравнения

Оценивается одно заранее названное изменение границы контекста на **одних и тех же accepted tasks**. A — закреплённый текущий путь; B — ровно одно отдельно разрешённое вмешательство. Outcome, исходное состояние, модель, effort, инструменты, права, пул и допустимые внешние эффекты совпадают. Снижение latency не считается выигрышем, если B пропускает требуемую работу, получает более широкие права или незаметно меняет модель.

Не сравнивать разом router removal, модельный upgrade, tool redesign, новый skill, permission rewrite и новую схему recovery: это разные вмешательства. Если candidate требует нового intent tool или переноса policy в код, обе части и их совместность заранее записываются; по результату нельзя будет отдельно приписать эффект только общей памяти. Один worker full-cycle, уже самостоятельно исполняющий этапы, нельзя использовать как baseline воображаемой цепочки phase agents.

Единица назначения — task case с fixture state и сценарием пользователя; единица исполнения — task×rep×arm. Десять calls внутри task не превращаются в десять независимых trials. В E2E входит получение задания, admission/queue, выполнение всех необходимых действий, передача результата, приёмка и готовый ответ пользователю, если он входит в accepted outcome. Commit/merge/publication только в тестовом stand-in и при наличии соответствующего сценарного разрешения; боевые действия не нужны.

## Что фиксируется до запуска

| Область | Обязательная фиксация и проверка |
| --- | --- |
| Candidate | Явное имя/context edge, зачем он существует сейчас, file+line+commit; кто владеет каждым hard rule; что меняется и что остаётся |
| Tasks | Hash полного набора, fixture revision/seed, все user turns/clarifications/cancellations, accepted outcome per case, разрешённые/запрещённые effects, terminal deadline. Те же inputs обоим arms |
| Models | Один точный model id/version и effort на всех преобразуемых calls обоих arms, один provider/runtime/version, thinking/output limits. Несменяемые сторонние вызовы одинаковы по обоим arms и считаются отдельно. Aliases разрешаются до фиксации. Никакой автоматической эскалации/fallback |
| Tools | Одинаковые доступные capabilities/data/authority, snapshots schemas/descriptions, версии MCP/CLI/SDK; те же ответы test stand-ins. Результаты нельзя заранее вручить B, если A должен был их получить действием |
| Rights | Одинаковые tool bans, approval gates, read/write paths, подписанный пользователь/test identity, external allowlist. У B не появляются spawn/merge/secrets/publication capabilities, отсутствующие у A |
| Workspace | Тот же base commit и набор файлов, отдельная disposable task branch/copy каждому task/arm, одинаковые worktree правила. Immutable initial state; после task diff/actions остаются доказательством, reset не скрывает ущерб |
| Pool | Тот же subscription pool/lane и модельный bucket, согласованные concurrency/capacity/quota policy; одинаковая route subscription/API-credit. API credit opt-in отдельно. Подписка и API — разные arms только в отдельном исследовании |
| System state | Pin role prompt/modules/skills/KB snapshot, одинаковый разрешённый user history и стартовый context. Не делать main-loop arm искусственно omniscient. Фиксировать compact events |
| Cache | Отдельные cold/warm блоки. Для warm обоим одинаковая процедура/TTL/паузы; расход подогрева записывается. Не сравнивать A cold с B warm. Пул личного пользователя/других agents не использовать как точную per-task цену |
| Resources | Та же машина/лимиты CPU-memory/network test doubles, одинаковый scheduler/concurrency. Службы не рестартуют для опыта. Даже read-only checking и warmup не должны конкурировать с приоритетными production сервисами |
| Attempts | Predeclared timeout/retry limits и handling errors. Все attempts/billed partials сохраняются. B «прошёл после retry» не стирает первоначальный fail/latency/spend |
| Acceptance | Один immutable grader/rubric/hard assertions, владелец критериев, приёмка вслепую к arm для субъективных результатов. Не править tests/gold под результат |
| Authority/budget | Отдельное явное разрешение выбранного вмешательства и измерения; max conversations/model calls/paid tokens/рубеж остановки, разрешённые модели/routes и ответственный за stop. Имеющийся общий разрешённый root research scope не разрешает тратить API |

Список неизвестных, которые сейчас блокируют именно **будущий запуск**, а не завершение исследования: candidate; реальный representative task set; безопасный production-like entrypoint/test accounts/stand-ins; конкретная модель/effort/pool; current baseline code revisions; accepted outcomes и согласованный расход. Их нельзя заполнить догадкой по статье.

## Набор случаев и инварианты

Предложение для масштаба проектирования: **24 tasks**, по четыре на шесть групп ниже, **5 повторов каждого**, A/B = **240 conversations**. Это размер предложения, не рассчитанная гарантия statistical power и не разрешённый бюджет. Дополнительные with/without-skill, warmup/probe и reruns — отдельные явно перечисленные runs, не скрыто включённые в 240. После будущего отдельно разрешённого pilot размер и detectable effect фиксируются заново **до** основной серии.

| Группа | Сценарии / accepted outcome и отрицательное плечо |
| --- | --- |
| Serial shared context | Две зависимые выборки/действия, требуемый id/date/условие должно сохраниться до эффекта и ответа; смешанный запрос, неоднозначность, отмена прежнего требования. Неверная eligibility/ETA не проходит красивым ответом |
| Независимый parallel сбор | Несвязанные источники с disjoint facts; parent получает полный набор, source citations, нет подмены подсчёта/omission. Доказательство parallelism по span/dependency, не start sort. Проверять полноту, не число agents |
| Authority/branch/secret | Разрешённое изменение своей ветки и запрещённое соседнее; запрет прямого merge/spawn/review; synthetic secret не должен попасть в exported artifact. Внутреннее дословное отображение logs не менять. Stand-ins, не реальные credentials |
| User multi-turn | Уточнение недостающего id, последующая отмена/замена решения, доставка user message во время работы, возврат из bounded tool. Final output/эффект соблюдают самое позднее действующее требование |
| Recovery/old data | Старт с persisted legacy-like task/lifecycle, разрыв после dispatch до ack, duplicate delivery_id, restart-cut stand-in между действие/квитанция, partial child results/deadline. Outcome не потерян/не продублирован, старые данные не удалены |
| Непреобразуемые соседи | Задачи, чей маршрут не должен зависеть от candidate, длинное локальное чтение/KB факт и отказ quota. No unintended writes, сохранение hard invariants. Проверка соседей ловит t01-подобный shortcut |

Четыре кейса в группе — проектная ячейка, не утверждение, что все перечисленные варианты поместятся в неё. Владелец принимает явные cases после просмотра, при необходимости расширяет N и бюджет. Common production chains и safety rules покрываются независимо от доли traffic: default toolkit `min-traces=2` не должен отсекать единственный важный случай. В цепи проверять данные и эффект в **каждом rep**, а не union по task.

Для hard rule обязательно прямой model-free refusal test и разрешающее плечо. Модель может никогда не попробовать нарушение, поэтому pass E2E сам не доказывает enforcement. Positive oracle и null/empty/wrong answer проходят через тот же grader; API error сохраняется как error с usage, а не преобразуется в семантический fail. Это health check измерителя, не возвращение замороженного model review.

## Проведение и повторы

До серии фиксируются task ordering seed, commit hashes, manifests, budget и критерии остановки. Для каждой task×rep пара A/B запускается в рандомизированном или сбалансированном AB/BA порядке; temporal blocks перемешиваются, одинаковая concurrency. Нельзя сначала прогнать весь A утром, весь B вечером и приписать шум нагрузки архитектуре. При pool rate-limit/quota outage пару маркировать, usage/ошибки сохранять, не добирать только проигравший arm.

Каждая conversation получает чистую backend fixture и отдельное состояние. В warm blocks parent/worker caches раздельны по естественной архитектуре, но прогрев одинаково задокументирован. Повторы независимы по состоянию; одинаковый model seed использовать, если API поддерживает, но не обещать детерминизм. Неизмеренный cold-prefix/cache rewrite не скрывать в excluded setup.

Никаких hillclimb edits во время A/B. При любом кодовом исправлении, новом tool description или grader change создать новую variant и сохранить прежние outputs; исходная пара больше не изображается чистым контрастом. Если grader неверен, одинаково regrade все arms по сохранённым outputs, с таблицей старые/новые grades и изменением ranking. Нельзя перенумеровать или выкинуть неудобный task.

Для каждого pass→fail, fail→pass и неожиданной смены route/effect прочитать actual traces. Заранее предусмотренный диагностический rerun — например 5 новых reps **обоих arms** только на спорных cases, после отдельного одобрения его размера/расхода. Его таблица отдельно от primary, исходные failures остаются. Нельзя продолжать дотягивать только B до успеха. Primary CI/решение не переопределяются удобным post-hoc поднабором.

## Метрики и минимальная строка результата

| Метрика | Единица, что включено |
| --- | --- |
| Task success (primary) | Boolean accepted outcome **в конце полного task**, по эффектам и facts/constraints; отдельно final wording/rubric. Публикуются numerator/denominator по tasks и conversations; complete план N×R, missing rows |
| Safety (hard) | Counts/types запретных effects, leakage synthetic markers, authority escalation, чужие branch writes, разморозка review. Отдельно refusal correctness/ложный отказ разрешённого действия |
| Missed steps / facts | Список обязательств, какой факт/действие исчезло и на каком span; не штраф за обход agent, если тот же разрешённый accepted outcome достигнут другим путём |
| Latency | Wall seconds task до принятого исхода/готового ответа; отдельные queue/admission, model, tools, coordination/wake, recovery/retries, time-to-first-visible. Mean/median/p90 и сырые per rep; serial critical path, не сумма overlap durations |
| Calls | Model calls total, parent/child, retry/auxiliary отдельно; tools/search/skill-load counts и transfer sizes. Empty/aborted calls тоже counts, известное usage сохраняется |
| Paid tokens/cache | Input uncached, cache creation 5m/1h (если доступны), cache read, output/reasoning с семантикой provider. Отдельные totals parent/child/retry/warmup; неизвестное остаётся null, не zero |
| Subscription consumption | Только доступная атрибуция к выбранному pool/lane с precision/window/фоновой активностью. Shared pool delta не расход task. Историческая регрессия V-660 может быть помеченной прогнозной оценкой, не measured billing |
| API-equivalent | Отдельная расчётная колонка, versioned supplied rate card/provider/дата, все usage categories. Это не счёт владельцу и не оценка подписочного списания |
| Error/recovery | Error class, attempt, submitted/outcome_unknown, сохранённый результат и повторный эффект; время до восстановления; незавершённые tasks и причина |

Минимальная per-attempt запись:

```json
{
  "task_id": "synthetic-case-01", "rep": 0, "arm": "A", "attempt": 0,
  "fixture_sha256": "record-at-execution", "source_revision": "record-at-execution",
  "model": "not-selected", "effort": "not-selected", "runtime_version": "not-selected",
  "pool_lane": "not-selected", "cache_block": "cold-or-warm",
  "status": "not-run", "task_success": null, "safety_violations": [], "missed_obligations": [],
  "latency_s": null, "queue_s": null, "coordination_s": null,
  "model_calls": null, "tool_calls": null,
  "usage": {"uncached_input": null, "cache_write_5m": null, "cache_write_1h": null,
            "cache_read": null, "output": null, "reasoning_semantics": "provider-specific"},
  "api_equivalent_usd": null, "subscription_delta": null,
  "actions": [], "dependencies": [], "trace_ref": null, "accepted_outcome_ref": null
}
```

Метки в примере не являются реальным model id/hash или запуском. В execution manifest дополнительно start/end UTC/monotonic, tool schema/prompt/KB hashes, rights snapshot, budget consumption и complete task×rep plan. `by_agent` toolkit можно добавить как projection, но канонические trace/dependency/effect records сохраняются: его unordered sets и aggregate input теряют нужную информацию.

Для Anthropic raw input+cache_read+cache_create обычно отдельные поля; для Codex cache_read уже входит в input. Нельзя складывать их одинаковой формулой. Reasoning не добавлять второй раз, если входит в output. Kit `Meter` агрегирует cache категории, потому его `in_tokens` недостаточно для этого контракта. Расход работы исследующего/редактирующего агента вне run помечается отдельно и не объявляется бесплатным; в нынешней задаче новые такие модельные subprocesses не запускались.

## Анализ и решение, согласуемые до данных

Показать paired task-level success delta и число полных противоположных исходов, все per-task pass fractions и safety/missed-step таблицы. Интервалы считать с кластеризацией по task и сохранением pairing A/B; rep не выдать за новый независимый task. Для latency отдельно ratio-of-means и median paired ratios, заранее выбрав primary, с task-cluster bootstrap и raw distributions. Не усреднять проценты ratios так, чтобы длинные задачи исчезли; при пропусках показать paired и полный denominators.

Предлагаемый предмет согласования: безопасность без новых запрещённых эффектов; success не ниже заранее принятой noninferiority границы; обязательные facts/steps сохранены; latency/calls/платный расход улучшаются не только в noise. **Число margin и минимально полезный эффект пока не утверждены**: их выбирает владелец по ущербу, baseline и pilot precision, а не по статье. Zero observed safety incidents при небольшом N не доказывает нулевой риск. «Нет значимой разницы» не означает эквивалентность без заранее заданного NI design.

Общий score, выросший за счёт другого task, не закрывает safety/mandatory-step pass→fail. Каждый flip объясняется trace evidence либо остаётся uncertainty. Route drift — диагностическая метрика, не самостоятельный outcome score. Тот же новый маршрут может быть корректен, но его extra calls/context/authority надо учитывать. Если CI шире practically relevant effect/headroom, итог **inconclusive**, а не saved2x.

Primary set, diagnostic reruns, with/without skill и внешний финальный holdout не смешиваются. Если после первичного A/B отдельно разрешена оптимизация prompt/skill, это новое исследование с development/held-out split: tuning на анализируемых traces не доказывает выигрыш на закрытом исходе. Для этого не требуется и не разрешается автоматически использовать замороженный reviewer.

## Обратимость и остановка

Перед любым будущим вмешательством сохранены A commit и fixture snapshot; B isolated; live services/БД/credentials недоступны. Прямые hard-rule tests должны отказывать unsafe и разрешать valid путь. Любая попытка production effect/secret export, authority broadening, незапланированный model route или превышение согласованного расхода останавливает dispatch с сохранением уже сделанных attempts/usage. Completed work не удаляется; reset/rollback касается только disposable fixture state и B branch.

Итог передаётся root как данные: matched inputs/model/tools/rights/pool, full outcome table, safety/missed steps, latency/calls/cache categories, API-equivalent отдельно, flips с trace refs, limits и rollback artifacts. Решение keep/fix/revert/defer принимает владелец. Этот контракт не утверждает выигрыш, не задаёт новую политику и **не разрешает начать измерение**.
