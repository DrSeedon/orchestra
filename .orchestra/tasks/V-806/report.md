# V-806 — Claude Managed Agents и dynamic workflows

**Область:** исследование без изменений кода Orchestra и без платных вызовов. Срез кода: текущий checkout V-806; внешняя документация проверена 10.10.2026. Все источники ниже открыты либо указаны как недоступные для прямой загрузки.

## Краткий вывод

Managed Agents dynamic workflows — API-бэкенд и исполняющая среда Anthropic для Claude, а не новая модель планировщика и не агентная система с прямым доступом к локальному checkout. В multiagent_20261001 сессия получает субагентов и workflows включёнными по умолчанию. Модель основного агента сама решает по заданию и системной инструкции, нужен ли workflow; она пишет программу разбиения на фазы и агентов. Сервер выполняет её в фоне, программа передаёт результаты между агентами и агрегирует их. У программы до 1 000 запущенных агентов за run, но до 64 одновременно.

В Orchestra уже есть детерминированный fan-out, цепочки, этапы с передачей результатов, лимиты стоимости/вызовов и общий ресурсный планировщик. Отличие — Orchestra получает от вызывающего заранее заданную структуру задач, а не поручает модели сочинить её. Текущий интерфейс нельзя называть автоматической декомпозицией.

**Рекомендация:** не переносить Managed Agents как backend. API-кредиты V-800 предназначены только для явно выбранных задач с billing="api_credit"; по данным владельца, они сейчас исчерпаны до 04.11.2026. Новые платные вызовы не выполнялись. Прямой тариф сервиса — цены API-токенов плюс $0.08 за час работающей сессии; лимит в $200/мес не является подписочной квотой Managed Agents и не делает стоимость большого workflow предсказуемой.

## 1. Что подтверждает первоисточник Anthropic

### Поведение и планировщик

Документация называет workflow **программой, которую пишет агент**. Входное сообщение описывает цель; агент основной сессии определяет, начинать ли run и когда. Он может определить агентов, фазы, prompts, параллельный fan-out, передачу результатов, повторы внутри фазы и следующий шаг по полученным ответам. Программа управляет дальнейшим запуском; главный агент не ведёт каждую задачу вручную. После окончания run главная сессия получает возможность прочитать результаты.

Отдельная «модель планировщика» в документации не заявлена. Основной агент использует назначенную ему модель. Inline-агенты workflow используют модель основной сессии и её tools/MCP/skills; для других моделей надо заранее определить агентов и разрешить workflow их выбирать. Поэтому «планировщик» — роль основного агента/модели плюс сгенерированная ею программа, а не отдельная модель.

Результаты «сливаются» на уровне программы: код собирает возвращённые значения и может направить их в следующую фазу. Это не автоматический git merge. Все участники run используют те же файлы sandbox-сессии; контексты и event streams раздельны. Изоляция контекста не означает отдельный checkout каждого агента, поэтому изменения общих файлов могут взаимодействовать.

Источники: [Multiagent orchestration](https://platform.claude.com/docs/en/managed-agents/multiagent-orchestration), [Workflow runs](https://platform.claude.com/docs/en/managed-agents/workflow-runs), [Agent setup](https://platform.claude.com/docs/en/managed-agents/agent-setup).

### Лимиты, тарификация и среда

Официальная документация workflow указывает:

- максимум 64 работающих одновременно agent threads на run; документация предупреждает, что лимит может меняться и API не гарантирует именно это значение;
- до 1 000 агентов, стартующих за весь срок одного run; повторно запущенные после сбоя агенты могут увеличить итоговое число threads выше 1 000;
- 24 часа срок run по умолчанию (агент может задать более короткий); пауза не останавливает отсчёт;
- 10 открытых runs на сессию по умолчанию, включая idle/приостановленные;
- бюджет сессии при достижении приостанавливает runs, но уже начатый запрос каждого работающего потока может завершиться; суммарный расход может превысить бюджет на эти запросы;
- агентские запросы также занимают лимиты Messages API модели и лимиты организации.

Это API-тарификация, не Claude Pro/Max/Team подписка. У workflow нет отдельного фиксированного тарифа: все токены потоков оплачиваются по API-ставкам использованных моделей. Для Managed Agents дополнительно считается **$0.08 за час состояния сессии running**; idle не тарифицируется по runtime. При 24 часах непрерывного running это $1.92 runtime за сессию, дополнительно к токенам. [Официальные цены Claude Managed Agents](https://platform.claude.com/docs/en/about-claude/pricing) перечисляют обе составляющие; [лимиты workflow](https://platform.claude.com/docs/en/managed-agents/workflow-runs) уточняют учёт бюджета и потоков.

Вызовы идут через Claude Platform API с beta header managed-agents-2026-04-01; multiagent_20261001 — значение поля multiagent.type, а не модель. Публичная бета требует API-ключ и тарифицируется API-способом.

Anthropic также публикует отдельный продуктовый [пост о dynamic workflows в Claude Code](https://claude.com/blog/introducing-dynamic-workflows-in-claude-code): он описывает workflows для Claude Code CLI/Desktop/IDE, включая подписочные планы. Это не основание считать Managed Agents API частью подписки: отдельная Managed Agents документация и тарифная страница прямо тарифицируют Platform API-сессии по токенам и runtime.

По умолчанию агент работает в изолированной Linux cloud sandbox Anthropic: Bash, файловые read/write/edit/glob/grep, web search/fetch и MCP. Конфигурация агента задаёт модель, prompt, tools, MCP и skills. Для приватных GitHub-репозиториев документация предлагает ресурс github_repository с токеном доступа и checkout ветки или commit. Альтернатива — self-hosted sandbox, где Anthropic ведёт orchestration/control plane, а выполнение кода и файлы находятся в инфраструктуре владельца. Но self-hosted требует поднять worker; GitHub/file resources туда не монтируются как в cloud — код надо подготовить самому. У локального пути текущего Orchestra нет автоматического доступа.

MCP-серверы объявляются в конфигурации агентов, а credentials сессии передаются через vault. Поддерживаются также custom tools. Инструменты MCP могут требовать подтверждения по permission policy; доступ предопределённых агентов можно сужать. Системный доступ к файлам и сети зависит от cloud/self-hosted среды и её сетевых ограничений. Бета-характеристики API могут меняться. Stateful-сессии сохраняют историю и sandbox state; overview указывает, что Managed Agents пока не подходит для Zero Data Retention или HIPAA BAA.

Источники: [Overview](https://platform.claude.com/docs/en/managed-agents/overview), [Cloud environments](https://platform.claude.com/docs/en/managed-agents/environments), [Accessing GitHub](https://platform.claude.com/docs/en/managed-agents/github), [MCP connector](https://platform.claude.com/docs/en/managed-agents/mcp-connector), [Self-hosted sandboxes](https://platform.claude.com/docs/en/managed-agents/self-hosted-sandboxes), [Pricing](https://platform.claude.com/docs/en/about-claude/pricing).

Настройка multiagent.type: multiagent_20261001 по умолчанию включает subagents и workflows; advisor опционален и по умолчанию отключён. Список содержит максимум 20 уникальных predefined agents на каждый список; это отдельное ограничение от 1 000 созданных в workflow за весь run. Обычные subagent threads ограничены 25 на сессию, workflow threads из этого лимита исключены. Вложенная многоуровневая делегация запрещена. Источник: [Multiagent orchestration](https://platform.claude.com/docs/en/managed-agents/multiagent-orchestration).

### Откуда взялась цифра «70 багов»

Anthropic опубликовал announcement и числа через аккаунт ClaudeDevs в X: [пост/тред о dynamic workflows](https://x.com/ClaudeDevs/status/2108591328732856655). В сообщении/демо говорится: в кодовой базе на 116 тыс. строк заложили 70 ошибок; один агент в трёх запусках нашёл 14, 15 и 27; workflow — 66 в каждом из трёх запусков. Числа о демо не перечислены в официальной API-документации или release notes; release notes подтверждают выход dynamic workflows в beta, но не методику эксперимента.

Это внутренний vendor-тест, а не независимый бенчмарк. В открытом сообщении не названы репозиторий/язык, природа и тяжесть ошибок, инструкция агентам, модель и параметры, размер workflow-команды, правило дедупликации, оценка false positives, стоимость/токены/время каждого режима и проверка находок. «Найденное» нельзя трактовать как precision: публичного знаменателя ложных срабатываний нет. Также не сообщено о сопоставлении бюджетов/токенов single-agent и workflow. Результаты показывают один эффектный результат на задаче, пригодной для поиска множества независимых дефектов, но не доказывают ту же кратность выигрыша, стоимость-эффективность или преимущество на обычной работе Orchestra. Независимую репликацию в рамках исследования не обнаружил; coverage поиска — официальная документация, release notes и первичное объявление Anthropic, не весь интернет.

Команда /claude-api managed-agents-onboard bug-hunter — guided onboarding из Claude Code для создания конфигурации нового Managed Agent по шаблону/задаче. Она не активирует и не переводит текущий Orchestra dynamic_workflow на Anthropic backend. Источник команды — [официальный репозиторий Anthropic Skills](https://github.com/anthropics/skills/blob/main/skills/claude-api/shared/managed-agents-onboarding.md); история Claude Code документирует managed-agents-onboard как flow настройки Managed Agent. «Bug-hunter» здесь — название/сценарий onboarding, не опубликованная гарантия найденных дефектов.

## 2. Сравнение с Orchestra по текущему коду

| Возможность | Anthropic Managed Agents | Orchestra сейчас |
|---|---|---|
| Запуск и разбиение | Основной агент сам определяет необходимость workflow и пишет фазированную программу | Вызывающий передаёт конкретные tasks, mode=parallel/chain либо конкретные stages; инструмент не генерирует список задач |
| Выполнение задач | Managed background run; агентские threads запускаются в sandbox общей сессии | dynamic_workflow сохраняет спецификацию и ставит scripts/wf_run.py как Orchestra background run; задачи исполняются существующими CLI adapters с выбранными моделями |
| Границы | До 1000 агентов за run, 64 одновременно по текущей документации | До 1000 expanded tasks, до 20 stages, JSON spec 1 MiB; вызывающий задаёт max concurrency 1–100. Runner по умолчанию ограничивает локальную параллельность 3 и применяет общий resource-aware scheduler |
| Передача и сбор результата | Программа выбирает данные, которые переходят между фазами; затем primary agent читает run | В chain следующий task получает предыдущий WorkflowValue; в stages каждый task получает все результаты предыдущей стадии; результат хранится в manifest и приходит вызывающему |
| Работа с репозиторием | Cloud: GitHub mount или загруженные файлы; self-hosted: пользователь организует checkout | Инструмент принимает checkout/worktree, закрепляет его HEAD, runner создаёт task workspaces по локальному коду; удалённая публикация не нужна |
| Оплата | API tokens + runtime Managed Agents | Подписка по умолчанию; выбранные явно Claude tasks могут иметь billing="api_credit"; неявный fallback на кредиты запрещён |

Ключевые места в исходниках:

- dynamic_workflow, входная схема и ограничения: [app/mcp_stdio.py:3161](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-managed-agents/app/mcp_stdio.py:3161) — инструмент принимает задачи/фазы как данные, проверяет пределы 20 stages/1000 tasks/1 MiB и concurrency 1–100 ([строки 3188–3274](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-managed-agents/app/mcp_stdio.py:3188)); checkout превращается в repo root + закреплённый commit, спецификация сохраняется и запускается как background job ([3280–3333](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-managed-agents/app/mcp_stdio.py:3280)).
- Исполнение по спецификации: [scripts/wf_run.py:440](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-managed-agents/scripts/wf_run.py:440) настраивает budget, concurrency и runner; explicit parallel/chain исполняются в [строках 1229–1257](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-managed-agents/scripts/wf_run.py:1229), фазы с передачей результатов — [1259–1282](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-managed-agents/scripts/wf_run.py:1259). agent() проверяет тип backend, бюджет, квоту/готовность, capability и режим оплаты ([649–770](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-managed-agents/scripts/wf_run.py:649)).
- Центральный workflow scheduler: [app/workflow_scheduler.py:29](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-managed-agents/app/workflow_scheduler.py:29) измеряет CPU, память и pressure; [87–126](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-managed-agents/app/workflow_scheduler.py:87) вычисляет concurrency; [129–219](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-managed-agents/app/workflow_scheduler.py:129) выдаёт слоты из общей очереди, распределяя вызовы по активным runs. Это планировщик локальной пропускной способности, не семантической декомпозиции.
- Лимиты, учёт и журнал: [scripts/wf_run.py:119](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-managed-agents/scripts/wf_run.py:119) — budget; [1173–1207](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-managed-agents/scripts/wf_run.py:1173) — manifest со стоимостью, вызовами и результатами. Параллельность runner и запросы scheduler — [477–480](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-managed-agents/scripts/wf_run.py:477), [571–631](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-managed-agents/scripts/wf_run.py:571).
- Model adapters и MCP: [scripts/wf_adapters.py:331](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-managed-agents/scripts/wf_adapters.py:331) задаёт Claude CLI tools/network/MCP и явный billing route; [451–480](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-managed-agents/scripts/wf_adapters.py:451) маршрутизирует к adapter по модели.
- Долгоживущие работники и orchestration lifecycle существуют отдельно от task-runner: spawn_worker создаёт worker в изолированном git worktree, требует model/task binding и передаёт MCP servers ([app/mcp_stdio.py:1054–1080](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-managed-agents/app/mcp_stdio.py:1054)); merge_worker выполняет отслеживаемый squash merge с outcome/lifecycle полями ([2474–2486](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-managed-agents/app/mcp_stdio.py:2474)); task_create создаёт задание ([2993–3027](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-managed-agents/app/mcp_stdio.py:2993)).
- Явный billing V-800: workflow API [scripts/wf_run.py:667](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-managed-agents/scripts/wf_run.py:667) принимает subscription по умолчанию или api_credit; выбранный кредитный маршрут проверяется до dispatch ([751–768](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-managed-agents/scripts/wf_run.py:751)) и непосредственно в Claude adapter ([scripts/wf_adapters.py:337](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-managed-agents/scripts/wf_adapters.py:337)). Ledger считает только usage с billing_mode='api_credit' ([app/claude_api_credits.py:25–47](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-managed-agents/app/claude_api_credits.py:25)). Решение V-800 зафиксировано в [V-800 report](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-managed-agents/.orchestra/tasks/V-800/report.md:5).

## 3. Вердикт по механизмам и цена переноса

| Механизм/предложение | Вердикт | Основание / цена переноса |
|---|---|---|
| План и явные этапы с результатами между ними | **Уже есть** | Orchestra stages реализованы; их порядок, inputs и prompts задаются явно. Это воспроизводимо и подходит известным этапам bug hunt. Перенос не нужен. |
| Автоматическое разбиение цели на произвольный набор подзадач/этапов | **Не брать как замену текущему API** | Потребует planner-generated workflow формата, безопасной валидации, оценки стоимости/числа вызовов, запуска/отмены/resume и обработки частичной программы. Это меняет контракт и поведение запуска. Уже есть ограниченное разворачивание заданного списка items через шаблон {item}; это не семантическое разбиение. |
| Автоматическое объединение ответов | **Уже есть в предсказуемом виде; агентный синтез задаётся явно** | Workflow собирает массив ответов; chain/stages передают структурированные inputs. Синтез — task, который вызывающий явно добавляет. «Модель сама решает» — выбор о качестве и воспроизводимости, а не техническая недостача. |
| bug-hunter как приём поиска | **Брать приём, не Managed Agents** | Разделить поиск по областям, дедупликацию, независимую проверку находок и итоговую сводку можно через текущие stages/tasks. Цифры Anthropic дают мотивацию тестировать независимые срезы, но не обещают recall/precision и не доказывают окупаемость. В существующем запуске нет отдельного тарифа инфраструктуры; модельные расходы зависят от явно выбранных backend и billing и ограничиваются бюджетом runner. |
| Managed Agents как backend для задач billing="api_credit" | **Не брать сейчас** | Нужна интеграция Agent/Environment/Session, передача репозитория и credentials, обработка SSE/event/thread/workflow, остановка и восстановление runs, выгрузка результатов и полный учёт thread-токенов плюс runtime. Это не замена одного адаптера. Пул API-кредитов $200 по словам владельца исчерпан до 04.11; без новых средств нельзя проверить цену/полноту учёта, платный тест не запускался. При включении тариф — API tokens + $0.08 за running-session-hour; объём токенов опубликованного теста неизвестен. Денежная оценка инженерного переноса неизвестна: код не писался и интеграция не замерялась. |

**Предложение на будущее, отдельное от текущего задания:** ограниченный bug-hunt эксперимент внутри существующего Orchestra workflow — фиксированный commit, заранее известный набор подтверждённых дефектов, одинаковый бюджет для одиночного и staged поиска, запись валидных и ложных кандидатов. Только отдельное решение владельца может разрешить оплату API-кредитами. Это даст более сопоставимый ответ на вопрос о качестве при одинаковом расходе и не требует сначала внедрять новый backend.

## Источники

- Anthropic [Managed Agents overview](https://platform.claude.com/docs/en/managed-agents/overview)
- Anthropic [Agent setup](https://platform.claude.com/docs/en/managed-agents/agent-setup)
- Anthropic [Multiagent orchestration](https://platform.claude.com/docs/en/managed-agents/multiagent-orchestration)
- Anthropic [Workflow runs: budgets and limits](https://platform.claude.com/docs/en/managed-agents/workflow-runs)
- Anthropic [Claude Platform release notes](https://platform.claude.com/docs/en/release-notes/overview), запись от 9 октября 2026
- Anthropic [Claude Managed Agents pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- Anthropic [Cloud environments](https://platform.claude.com/docs/en/managed-agents/environments), [GitHub access](https://platform.claude.com/docs/en/managed-agents/github), [MCP connector](https://platform.claude.com/docs/en/managed-agents/mcp-connector), [self-hosted sandboxes](https://platform.claude.com/docs/en/managed-agents/self-hosted-sandboxes)
- Anthropic [ClaudeDevs announcement and bug-hunt figures](https://x.com/ClaudeDevs/status/2108591328732856655) (X page did not render through browser fetch; figures cross-checked against contemporaneous reports, protocol remains undocumented)
- Anthropic [Introducing dynamic workflows in Claude Code](https://claude.com/blog/introducing-dynamic-workflows-in-claude-code) (separate Claude Code surface)
- Anthropic [Managed Agents onboarding source in anthropics/skills](https://github.com/anthropics/skills/blob/main/skills/claude-api/shared/managed-agents-onboarding.md)
