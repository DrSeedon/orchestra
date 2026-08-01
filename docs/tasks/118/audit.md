# #118 — аудит промптов Orchestra

Дата: 2026-08-01. Область: `pipelines/default/prompts/`,
`pipelines/tasks-pm/prompts/`, корневой `CLAUDE.md`, а также статически собранный
промпт каждой роли. Правки в промпты и код не вносились.

## Статус исправлений

`tasks-pm` удалён после аудита: P1-11—P1-15 и P2-28—P3-32 закрыты удалением и ниже
сохранены только как исторические доказательства, не как задачи на несуществующие файлы.
P0-1 и P0-2 закрыты отдельно. Остальные пакеты перечислены в актуальном порядке внизу.

## Вердикт

Промпты требуют не косметической полировки, а поэтапной санации контрактов. Основной
`default`-пайплайн работоспособен, но в нём есть два потенциально разрушающих контракта
(единицы платежей и переполнение `CLAUDE.md`) и несколько пар правил, из-за которых
оркестратор и воркер ожидают разные гейты и ревью. `tasks-pm` фактически законсервировал
старый рантайм: в БД нет ни одной сессии с `pipeline='tasks-pm'`, а его правила расходятся
с текущими моделями, доступом к агентам, background jobs, тестами и lifecycle.

Это не случай «слишком много текста». Проблема — несколько источников истины и правила,
стоящие в разных слоях собранного промпта. Модель обычно выбирает более близкий,
конкретный или удобный маршрут, а не тот, который автор считал главным.

## Как проверялось

- Прочитаны все Markdown-файлы в обоих каталогах промптов и текущий `CLAUDE.md` из
  `main`.
- Промпты собраны через реальный `build_system_prompt()`; порядок сборки подтверждён в
  `app/pipeline.py:427-460`: сначала `base + role + pipeline layer`, затем модули.
- Динамика сверена с `ROLE_SYSTEM_PROMPT()` (`app/manager.py:195-225`), инъекцией
  персональной памяти (`app/manager.py:435-444,1138-1157`) и индексом Codex-скиллов
  (`app/runtime_registry.py:185-216`).
- Протухшие инструкции сверены с реализацией `spawn_worker`, `merge_worker`,
  `codex_review`, ownership, auto-report и branch resolution.
- Частота ролей измерена по `data/orchestra.db`: `default/worker` — 185 сессий,
  `default/full-cycle` — 143, `default/orchestrator` — 16,
  `default/sub-orchestrator` — 2; `tasks-pm` — 0.
- Приоритет ниже — оценка **частота × ущерб**. `P0` требует первого исправления, `P1` —
  следующий пакет, `P2` — плановая санация, `P3` — удаление шума/неисполняемых правил.

## Собранные промпты

Размеры ниже — статическая сборка без динамического списка живых агентов и без тела
skills (Claude загружает skill по триггеру; Codex получает короткий индекс). `CLAUDE.md`
наследуется отдельно.

| Pipeline / роль | Слои | Статический размер |
|---|---|---:|
| default / orchestrator | base + role + 6 modules | 35 525 B / 535 строк |
| default / sub-orchestrator | base + role + 5 modules | 34 795 B / 518 строк |
| default / worker | base + role + 4 modules | 17 893 B / 301 строк |
| default / full-cycle | base + role + 5 modules | 30 827 B / 501 строк |
| tasks-pm / base-orchestrator | base + role + `_pipeline` | 17 785 B / 166 строк |
| tasks-pm / pm-glava | base + role + `_pipeline` | 19 648 B / 162 строк |
| tasks-pm / pm-fichi | base + role + `_pipeline` | 21 689 B / 168 строк |
| tasks-pm / analyst | base + role + `_pipeline` | 18 447 B / 143 строк |
| tasks-pm / coder | base + role + `_pipeline` | 16 457 B / 132 строк |
| tasks-pm / tester | base + role + `_pipeline` | 19 257 B / 155 строк |
| tasks-pm / secretary | base + role (без `_pipeline`) | 12 599 B / 163 строк |
| tasks-pm / worker | base + role (без `_pipeline`) | 6 615 B / 54 строки |

`CLAUDE.md` в `main` — **32 748 B**, то есть до стандартного лимита Codex
`project_doc_max_bytes=32 768` осталось **20 B**. Раздел «Грабли» занимает 18 016 B,
или 55,0% файла.

## Находки

### P0-1 — следующий append в `CLAUDE.md` обрежет инструкции Codex

- **Места:** `pipelines/default/prompts/modules/orchestration.md:223-234` требует перед
  каждым compact писать session notes в `CLAUDE.md`; `CLAUDE.md:148-150` фиксирует, что
  Codex режет файл на 32 KiB посреди фразы. Текущий замер: 32 748 из 32 768 B.
- **Несовместимость:** обязательный постоянно растущий append и жёсткий потолок оставляют
  запас меньше одного короткого русского предложения.
- **Выбор агента:** выполнит свежую инструкцию `MANDATORY` и допишет файл; байтовый предел
  из project doc не является локальным stop-condition перед записью.
- **Последствие:** следующий compact/урок с высокой вероятностью отрежет хвост `AGENTS.md`
  посреди правила для каждого Sol-воркера. Ошибка молчаливая: тесты промптов остаются
  зелёными, а поведение «вдруг» откатывается к старому.
- **Предложение:** немедленно ввести byte-budget test; task/session state хранить в
  `docs/tasks/` и task manager, а из `CLAUDE.md` вынести историю. Само правило pre-compact
  должно запрещать append при исчерпанном бюджете.

### P0-2 — платежи и цены имеют две единицы, ошибка равна ×1000

- **Места:** `pipelines/default/prompts/modules/orchestration.md:74-76` говорит «prices/
  amounts in thousands»; `pipelines/default/prompts/modules/task-management.md:6-12`
  требует exact currency units. Оба модуля входят в собранный prompt оркестратора.
- **Несовместимость:** `20` означает одновременно 20 000 и 20 рублей.
- **Выбор агента:** вероятнее возьмёт более поздний `task-management` для вызова самого
  тула, но примеры/рассуждение о цене может взять из более раннего orchestration; маршрут
  зависит от того, какую секцию он вспомнит.
- **Последствие:** неверная цена задачи или запись платежа в 1000 раз меньше/больше;
  автодистрибуция затем разнесёт ошибку по закрытым задачам.
- **Предложение:** оставить exact units единственным контрактом рядом с tools. Код это
  подтверждает: `app/mcp_stdio.py:677-704,755-766` и поля `price_rub` в `app/tm.py`.

### P1-3 — оркестратор пропускает первый гейт full-cycle

- **Места:** `pipelines/default/prompts/modules/orchestration.md:31-39` описывает один
  непрерывный маршрут «research → plan → Codex → один plan approval → implementation»;
  `pipelines/default/prompts/roles/full-cycle.md:27-42,44-76` требует отдельные
  `RESEARCH DONE` и `PLAN READY` с двумя STOP-гейтами.
- **Несовместимость:** родитель ждёт первый отчёт только после плана, ребёнок обязан
  остановиться до планирования.
- **Выбор агента:** full-cycle обычно следует собственному нумерованному pipeline, а
  оркестратор — своей схеме. Они оба «правы» в своих собранных промптах.
- **Последствие:** лишний round-trip и зависшая задача либо явная команда «сделай сразу
  research+plan», обходящая одобренный гейт. Это объясняет непредсказуемость фаз, а не
  слабость модели.
- **Предложение:** в orchestration оставить только три события контракта:
  `RESEARCH DONE → approve`, `PLAN READY → approve`, `DONE`; детали — только в роли.

### P1-4 — task закрывается одновременно на DONE и после merge

- **Места:** `pipelines/default/prompts/modules/task-management.md:14-18` требует
  `Worker DONE → status=done`; тот же файл `:20-24` требует закрывать только после merge,
  потому что merge может упасть.
- **Несовместимость:** один event имеет два разных перехода состояния.
- **Выбор агента:** скорее выполнит ранний конкретный workflow сразу при DONE; позднее
  правило легко уже не проверить.
- **Последствие:** task показывает `done`, пока ветка не смержена; конфликт/грязный target
  оставляет ложнозакрытую работу и ломает отчётность/платежи.
- **Предложение:** единственный переход `successful merge → done`; worker DONE означает
  `awaiting_merge` либо остаётся `in_progress`.

### P1-5 — medium flow отменяет обязательное shared-runtime ревью

- **Места:** `pipelines/default/prompts/modules/orchestration.md:41-45` говорит medium
  worker «No plan, no Codex»; `pipelines/default/prompts/roles/worker.md:52-60` требует
  Codex для любого diff shared runtime независимо от размера.
- **Несовместимость:** однострочная правка очереди одновременно «без Codex» и «Codex
  mandatory».
- **Выбор агента:** родитель может прямо повторить `no Codex` в task; worker либо подчинится
  свежему task, либо потратит неожиданный раунд и нарушит ожидания родителя.
- **Последствие:** именно самые рискованные маленькие правки message/session/lock уходят
  без второго мнения либо pipeline зависает на незапланированном review.
- **Предложение:** medium flow должен ссылаться на единый review-decision: без плана;
  Codex — по shared-runtime/complexity gate роли.

### P1-6 — fail-loud отправляет баги проекта в platform `BUGS.md`

- **Места:** `CLAUDE.md:109-115` требует при любой ошибке `STOP + report_bug`, а
  `pipelines/default/prompts/modules/orchestration.md:247-259` и
  `pipelines/default/prompts/roles/full-cycle.md:85-86` разрешают `report_bug` только для
  Orchestra platform, не для кода проекта.
- **Несовместимость:** обычный failed test одновременно является «любой ошибкой» и
  категорически не platform bug.
- **Выбор агента:** `CLAUDE.md` использует абсолютные «любая»/«STOP» и выглядит как
  проектный верхний приоритет, поэтому модель склонна репортить до классификации.
- **Последствие:** задача преждевременно останавливается, а `report_bug` пачкает рабочий
  checkout `BUGS.md`; известное следствие уже записано в `CLAUDE.md:185-187` — грязный
  файл блокирует все merge.
- **Предложение:** fail-loud сначала механически классифицирует источник: platform →
  `report_bug`; task code → тест/`docs/tasks/<id>/` + родитель, без глобального STOP.

### P1-7 — worker одновременно обязан и не имеет права создавать subagent

- **Места:** `pipelines/default/prompts/base.md:36-42,49-52` запрещает built-in Agent,
  советует large exploration отдать subagent; `pipelines/default/prompts/roles/worker.md:4-10`
  запрещает worker управлять агентами.
- **Несовместимость:** для большой инспекции у worker нет разрешённого маршрута: Agent
  запрещён, `spawn_worker` запрещён, но subagent предписан.
- **Выбор агента:** Sol чаще следует critical-запрету и делает всё сам; другая модель
  может вызвать недоступный/неразрешённый Agent по более конкретному совету context economy.
- **Последствие:** крупные аудиты переполняют один контекст или воркер создаёт ребёнка без
  lifecycle/ownership, которого не имеет права закрывать.
- **Предложение:** сделать строку про subagent role-aware: только orchestrator/full-cycle;
  обычный worker при выросшем scope эскалирует родителю.

### P1-8 — у research-задачи четыре разных «первых действия»

- **Места:** `pipelines/default/prompts/modules/memory-search.md:4-8` — search_memory до
  первого Read/Grep; `pipelines/default/prompts/roles/worker.md:17-23` и
  `roles/full-cycle.md:19-23` — сначала `pwd`/чтение кода; `modules/research-method.md:8-38`
  — сначала frame + hypotheses; `CLAUDE.md:122-126` — при старте сначала BUGS.md.
- **Несовместимость:** все команды названы стартовым обязательным порядком, но общего
  порядка между ними нет.
- **Выбор агента:** следует первому нумерованному списку своей роли, потому что он выше
  модулей в собранном prompt; memory-search снова становится опциональным на практике.
- **Последствие:** повторяются прошлые исследования и грабли — ровно тот measured failure,
  ради которого memory-search переписывали; либо гипотеза формируется до извлечения уже
  принятого решения.
- **Предложение:** один pre-work pipeline, например `pwd → memory → frame → targeted code`;
  `BUGS.md` — только когда задача про platform/старт root-session.

### P1-9 — «можно рестартить самому» стоит рядом с «нельзя без команды»

- **Места:** `CLAUDE.md:54-56` говорит, что sudo без пароля и сервер «можно рестартить
  самому»; следующая строка запрещает самостоятельный restart без явной команды.
- **Несовместимость:** capability сформулирована как authorization.
- **Выбор агента:** при проверке Python-правки выберет удобное «можно», особенно если
  restart нужен для доказательства результата.
- **Последствие:** активные turns прерываются; сама строка `CLAUDE.md:56-57` признаёт этот
  эффект. Это production-like действие без согласия.
- **Предложение:** оставить «sudo технически доступен, но authorization только явная команда»
  одной фразой; убрать глагол «можно».

### P1-10 — deploy skill сам создаёт разрешение, которого проект не давал

- **Места:** `CLAUDE.md:58` запрещает VPS pull/restart без команды пользователя;
  `pipelines/default/prompts/skills/vps-deploy.md:10-14` включает триггер «after merging
  important fixes needed on prod» без пользовательской команды.
- **Несовместимость:** важность фикса подменяет approval.
- **Выбор агента:** при срабатывании skill воспринимает `When to use` как локальную
  процедуру и deploy'ит сразу после merge.
- **Последствие:** несанкционированный `git pull + systemctl restart` production на
  hardcoded host; активные пользователи получают новый код без ручной приёмки.
- **Предложение:** единственный trigger skill — дословная команда пользователя на deploy;
  «important fix» не даёт полномочий.

### P1-11 — tasks-pm одновременно запрещает и разрешает full suite

- **Места:** `pipelines/tasks-pm/prompts/base.md:38-41` сначала говорит «НИКОГДА» не
  запускать full suite, затем описывает обязательный test lock перед таким прогоном;
  `pipelines/tasks-pm/prompts/roles/coder.md:11-15` разрешает его с PM approval + lock.
- **Несовместимость:** даже одобренный прогон остаётся нарушением глобального NEVER.
- **Выбор агента:** часть моделей остановится на более сильном NEVER; часть выберет
  поздний конкретный рецепт с lock.
- **Последствие:** релиз остаётся без требуемой интеграционной проверки либо перегревает
  машину прогоном, который автор base хотел запретить.
- **Предложение:** один gate: `узкие всегда; full suite только explicit PM approval + load
  check + global lock`, иначе запрещён.

### P1-12 — terminal secretary имеет два противоположных workflow

- **Места:** `pipelines/tasks-pm/prompts/roles/secretary.md:11-15` запрещает commit и детей;
  тот же файл `:88-104` требует commit и разрешает subagents/Task, а `:106-109` снова
  предписывает subagent для 20 файлов.
- **Несовместимость:** terminal worker должен одновременно коммитить/не коммитить и
  создавать/не создавать детей.
- **Выбор агента:** вероятнее выполнит поздний нумерованный workflow и попробует Agent,
  хотя текущая platform policy built-in Agent блокирует.
- **Последствие:** отчёт либо остаётся незакоммиченным и теряется при cleanup, либо ход
  падает на недоступном инструменте; родитель ждёт материал, которого физически нет.
- **Предложение:** выбрать один маршрут: secretary terminal, читает сам, коммитит свои
  `_secretary`-артефакты; крупный fan-out делает родитель.

### P1-13 — tasks-pm даёт workers межпроектные полномочия

- **Места:** `pipelines/tasks-pm/prompts/base.md:17-23` разрешает всем агентам
  `list_orchestrators()` и cross-project messaging; актуальный контракт
  `pipelines/default/prompts/base.md:14-25` разрешает это только orchestrators, workers
  репортят своему родителю.
- **Несовместимость:** один и тот же worker capability зависит от выбранного pipeline,
  хотя MCP/изоляция одна.
- **Выбор агента:** secretary/worker tasks-pm увидит только разрешающую копию и может
  писать чужому оркестратору напрямую.
- **Последствие:** обход родителя, утечка контекста между проектами и неучтённая
  межпроектная задача.
- **Предложение:** вынести platform base в один общий source; worker-ограничение должно
  быть одинаковым для всех pipelines.

### P1-14 — tasks-pm маршрутизирует каждый рабочий этап в старый Claude-пул

- **Места:** `pipelines/tasks-pm/prompts/_pipeline.md:5-9` требует Opus для всех
  orchestration/analysis/coding workers и Haiku для рутины; `CLAUDE.md:76-84,140-146`
  требует Sol по умолчанию, Opus только по качественной причине, а новые orchestrators —
  Opus 5. `pipelines/default/prompts/base.md:67-76` содержит тот же текущий routing.
- **Несовместимость:** задачи одного проекта получают разные модели только из-за имени
  pipeline; `tasks-pm` игнорирует отдельный Codex quota pool.
- **Выбор агента:** tasks-pm видит свой императив ближе к роли и передаёт `opus`/`haiku`
  в обязательный `spawn_worker(model=...)`.
- **Последствие:** scarce Claude quota сгорает на каждом чтении/кодинге; Haiku получает
  задачи, для которых текущая политика выбрала Sol/Spark. Стоимость здесь — число дорогих
  вызовов, не байты prompt.
- **Предложение:** единый model-routing module для обоих pipelines; в tasks-pm описывать
  task class, не provider alias.

### P1-15 — tasks-pm всё ещё классифицирует lifecycle по имени

- **Места:** `pipelines/tasks-pm/prompts/roles/base-orchestrator.md:11-16,23-29`
  объявляет `impl-*`/`fix-*` disposable и kill после merge; `CLAUDE.md:128-134` повторяет
  name-based kill. Текущий механический контракт
  `pipelines/default/prompts/modules/orchestration.md:128-142` прямо запрещает определять
  lifecycle по имени и требует marker + `worker_wip`.
- **Несовместимость:** persistent `fix-tg-speed` по двум старым правилам одноразовый, по
  новому — persistent/unmarked и не может быть auto-killed.
- **Выбор агента:** tasks-pm не получает новый orchestration module, поэтому выполнит
  старый пример `merge → kill` без WIP gate.
- **Последствие:** потеря долгоживущего контекста или незамерженной фазы; именно такой
  класс ошибки уже случался с воркерами `fix-*` и `ouroboros-*`.
- **Предложение:** lifecycle gate — общий module для каждого pipeline, без копии в
  `CLAUDE.md`; spawn всегда ставит marker.

### P1-16 — full-cycle обязан закрыть детей, но не получает kill gate

- **Места:** `pipelines/default/prompts/roles/full-cycle.md:155-159` требует spawn 2–3
  workers и «merge or kill them before finish»; единственный lifecycle/kill contract
  находится в `modules/orchestration.md:128-142`, который full-cycle не получает
  (`pipeline.yaml:63-72`).
- **Несовместимость:** роль имеет полномочие создать/убить ребёнка, но не видит обязательный
  marker, `worker_wip`, full-cycle gate и one-shot conditions.
- **Выбор агента:** использует краткое «kill them before finish» как достаточное
  основание, потому что другой политики в собранном prompt нет.
- **Последствие:** дочерняя работа/контекст уничтожается перед merge либо parent не может
  корректно завершиться с live children.
- **Предложение:** либо общий lifecycle-safety module всем spawn-capable ролям, либо fan-out
  full-cycle делает оркестратор, а worker только синтезирует результаты.

### P1-17 — orchestrator одновременно «никогда не кодит» и кодит trivial сам

- **Места:** `pipelines/default/prompts/roles/orchestrator.md:4-7` — «Delegate
  EVERYTHING»; `modules/orchestration.md:12-25,237-244` — trivial DIY, но content/
  research always delegate. Аналогичная пара есть в
  `pipelines/tasks-pm/prompts/roles/base-orchestrator.md:1-9`.
- **Несовместимость:** однострочная правка prose/config одновременно подходит под
  `trivial DIY` и `content ALWAYS delegate`/`EVERYTHING`.
- **Выбор агента:** выберет более дешёвый DIY, если уже знает файл, либо абсолютное
  EVERYTHING — результат меняется от формулировки task.
- **Последствие:** лишняя сессия для опечатки или, наоборот, оркестратор правит shared
  checkout между управлением агентами и пропускает проверку/worktree.
- **Предложение:** один классификатор по риску и артефакту: DIY только exact edit вне
  shared runtime; абсолютное EVERYTHING убрать.

### P1-35 — долговечный артефакт можно запустить без номера задачи

- **Места:** `pipelines/default/prompts/modules/orchestration.md:78-82` описывает task refs
  только для уже существующей задачи; `modules/task-management.md:14-24` не требовал
  `task_create` перед research/audit/knowledge-base работой.
- **Несовместимость:** артефакт обязан жить в `docs/tasks/<id>/`, но текстовое поручение
  могло не иметь `<id>` и оставалось непривязываемым постфактум.
- **Выбор агента:** начинал работу сразу по сообщению: создание task выглядело
  административной опцией, а не pre-work gate.
- **Последствие:** восемь ручных интеграций за день нельзя было связать с задачами и найти
  через task history, хотя их документы и коммиты существовали.
- **Предложение:** до substantive work создать/взять task number для любого persistent
  `docs/` artifact; exact 1–2 line edit без артефакта оставить без бюрократии.

### P2-18 — обязательный custom `system_prompt` описывает уже автоматическую работу

- **Места:** `pipelines/default/prompts/modules/orchestration.md:47-58,188-206` требует
  всегда передавать custom `system_prompt`; примеры `:89-117` его не передают. Код
  `app/manager.py:195-225,434-444` всегда собирает role prompt и лишь опционально добавляет
  custom overlay; `app/mcp_stdio.py:100-123` имеет `system_prompt=""` по умолчанию.
- **Несовместимость:** «never empty» относится к полному role prompt, но сформулировано как
  обязательный аргумент API, который runtime уже заполняет.
- **Выбор агента:** либо копирует шаблон и дублирует роль/quality bar, либо следует живым
  примерам без аргумента.
- **Последствие:** длинные конфликтующие overlays, устаревшая специализация при reuse и
  лишняя нерешительность перед spawn.
- **Предложение:** назвать аргумент `custom overlay`; задавать только уникальные границы,
  которых нет в role/task/owned_dirs.

### P2-19 — auto-report обещан sub-orchestrator, но код его отключает

- **Места:** `pipelines/default/prompts/base.md:8-10` без оговорки обещает auto-report
  «to the orchestrator»; `roles/sub-orchestrator.md:4-9` требует явный `send_message`.
  Реализация `app/session_turns.py:168-179` сразу выходит для `is_orchestrator`.
- **Несовместимость:** sub-orchestrator является одновременно дочерним агентом с parent и
  orchestrator без auto-report.
- **Выбор агента:** после финального текста может положиться на base и не вызвать tool.
- **Последствие:** родитель бесконечно ждёт завершение, хотя child уже idle.
- **Предложение:** формулировка tasks-pm base `:11` корректна: auto-report только workers;
  orchestrators всегда report explicitly.

### P2-20 — codex skill калибрует все проекты как Orchestra на 10 пользователей

- **Места:** `pipelines/default/prompts/modules/orchestration.md:47-58` требует
  **адаптировать** PROJECT CONTEXT под проект; `skills/codex-debate.md:119-126`
  предоставляет безусловный hardcode Python/FastAPI/SQLite/~10 users.
- **Несовместимость:** skill общий для проектов, но template выдаёт локальный контекст как
  готовый обязательный блок.
- **Выбор агента:** вставит ближайший copy-paste template дословно — это проще, чем заново
  исследовать scale/stack.
- **Последствие:** review чужого high-load/не-Python проекта снижает severity performance/
  architecture проблем и проверяет не тот stack.
- **Предложение:** template должен содержать placeholders и требовать факты из текущего
  repo/task; Orchestra-specific пример вынести из общего skill.

### P2-21 — codex skill спрашивает user там, где worker обязан спорить сам

- **Места:** `pipelines/default/prompts/skills/codex-debate.md:10-24` предлагает
  эскалацию/вопрос user и review только после явного «да»; тот же skill `:85-99,128-133`
  требует auto-iteration без дёрганья user. Роли делают review обязательным:
  `roles/full-cycle.md:34-40,65-70,117-124`, `roles/worker.md:53-56`.
- **Несовместимость:** обязательный review одновременно требует предварительного approval;
  blocking disagreement одновременно идёт user и автоматически debate'ится.
- **Выбор агента:** на ранней секции спросит user/выведет вопрос в обычный чат; worker по
  Orchestra вообще должен общаться с parent, не user.
- **Последствие:** лишний гейт, утечка рабочего вопроса мимо оркестратора или recorded-and-
  ignored finding при ожидании ответа не того адресата.
- **Предложение:** различить user-requested optional review и role-mandated review; worker
  эскалирует requester/parent только после 3 rounds или architecture/delete gate.

### P2-22 — personal-memory reminder снова использует ложный name heuristic

- **Места:** `pipelines/default/prompts/modules/self-improvement.md:49-56` напоминает
  long-lived/system, но исключает one-shot «such as impl-*/fix-*»; lifecycle source
  `modules/orchestration.md:128-139,151-164` говорит, что prefixes никогда не
  классифицируют lifecycle.
- **Несовместимость:** persistent worker с именем `fix-*` не получит reminder.
- **Выбор агента:** оркестратор использует явные примеры из self-improvement вместо
  поиска lifecycle marker в другой секции.
- **Последствие:** самые ценные долгоживущие workers продолжают терять знания; живой
  контрпример — persistent `fix-tg-speed`.
- **Предложение:** reminder gate только по `description lifecycle=persistent`, без имён.

### P2-23 — новая personal memory не переживает текущий compact

- **Места:** `pipelines/default/prompts/modules/self-improvement.md:41-52` обещает
  auto-inject на spawn/restart и survival compact; код загружает файл только при сборке
  prompt (`app/manager.py:435-444,1138-1157`), а `app/session.py:1162-1189` при compact
  создаёт summary, не перечитывая memory.
- **Несовместимость:** старое содержимое действительно остаётся в system prompt, но запись,
  сделанная перед DONE, не появляется после следующего compact без reload/restart.
- **Выбор агента:** доверяет обещанию и не переносит новый lesson в handoff summary.
- **Последствие:** первый же post-compact task выполняется со старой личной базой; именно
  новое знание, ради которого файл обновлялся, теряется на границе сессии.
- **Предложение:** либо runtime reload memory при compact, либо текст честно ограничивает
  гарантию spawn/restart до отдельного code fix.

### P2-24 — worker обязан push'ить локальную ветку, хотя merge локальный

- **Места:** `pipelines/default/prompts/modules/git-workflow.md:28-31` требует
  «committed and pushed»; `app/mcp_stdio.py:491-500` и
  `app/workspace.py:664-730` squash-merge'ят локальную branch/worktree без remote.
- **Несовместимость:** push назван precondition, которого merge API не использует и для
  adhoc branch обычно не настраивает.
- **Выбор агента:** попробует `git push`, потому что это часть `Before merge`.
- **Последствие:** потеря хода на credentials/upstream, публикация внутренних task branches
  или ложный blocker перед DONE.
- **Предложение:** обязательны local commit + clean status; push только если task/project
  явно использует remote review workflow.

### P2-25 — `owned_dirs` одновременно обязательны каждому и опциональны в runtime

- **Места:** `pipelines/default/prompts/modules/git-workflow.md:10-14` утверждает, что
  каждый worker owns specific directories и запрещает всё снаружи; `app/mcp_stdio.py:100-145`
  оставляет `owned_dirs=""`, а `app/manager.py:325-334` не инжектит ownership при пустом
  списке. Примеры spawn в `modules/orchestration.md:89-117` ownership не передают.
- **Несовместимость:** unowned worker по prompt либо «владеет ничем», либо должен считать
  отсутствие списка разрешением на весь task scope.
- **Выбор агента:** обычно игнорирует общий запрет, потому что конкретного списка нет;
  осторожный worker остановится и спросит.
- **Последствие:** скрытые пересечения файлов между workers или ненужный blocker на обычной
  задаче.
- **Предложение:** условный контракт: если ownership block присутствует — hard boundary;
  иначе task files define scope. Для параллельных edits `owned_dirs` сделать обязательным
  на spawn.

### P2-26 — full-cycle всегда пишет «Codex approved», хотя review можно skip

- **Места:** `pipelines/default/prompts/roles/full-cycle.md:78-88` безусловно запускает
  Codex и требует фразу `Codex approved`; тот же файл `:114-120` разрешает skip trivial
  diff вне shared runtime.
- **Несовместимость:** один допустимый маршрут не создаёт review artifact, но финальный
  contract требует заявить approval.
- **Выбор агента:** либо всё равно запустит Codex из нумерованной фазы, либо применит skip
  и скопирует обязательную фразу.
- **Последствие:** пустая трата review на prose/trivial либо ложное утверждение о несуществующем
  вердикте.
- **Предложение:** Phase 3 ссылается на единый review gate; DONE говорит `Codex approved`
  только при artifact, иначе `Codex skipped — <eligible reason>`.

### P2-27 — корневой model routing сам себе противоречит

- **Места:** `CLAUDE.md:5-7` описывает Claude-only «Opus управляет Haiku/Sonnet»;
  `:76-84` назначает orchestrators Opus 4.6, workers Sol; `:140-146` требует
  orchestrators Opus 5 и запрещает более старый выбор. Текущий manifest также ставит
  `claude-opus-5[1m]` (`pipelines/default/pipeline.yaml:18-39`).
- **Несовместимость:** три поколения routing живут в одном always-loaded документе.
- **Выбор агента:** обычно берёт последнюю строку «оркестраторы на Opus 5», но при spawn
  может скопировать стратегию из отдельного Pricing-раздела.
- **Последствие:** новая сессия получает неправильную модель/quota pool; проблема выглядит
  как ручная ошибка оркестратора.
- **Предложение:** routing только в одном runtime module/catalog; `CLAUDE.md` хранит
  принцип quota-first, без ids и исторических поколений.

### P2-28 — tasks-pm считает secretary report одновременно optional и gate

- **Места:** `pipelines/tasks-pm/prompts/_pipeline.md:34-47` говорит secretary reports
  необязательны для перехода; `roles/pm-fichi.md:4-11` требует всегда нанять secretary и
  прочитать отчёт **до** analyst.
- **Несовместимость:** один и тот же artifact не блокирует stage по общей таблице и блокирует
  по роли PM-фичи.
- **Выбор агента:** PM-фичи следует локальному numbered workflow и ждёт; PM-глава по общей
  таблице считает analyst уже допустимым.
- **Последствие:** родитель и child показывают разные статусы, analyst стартует дважды/
  слишком рано либо feature стоит без формального обязательного artifact.
- **Предложение:** решить контракт: secretary optional cache, а обязательный вход —
  `business_context.md`; если report нужен всегда, добавить его в таблицу artifacts.

### P2-29 — tasks-pm говорит coder «сам ревьюишь» и «всё чтение через secretary»

- **Места:** `pipelines/tasks-pm/prompts/roles/coder.md:11-15` требует самому проверить и
  ревьюить код workers; общий `_pipeline.md:11-19,64-65` требует любой поиск/чтение кода и
  приёмку делать через secretary/worker, чтобы не тратить собственный контекст.
- **Несовместимость:** ownership финального технического verdict не определён.
- **Выбор агента:** либо принимает пересказ secretary вместо просмотра diff, либо нарушает
  общий запрет и читает всё сам.
- **Последствие:** нет независимой технической проверки либо coder сжигает именно тот
  контекст, который pipeline пытался защитить.
- **Предложение:** coder лично читает load-bearing diff/tests и принимает verdict;
  secretary только собирает широкий контекст/логи.

### P2-30 — tasks-pm workers не получают сквозные правила pipeline

- **Места:** `pipelines/tasks-pm/pipeline.yaml:9-15` добавляет `_pipeline.md` только
  orchestrators; `pipelines/tasks-pm/prompts/roles/worker.md:1-6` почти пуст и отсылает к
  `base.md`, не к сквозным git/docs/contracts; `_pipeline.md:21-65` содержит именно эти
  обязательные правила.
- **Несовместимость:** автор называет `_pipeline` правилами «для всех ролей» (`:1-3`), но
  собранные secretary/worker их физически не содержат.
- **Выбор агента:** worker импровизирует по краткому task и корневому `CLAUDE.md`.
- **Последствие:** неверная base branch, пропущенные `docs_work` artifacts, task status и
  test lock; coder затем принимает работу, сделанную по другому pipeline.
- **Предложение:** выделить worker-safe shared module и подключить обоим kind; не инлайнить
  orchestrator-only ветвление.

### P3-31 — progress reporting не имеет проверяемого момента

- **Места:** `pipelines/default/prompts/roles/worker.md:62-67` говорит «for long tasks» и
  «at natural checkpoints»; в отличие от `self-improvement.md:49-52` у него нет события,
  порога или completion bar.
- **Несовместимость:** агент не может бинарно определить, стала ли задача long и наступил
  ли natural checkpoint.
- **Выбор агента:** не вызывает tool: работа и так видна в logs, а DONE обязателен.
- **Последствие:** dashboard/родитель не получают структурированный прогресс на длинной
  реализации; внезапный timeout оставляет только сырой лог. В текущей БД `update_progress`
  встречается у 13 сессий, тогда как worker/full-cycle сессий — 328.
- **Предложение:** привязать к измеримому событию (например, после каждого принятого ticket
  full-cycle или после каждого завершённого AC), либо удалить правило/tool из worker prompt.

### P3-32 — tasks-pm «периодически опрашивай» не задаёт ни события, ни безопасного способа

- **Места:** `pipelines/tasks-pm/prompts/roles/pm-glava.md:23-28` требует периодически
  опрашивать PM-фичи; `pipelines/tasks-pm/prompts/base.md:26-36,43-46` запрещает Monitor/
  background process и описывает только старый one-shot набор jobs.
- **Несовместимость:** обязательная периодичность не имеет интервала, stop condition или
  разрешённого recurring route; `cron` существует в текущем MCP, но эта копия base его
  скрывает.
- **Выбор агента:** либо игнорирует слово «периодически», либо шлёт ручные сообщения
  running-agent и дробит его фокус.
- **Последствие:** застрявшие feature не обнаруживаются или сам контроль создаёт очередь
  сообщений, похожую на уже случившийся queue-on-busy сбой.
- **Предложение:** event-based reports по milestones; если нужен SLA — один cron с явным
  интервалом и проверкой статуса, без произвольного polling.

### P3-33 — platform contract скопирован в два base и уже разъехался

- **Места:** дубли `pipelines/default/prompts/base.md:2-25,28-42` и
  `pipelines/tasks-pm/prompts/base.md:1-36`; background jobs дополнительно продублированы в
  `default/modules/background-jobs.md:1-23`.
- **Несовместимость:** tasks-pm знает старый auto-report точнее, но неверно даёт workers
  cross-project access и считает jobs one-shot; default знает cron и worker isolation, но
  неверно обобщает auto-report на orchestrators.
- **Выбор агента:** получает «истину» своего pipeline; общей runtime-политики для одной MCP
  платформы нет.
- **Последствие:** исправление безопасности/инструмента в default не доезжает tasks-pm,
  следующая миграция снова создаёт скрытую коллизию.
- **Предложение:** один platform base + один background module, переиспользуемые обоими
  manifests; pipeline-specific правила отдельно.

### P3-34 — 55% `CLAUDE.md` — runtime-changelog, а не текущий контракт

- **Места:** `CLAUDE.md:136-203` («Грабли») занимает 18 016 из 32 748 B; сам файл
  `:205-208` говорит, что хроника уже лежит в `docs/archive/sessions/` и индексируется
  через memory. `CLAUDE.md:91-104` рекомендует pre-inject только повторяемое и сокращать
  tool calls.
- **Несовместимость:** always-loaded document хранит детальные разовые симптомы, live DB
  числа, старые model generations и уже исправленные реализации, хотя для истории есть
  отдельный retrieval layer.
- **Выбор агента:** доверяет исторической конкретике как текущему правилу; поздние строки
  конкурируют с role/module contracts (kill, models, report_bug).
- **Последствие:** потолок исчерпан, полезные новые правила нельзя добавить, а старые
  детали уже породили P1-6/P1-15/P2-27.
- **Предложение:** в `CLAUDE.md` оставить только короткие действующие invariants и ссылки на
  field guides; symptom→cause истории перенести в индексируемые docs. Резать ради ясности и
  лимита, не ради цены: `CLAUDE.md:197` уже фиксирует, что bytes дают около 4% стоимости.

## Порядок исправлений

1. **Сразу:** P0-1 (освободить byte budget + test) и P0-2 (единицы денег).
2. **Один пакет контрактов default:** P1-3—P1-8, P1-16, P1-17, P1-35. После пакета
   проверить собранные четыре роли, не отдельный файл.
3. **Опасные внешние действия:** P1-9, P1-10.
4. **Дедупликация:** P2-18—P2-27 и P3-33—P3-34; цель — один source of truth на каждое
   правило, а не очередная уточняющая строка рядом.

## Что не считал находками

- Сам размер статического system prompt не объявлен дефектом: внутренний замер проекта
  показывает, что стоимость определяет число вызовов, а bytes дают около 4%. Размер важен
  здесь только там, где он упирается в реальный 32 KiB limit или снижает исполнимость.
- Повторы code-quality между worker/full-cycle оставлены вне списка: роли не склеиваются
  друг с другом, а формулировки пока одинаковы и не создают разного действия.
- `codex-debate` всё ещё называет reviewer GPT-5.5 в header, тогда как tool docstring
  `app/mcp_stdio.py:923-939` говорит GPT-5.6 Sol. Это протухшая метка, но без отдельного
  рабочего последствия она ниже порога аудита; исправить вместе с P2-20/P2-21.
- Второй Codex-раунд не запускался: аудит текстовый, все load-bearing выводы подтверждены
  собранными prompt'ами и текущим runtime code; дополнительный review не менял бы artifact,
  а собственное правило ограничивает пустые раунды на prose.
