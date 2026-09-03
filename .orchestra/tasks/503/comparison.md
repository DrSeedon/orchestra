# #503 — Orchestra против популярных ADE/harness: матрица возможностей

Все ячейки проверены 02.09.2026. Правило: факт берётся из первоисточника (репозиторий,
README/CONTRIBUTING, официальная документация, локальный бинарник) со ссылкой; маркетинговая
строка помечается **[заявка]**; отсутствие подтверждения пишется как «не проверено», а не «нет».

Метаданные всех репозиториев сняты `gh api repos/<owner>/<repo>` 02.09.2026, а не из поисковой
выдачи: выдача давала Orca «53k» при фактических 59 427.

## Кого сравниваем и почему

| Проект | Звёзды | Последний push | Лицензия | Язык | Категория |
|---|---:|---|---|---|---|
| **Orchestra** (наш) | 3 | 2026-09-02 | AGPL-3.0 + коммерческая | Python | оркестратор флота |
| **Orca** `stablyai/orca` | 59 427 | 2026-09-02 | MIT | TypeScript | ADE, десктоп + мобильный |
| **omp / oh-my-pi** `can1357/oh-my-pi` | 28 961 | 2026-09-02 | MIT | TypeScript + Rust | harness одного агента с субагентами |
| **Multica** `multica-ai/multica` | 48 569 | 2026-09-02 | NOASSERTION | Go | workspace-доска для агентов |
| **Paseo** `getpaseo/paseo` | 15 778 | 2026-09-02 | NOASSERTION | TypeScript | демон + клиенты |
| **cmux** `manaflow-ai/cmux` | 26 679 | 2026-09-02 | NOASSERTION | Swift | терминальный оркестратор |

**Выкинуты после проверки, с причиной:**
- `BloopAI/vibe-kanban` (27 986★) — последний push **2026-04-24**, четыре месяца тишины. Живость
  не подтверждается, в матрицу не берём.
- `herdrdev/herdr` (34 498★) — категория подходит (мультиплексор агентов), но README 4,4 КБ и
  весь предмет вынесен на `herdr.dev/docs`. Сорсить ячейки было бы пересказом внешнего сайта —
  честнее не включать, чем включить с шестью «не проверено».
- LangGraph / CrewAI / AutoGen — другая категория (SDK для построения графов агентов, а не среда
  для флота CLI-агентов). Они уже стоят в сравнительной таблице README и там уместны.

## Матрица

| | **Orchestra** | **Orca** | **omp (oh-my-pi)** | **Multica** | **Paseo** | **cmux** |
|---|---|---|---|---|---|---|
| **1. Кто дирижирует** | Агент-оркестратор: сам режет задачу, спавнит воркеров, назначает, мержит | Человек: «Fan one prompt across five agents … compare the results and merge the winner». Слоган «The AI Orchestrator» — **[заявка]**, механизма агента-распорядителя в README нет | Агент: режим `orchestrate` «run substantial independent work through parallel subagents and verify each phase»; `task` раздаёт работу воркерам | Человек назначает как коллегам; агенты сами «pick up work, report progress, raise blockers, and hand back for review» | Человек через CLI/клиенты; **но** «Skills teach your agent to use Paseo to orchestrate other agents» — агентная раздача возможна как навык | Человек. Субагенты, порождённые самим агентом, показываются как панели: «When an agent spawns subagents or teammates, cmux turns them into native panes» |
| **2. Изоляция работы** | git worktree на воркера + squash-merge в main | git worktree на агента, в т.ч. по SSH («SSH Worktrees») | worktree на субагента: «task fans out into isolated worktrees, each worker runs its own tool surface»; отдельная крата `pi-iso` (apfs/btrfs/zfs/reflink/overlayfs/projfs) | не проверено: в README только Docker/Helm для селф-хоста самой платформы, про изоляцию отдельного агента ничего | worktree по флагу: `paseo run --provider codex/gpt-5.5 --worktree feature-x` | не проверено: в панели показываются git-ветка и рабочий каталог, про отдельный worktree не сказано |
| **3. Общение агентов между собой** | Прямые сообщения `send_message(to=…)` воркер→воркер, без человека | не проверено: в README нет механизма обмена между агентами | Есть: в их же подписи к демо — «the constraints block requiring an IRC DM between peers», плюс Agent Hub, где можно писать субагенту steering-сообщение | Косвенно, через доску: агенты «report progress, raise blockers» в общий контекст задачи | не проверено: в README обмен между агентами не описан, есть `/paseo-advisor` как отдельный агент-советчик | не проверено: панели показывают чужие сессии, канал обмена не описан |
| **4. Ревью** | Обязательный этап перед мержем, ревьюер — модель другого вендора | Человеческое: «Annotate AI Diffs», просмотр PR в приложении. Ревью моделью не заявлено | Два механизма: роль `advisor` — «a second model, watching every turn … runs on its own context and its own model», и `/review`, который «spawns dedicated reviewer subagents» с вердиктом и приоритетами P0–P3 | Человеческое: работа возвращается «back for review» | `/paseo-advisor` — «a single agent as an advisor for a second opinion»; обязательным этапом не является | не проверено |
| **5. Скорость тулинга** | Внешние процессы (CLI-агент зовёт `grep`/`rg`/`bash`). Свой in-process слой есть только у OpenRouter-харнесса (`app/harness/tools.py`) | не проверено: агенты чужие, тулинг их | **Главная их ставка:** «~80,000 lines of Rust, doing the work other harnesses shell out for … Search, shell, AST, highlight, PTY, desktop control, image decode, BPE counting — all in-process on the libuv pool. **No fork/exec on the hot path**». Плюс 58 CLI-утилит (coreutils, findutils, sed, jq, ripgrep-backed grep, fd, diff) вкомпилированы в крату builtins. **Числовых замеров задержки они НЕ публикуют** — ни в README, ни в их же посте про harness-проблему | не проверено | не проверено | не проверено |
| **6. Мультирантаймовость** | 4 рантайма за одним контрактом: Claude Code, Codex, Grok, свой OpenRouter-харнесс (`BUILTIN_RUNTIMES`) | Максимальная широта: «Works with **any CLI agent**», в README перечислено 28 штук с ссылками — Claude Code, Codex, Grok, Cursor, Copilot, OpenCode, MiMo, Amp, Pi, сам oh-my-pi, Hermes, Devin, Goose и др. | **60+ провайдеров** моделей (это провайдеры LLM, а не CLI-агентов — другая ось) | «works with 26 agent CLIs» | 5 названы: Claude Code, Codex, Copilot, OpenCode, Pi | «26+ agent CLIs» по описанию репозитория; в README названы Claude Code teams и другие |
| **7. Персистентность** | Сессии в SQLite, авто-resume после рестарта, гибернация с освобождением дерева процессов; замер по своей БД: 431 завершённая сессия воркера, медиана жизни 0,8 ч, p90 **130,6 ч**, максимум **531,8 ч**, дольше суток жили 81 | не проверено: агенты живут как процессы в панелях приложения; про переживание рестарта в README нет | Субагентов можно «revive a parked worker, or kill a stuck one without aborting the parent session»; персистентный Python- и Bun-кернел внутри сессии | Демон на своей машине держит рантаймы агентов | Демон: «Paseo runs a local server called the daemon that manages your coding agents», клиенты подключаются к нему | Частично: «Supported agent sessions can resume when hooks have saved a native session ID» |
| **8. Что есть у них, чего НЕТ у нас** | — | Десктоп (macOS/Windows/Linux) и мобильные приложения iOS/Android; нативные GitHub и Linear в интерфейсе; SSH-worktrees на удалённой машине; переключатель аккаунтов с трекингом лимитов; drag-and-drop файлов в агента; поддержка 28 CLI-агентов против наших 4 | In-process тулинг без fork/exec; LSP (14 операций) и DAP-отладчик (28 операций) в тулах агента; hashline-редактирование по хешу содержимого; 60+ провайдеров моделей; advisor, читающий КАЖДЫЙ ход; типизированный schema-validated результат субагента вместо прозы; Agent Hub с живым просмотром и оживлением воркеров; браузер и управление десктопом | Доска в духе трекера, где агент выглядит как участник команды; 26 CLI-агентов; готовый селф-хост Docker Compose / Helm | Демон с десктоп-, мобильным и веб-клиентом; голосовое управление; готовый Docker-образ; MCP-сервер в составе демона | Нативные панели терминала для субагентов, tmux-интеграция, встроенный браузер, нативное приложение на Swift |

---

## Разбор по пунктам с источниками

### 1. Кто дирижирует

- **Orca.** README: «Fan one prompt across five agents, each in its own isolated git worktree —
  compare the results and merge the winner» (`stablyai/orca`, README, раздел Parallel Worktrees).
  Выбирает и мержит человек. Строка «The AI Orchestrator for 100x builders» — маркетинговый
  заголовок в шапке, механизма за ней в README нет → **[заявка]**.
- **omp.** README, список режимов: `orchestrate` — «run substantial independent work through
  parallel subagents and verify each phase». Это ближайший к нам по замыслу пункт во всей выборке:
  решение о разбиении принимает агент.
- **Multica.** README: «an open-source workspace where you assign work to AI coding agents the way
  you'd assign to teammates», агенты «pick up work, report progress, raise blockers, and hand back
  for review». Раздаёт человек, инициативу внутри задачи проявляет агент.
- **Paseo.** README: «Skills teach your agent to use Paseo to orchestrate other agents» — то есть
  агентная раздача достижима, но это навык поверх CLI, а не роль в системе.

### 2. Изоляция

Worktree как единица изоляции — уже общее место, а не наше отличие: он есть у Orca, omp, Paseo и
у нас. Различаются детали: у omp под изоляцию выделена отдельная Rust-крата `pi-iso` (3 300 строк,
apfs/btrfs/zfs/reflink/overlayfs/projfs — то есть быстрые копии рабочего дерева на уровне ФС), у
Orca есть worktree на удалённой машине по SSH, у нас — привязка worktree к задаче и squash-merge
с гейтом.

### 3. Общение между агентами

У omp это подтверждается их же материалом: подпись к демо описывает «constraints block requiring
an IRC DM between peers», а Agent Hub позволяет «type a steering message» конкретному субагенту.
У остальных прямого канала в первоисточниках не нашёл — пишу «не проверено», потому что отсутствие
строки в README не доказывает отсутствие механизма.

### 4. Ревью

Здесь у omp сильнее нас по механике: `advisor` — вторая модель, читающая **каждый** ход основного
агента и вставляющая заметку inline («a quiet aside, a concern, or a hard blocker»), плюс `/review`
с вердиктом и приоритетами P0–P3. У нас ревью — событие перед мержем, а не непрерывный надзор.
Наше отличие в другом: ревью у нас **обязательный гейт мержа**, а не опция, и оно уходит на модель
другого вендора.

### 5. Скорость тулинга — тот самый вопрос про omp

**Что подтверждается.** В README omp прямо написано: «Roughly ~80,000 lines of Rust, doing the work
other harnesses shell out for. … Search, shell, AST, highlight, PTY, desktop control, image decode,
BPE counting — all in-process on the libuv pool. **No fork/exec on the hot path.**» Отдельно
указано, что ещё ~80k строк едут вендоренными: форк bash под именем brush плюс **58 утилит
командной строки** (coreutils, findutils, sed, jq, ripgrep-backed grep, fd, diff, moreutils),
портированных в крату builtins. То есть архитектурная заявка «тулинг внутри харнесса» —
**правда и она документирована**.

**Что НЕ подтверждается.** Ни одного числа про задержку они не публикуют. Проверено дважды: в
README цифры только про качество редактирования (Grok Code Fast 1 «6.7% → 68.3%», Grok 4 Fast
«−61% tokens», MiniMax «2.1×»), а их собственный пост про harness-проблему
(`blog.can.ac/2026/02/12/the-harness-problem/`, редиректит на `stencil.so/blog/the-harness-problem`)
измерений задержки не содержит вовсе. Формулировка «отвечает за миллисекунды вместо вызова внешних
программ» — это **вывод из архитектуры, а не их замер**.

**Порядок величины я померил сам** — не их продукт, а сам механизм, на этом VPS, ветки чередовал
A/B/A/B, 40 повторов, loadavg 2.87 в момент замера (`/tmp/bench_spawn.py`):

| Что | Медиана | p90 |
|---|---:|---:|
| Поиск подстроки в памяти (in-process, Python `re` по README.md) | **20,2 мкс** | 31,7 мкс |
| Тот же поиск внешним процессом (`/usr/bin/grep -c` по тому же файлу) | **3 667,6 мкс** | 5 845,7 мкс |
| Голый `fork+exec` (`/bin/true`, ничего не делает) | **2 170,0 мкс** | 3 496,5 мкс |

Повтор того же скрипта через двадцать минут при loadavg 2.44: 20,0 мкс / 3 868,8 мкс / 2 174,0 мкс,
отношение 193× — порядок величины устойчив, разброс между прогонами ~7%.

Отсюда: внешний вызов дороже внутреннего примерно в **180–190 раз**, и около **60% его цены — это
сам запуск процесса**, а не полезная работа. При 30–50 тул-вызовах на ход разница набегает на 0,1–0,2 с
за ход — заметно для интерактивного харнесса и почти невидимо для нашего сценария, где ход воркера
и так измеряется десятками секунд. Это объясняет, почему ставка omp разумна для них и не является
дырой у нас: у нас узкое место — round-trip к модели, а не `fork`.

### 6. Мультирантаймовость — здесь надо разделить две разные оси

Их путают, и заявки становятся несопоставимыми:
- **CLI-агенты за одним контрактом:** Orca — «any CLI agent», 28 перечислены; Multica — 26;
  Paseo — 5; **мы — 4**. По этой оси мы позади всех, кроме Paseo.
- **Провайдеры моделей:** omp — «60+ providers … one /model away». У нас модель выбирается на
  воркера внутри четырёх рантаймов, отдельного каталога провайдеров нет.

### 7. Персистентность

Наша сторона измерена, а не заявлена: `sessions` боевой БД, 431 завершённая сессия воркера,
медиана жизни 0,8 ч, p90 130,6 ч, максимум 531,8 ч (22 дня), дольше суток прожили 81; медиана
ходов на сессию воркера — 77,5, максимум 1 497. У соседей сопоставимого механизма в
первоисточниках не нашёл: у cmux это «resume when hooks have saved a native session ID», у Paseo и
Multica — демон, который держит процессы, пока жив сам.

---

## Чем это отличается от субагентов Claude Code и Codex

Вопрос правильный, и ответ не в нашу пользу настолько, насколько кажется: **за 2026 год субагенты
догнали половину того, что раньше было отличием Orchestra.**

### Что умеют субагенты Claude Code (первоисточник — `code.claude.com/docs/en/sub-agents`, 02.09.2026)

- Свой контекст: «Each subagent runs in its own context window with a custom system prompt,
  specific tool access, and independent permissions», размер окна — «sized by its own model, not
  the parent's».
- Одноразовость с оговоркой: «Each subagent invocation creates a new instance rather than
  continuing an earlier one», но «To continue an existing subagent's work instead of starting over,
  ask Claude to resume it. Resumed subagents retain their full conversation history».
- **Общение между собой есть:** «Claude uses the `SendMessage` tool with the agent's ID or name as
  the `to` field to resume it».
- **Вложенность есть:** «By default, a subagent can spawn subagents of its own, up to three layers
  below the main conversation» (`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`).
- **Изоляция worktree есть, но по умолчанию выключена:** «A subagent starts in the main
  conversation's current working directory», а для копии репозитория — «set `isolation: worktree`».

### Что говорит OpenAI про субагентов Codex (первоисточник — `learn.chatgpt.com/docs/agent-configuration/subagents`, 02.09.2026)

- Параллельный запуск и сбор: «When many agents are running, Codex waits until all requested
  results are available, then returns a consolidated response», субагенты возвращают «summaries
  instead of raw intermediate output».
- Изоляция наследуется, а не создаётся: «Subagents inherit your current sandbox policy».
- Прямое предупреждение про запись: «Be more careful with parallel write-heavy workflows, because
  agents editing code at once can create conflicts and increase coordination overhead».
- Цена: «Because each subagent does its own model and tool work, subagent workflows consume more
  tokens than comparable single-agent runs».
- Локальная проверка бинарника (`codex --help`, 02.09.2026): есть команда `agents` — «Browse all
  agent sessions on the shared local app-server daemon», то есть у Codex тоже есть общий демон с
  сессиями агентов.

### Настоящая разница, которую можно предъявить инженеру

1. **Время жизни.** Субагент живёт внутри разговора родителя: новый вызов — новый экземпляр,
   продолжение — только «попроси Claude его возобновить». Замер по нашей БД на таких же
   субагентах: **медиана 12,5 с, p90 75,1 с, максимум 587,2 с**, дольше 10 минут — 0,0%. Воркер
   Orchestra — отдельный процесс с записью в SQLite, который переживает рестарт платформы,
   гибернирует и возвращается тем же нативным тредом: **p90 130,6 ч, максимум 531,8 ч**. Это
   разница не в настройке, а в том, кому принадлежит жизненный цикл: там — родительскому
   разговору, здесь — базе.
2. **Границы вендора.** Субагенты Claude Code — это Claude, субагенты Codex — это Codex. Модель
   можно менять, вендора — нет. У Orchestra воркер = отдельная CLI-сессия ЛЮБОГО из четырёх
   рантаймов, поэтому «написал Codex — ревьюит Claude» является штатным маршрутом, а не
   самодельной обвязкой.
3. **Ревью как гейт, а не как просьба.** У обоих можно попросить субагента-ревьюера. У нас ревью
   стоит на пути мержа: работа не попадает в main мимо него, и мержем распоряжается не тот агент,
   который писал код.
4. **Всё, что вокруг кода.** Учёт задач с приоритетами, привязка ветки к задаче, квоты по пулам
   подписок, мост в Telegram, дашборд, durable-доставка сообщений между агентами. Субагенты — это
   примитив внутри одного CLI; Orchestra — контур вокруг нескольких CLI.
5. **Чего у нас нет, а у них есть.** Вложенность субагентов до трёх уровней из коробки и `Task`
   как обычный тул внутри одного процесса — у нас порождение воркера стоит дороже (отдельная
   сессия, ветка, worktree), и мы его прямо запрещаем воркерам. Для «сходи посмотри в двадцати
   файлах и вернись» субагент дешевле нашего воркера, и это правильный инструмент для такой
   задачи.

**Формулировка, которую не стыдно дать инженеру:** субагенты решают задачу «разгрузить контекст
одного агента на время одного разговора». Orchestra решает задачу «держать флот агентов разных
вендоров неделями, с задачами, ветками, ревью и мержем». Пересечение большое и растёт; отличие —
в собственнике жизненного цикла и в том, что через границу вендора субагент не ходит.

---

## Где мы объективно слабее

1. **Широта рантаймов.** 4 против 26–28 у Orca и Multica. Наш контракт бэкенда закрыт кодом, чужой
   CLI не подключается конфигом.
2. **Скорость тулов.** Каждый тул-вызов у нас — внешний процесс: измеренные 3,7 мс против 20 мкс,
   из которых 2,2 мс — цена самого `fork+exec`. У omp этой цены нет по построению.
3. **Ничего похожего на LSP/DAP в тулах.** У omp 14 LSP- и 28 DAP-операций доступны агенту; у нас
   агент читает файлы и зовёт `grep`.
4. **Интерфейсы.** У Orca — десктоп и мобильные приложения, у Paseo — десктоп/веб/мобильный клиент
   и голос, у cmux — нативные панели терминала. У нас веб-дашборд и Telegram.
5. **Установка.** У них `brew install` / AUR / готовый Docker-образ / релизные бинарники. У нас
   `git clone` + `uv sync` + свои CLI и подписки.
6. **Масштаб проекта.** Один сопровождающий, 3 звезды, одна боевая инсталляция и одна вторичная.
   Всё, что здесь сравнивается, — архитектура, а не зрелость продукта.
7. **Изоляция исполнения.** Worktree разделяет ФАЙЛЫ, но команды агента исполняются на хосте; у
   Codex субагент наследует sandbox-политику, у omp есть своя крата изоляции рабочего дерева.
   Нашего эквивалента нет.

## Что осталось непроверенным (и почему)

- Изоляция и межагентный обмен у Multica и cmux, ревью у cmux — README не содержит, документация
  живёт на их сайтах; одного захода на сайт для честной ячейки мало.
- `herdr` целиком — см. причину выше.
- Любые сравнения производительности САМИХ продуктов между собой: ни один из шести не публикует
  воспроизводимых замеров, а стенд под шесть разных установок в эту задачу не входил.
- Reddit-обсуждения и отзывы пользователей: с этого сервера Reddit отдаёт `403` (см. #502).

## Побочная находка, требующая правки ПУБЛИЧНОГО README

Строка «Sub-agents spawned — **5 593**» в разделе «Built by Itself» **вводит в заблуждение**.
Проверка таблицы `subagents` по обеим базам 02.09.2026:

| Установка | `local_bash` | `local_agent` | `codex` | пусто | Итого |
|---|---:|---:|---:|---:|---:|
| основная (числа README) | 5 398 | 151 | 46 | — | 5 595 |
| вторая (VPS) | 5 014 | 5 | 13 | 11 | 5 043 |

То есть **96,5% строк — это фоновые bash-задачи**, а не порождённые агенты. Настоящих суб-агентов
на основной установке 197. В публичном тексте это читается как «мы породили 5 593 агента», что
неправда. Правка не в моих границах (владею `docs/tasks/503/`, `docs/kb/`,
`docs/workers/readme-refresh.md`) — передаю оркестратору: либо переименовать строку в «Background
tasks and sub-agents recorded», либо поставить 197 и назвать это суб-агентами.

## Источники

Все проверены 02.09.2026.

- `gh api repos/{stablyai/orca, can1357/oh-my-pi, multica-ai/multica, getpaseo/paseo,
  manaflow-ai/cmux, herdrdev/herdr, BloopAI/vibe-kanban, DrSeedon/orchestra}` — звёзды, `pushed_at`,
  лицензия, язык.
- README указанных репозиториев через `gh api repos/<r>/readme` (raw, не веб-страница).
- `code.claude.com/docs/en/sub-agents` — субагенты Claude Code.
- `learn.chatgpt.com/docs/agent-configuration/subagents` — субагенты Codex.
- `stencil.so/blog/the-harness-problem` (редирект с `blog.can.ac`) — их пост про harness; проверен
  на отсутствие замеров задержки.
- `codex --help` на этой машине — наличие команды `agents` и общего app-server демона.
- Боевая БД Orchestra (read-only копия через `sqlite3.Connection.backup`) — время жизни сессий,
  длительности субагентов, распределение `task_type`.
- `/tmp/bench_spawn.py` — замер in-process против fork+exec, 40 повторов, чередование ветвей.
