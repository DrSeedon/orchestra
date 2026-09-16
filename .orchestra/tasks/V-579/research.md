# V-579: разбор alphaXiv/OpenResearch по исходникам

Дата среза: 16.09.2026. Исследован commit `325eb509dc8e4ca7074568cf0ae1f0f98704eac0` (latest commit на момент среза, `Add Hindi (hi) locale (#351)`). Репозиторий клонирован только для чтения в `data/OpenResearch/`; этот путь попадает под `.gitignore` и в наш Git не добавлялся. Установщик `orx install-skills` не запускался.

## Короткий вывод

OpenResearch — не «универсальный автономный исследователь» внутри одного алгоритма. В репозитории есть рабочий Rust CLI/dashboard: локальные проекты, Git-ветки экспериментов, SQLite-реестр запусков, detached supervisor, потоковые логи и адаптеры local/SSH/Slurm/Kubernetes/Ray/Hugging Face/Modal/Tinker/OpenResearch. Автономный научный цикл и правила выбора следующей гипотезы почти целиком заданы Markdown-системными инструкциями.

Главная технически законченная часть — воспроизводимость *кода запуска*: перед каждым запуском `git archive` фиксированного commit превращается в SHA-256-адресуемый tar-архив, а backend получает этот архив, а не рабочее дерево. «Заморозка узла после отвеченного run» не реализована в данных или Git-предохранителях: это правило `orx-experiment-tree`/`orx-git`, тогда как SQLite-метод обновления узла остаётся общим и не проверяет наличие run.

Для Orchestra сейчас не следует переносить их полный experiment-tree loop: наши worktree и merge уже решают изоляцию, проверку голов, приемку и восстановление, а рабочие изменения платформы обычно не являются повторяемыми научными прогонами. Полезен только узкий переносимый принцип — если у нас появится настоящий внешний вычислительный run, привязывать его к неизменному commit/archive и хэшу результата. Это предложение, не внедрение в рамках данного исследования.

## 1. Модель эксперимента, run и snapshot

### Узел эксперимента

Тип `LocalExperiment` (`src/local/model.rs:66-104`) содержит:

* `id`, `project_id`, `parent_experiment_id` (`NULL` для root/baseline);
* `slug`, `branch_name` (`orx/<slug>`), `title`, `description`;
* `run_command`, `agent_status`, timestamps и необязательный `chat_session_id`.

Таблица `local_experiments` (`src/store.rs:443-457`) хранится в локальном SQLite `orx.db`. При создании `src/local/experiments.rs:72-128` сначала выполняется `git branch --no-track <new> <parent-branch>` (или ветка от `baseline_branch`), затем записывается строка. Дочерний узел получает parent branch и копию run command; базовая ветка проекта сама узлом не считается для новых root.

Важные отрицательные результаты по модели:

* нет `frozen`, `answered_at`, `answered_run_id`, метрики победителя или ссылки узла на snapshot;
* нет отдельной таблицы lineage/edges — parent хранится одним foreign-key-подобным текстовым полем без SQL `REFERENCES`/циклической проверки;
* `update_local_experiment` (`src/store.rs:1766-1781`) обновляет title/description/run command/status и даже branch/parent без проверки run history; публичный CLI реально использует его для `orx exp desc` (`src/plane/local_plane.rs:228-239`). Значит, запрет редактировать отвеченный узел декларативный.

`orx-experiment-tree/SKILL.md` (217 строк) задаёт четыре заявленные дисциплины: branch от подтверждённого победителя; не менять узел после отвечающего run; фиксировать run command+environment; после двух безответных repair-run спрашивать человека. Там же описан stacked-bush и auto-research loop (repair/refill/promote/stop). В Rust-коде нет реализации выбора winner, repair cap или promote.

### Run

`StoredRun` (`src/store.rs:202-216`) и таблица `runs` (`src/store.rs:417-428`, миграции там же) содержат `id`, experiment/project IDs, status (`starting`, `running`, `done`, `failed`, `cancelled`), serialized `backend_json`, эффективную `command`, timestamps, exit code, `commit_sha`, `result_markdown`, cancel intent и chat attribution.

Статусы технически защищены: `RunStatus::can_transition_to` делает три terminal-состояния поглощающими; SQL `update_status` (`src/store.rs:981-1004`) принимает изменения только из `starting`/`running`. Повторный run — новая строка с новым UUID, а `latest_run_for_experiment` просто выбирает последнюю по `created_at` (`src/store.rs:1055-1074`). Это заморозка *исхода конкретного run*, не заморозка узла.

Логи разделены от БД: append-only `data_dir()/run-logs/<run_id>.log` (`src/store.rs:1-5, 193-196`). Для local backend дополнительно создаётся `data_dir()/local-runs/<run_id>/` с `run.sh`, `log`, `pid`, `exit_code` (`src/jobs/localbox.rs:1-34, 45-91`). Detached `orx supervise` переоткрывает каталог и обновляет SQLite; provider handle дублируется в `submission-handles/<run_id>.json` (`src/compute.rs:830-870`).

### Source snapshot

`SourceSnapshot::create` (`src/compute.rs:25-75`) — самая сильная часть:

1. читает `HEAD` именно `refs/heads/<experiment.branch>` через `git rev-parse`;
2. выполняет `git archive` этого commit в новый временный tar;
3. считает SHA-256 и размер;
4. атомарно устанавливает файл как `data_dir()/source-snapshots/<digest>.tar` (при необходимости также zip для Ray);
5. кладёт digest/path/size в `BackendDescriptor` и commit SHA в run row.

Каталог snapshot принадлежит текущему UID и имеет mode 0700, файлы — 0600 (`src/compute.rs:150-223`). `SourceSnapshot::from_run` проверяет существование архива и заново сверяет digest и size (`src/compute.rs:77-119`). Скрипты backend распаковывают этот архив в отдельный `repo` и запускают command (`src/compute.rs:225-265`). Поэтому изменение рабочего дерева или ветки после submit не меняет уже переданный код.

Это не полный immutable execution contract. `command` сохраняется в run row, но environment не имеет snapshot/hash-поля: local backend собирает synced env, PATH и shell environment непосредственно при submit и записывает часть в owner-only `run.sh` (`src/local/localrun.rs:64-122`). `run_command` узла технически наследуется только при создании (`src/local/experiments.rs:103-111`), а затем mutable через store. Следовательно, skill-правило «command+env fixed» не обеспечивается схемой.

### Auth и telemetry: проверка двух исходных тезисов

Тезис «remote mode без authentication» требует уточнения.

* Обычный `orx up` действительно слушает только `127.0.0.1` и передаёт `remote_auth = None` (`src/commands/up.rs:50-70`); router при `None` не добавляет auth middleware (`src/commands/up.rs:701-707`). Пользователь того же host, имеющий доступ к loopback, может обращаться к dashboard/API без application bearer.
* Предназначенный `orx up --remote` путь в текущем commit запускает persistent remote-host: создаётся `RemoteAuth`, router применяет `require_remote_auth`, а все обычные API-запросы требуют Bearer (`src/commands/up.rs:53-57, 710-747`). Клиент генерирует token, передаёт его через SSH stdin, проверяет authenticated health и сохраняет token для gateway (`src/commands/up_remote.rs:908-1014, 1080-1109`). Control channel — Unix socket mode 0600 плюс проверка peer UID (`src/commands/remote_host.rs:277-317`).

Итак, в текущем коде запланированный remote-host auth есть, но обычный loopback-сервис — нет. README всё ещё утверждает без оговорки «remote service ... has no application-level authentication» (`README.md:80-82`), что расходится с реализацией persistent remote-host. Риск shared-host loopback остаётся; для Orchestra это решение не брать.

Тезис «telemetry enabled by default» подтверждён для official production builds. `main` создаёт `TelemetrySession` до dispatch (`src/main.rs:894-908`), а `is_enabled` отключает только development build, `ORX_TELEMETRY_ENV`, `--no-telemetry` или persisted `orx telemetry off` (`src/telemetry.rs:505-564`). Иными словами, отсутствие настройки = отправка. Доставка идёт на `https://api.openresearch.sh/analytics/v1/cli-events`, с disk outbox и коротким flush (`src/telemetry.rs:682-705, 802-848`). Отправляемые события не ограничены одним coarse install event: есть command, harness/skill, experiment started, first action, onboarding и т.п.; профиль onboarding включает выбранные research areas и введённый background (`src/telemetry.rs:906-920, 945-955`). Для Orchestra это не брать и не использовать как модель default.

## 2. Сопоставление с Orchestra

| OpenResearch | У нас уже есть | Чего нет / различие |
|---|---|---|
| `orx/<slug>` per-node branch и отдельный checkout | `app/workspace.py:create_worktree` создаёт `git worktree` на worker, ветку `task-<task>/<name>` и base от main или parent strategy (`app/workspace.py:523-567`; `app/manager.py:_resolve_base_branch`) | Нет отдельной сущности experiment-node и stacked-bush winner graph. Parent strategy — отношение сессий/веток, не научный результат. |
| Узел/run в SQLite | SQLite у нас — проекция и operational state; canonical tasks — Git | Нет first-class experiment/run table, которая связывает вариант, commit, command, output metric и parent. |
| Один task JSON + Git history | `app/task_store.py:1-5, 93-120, 215-263`: один `projects/<project>/tasks/<uuid>.json`, validated schema, immutable identity, revision hash, commit-per-write, file lock | Это task registry, не snapshot каталог исполняемых вариантов. На текущем checkout `git ls-files .orchestra/tasks` даёт 1653 tracked files; число 1755 из постановки не совпадает с текущим срезом. |
| Артефакты/evidence | `.orchestra/tasks/<id>/` — durable research/plan/report/evidence; task record имеет `evidence_refs` (`app/task_store.py:33-39, 80-90`) | Физический файл не автоматически является immutable snapshot кода и не обязан описывать команду/среду run. |
| Run logs и результат | `review_receipts` (`app/schema.sql:332-374`) и `app/run_receipts.py` связывают task-run с session, task snapshot ref, prompt hashes, usage/tool logs, review и terminal merge; `build_task_run_trace` строит trace read-time без копий | У нас нет OpenResearch-подобного detached scientific compute run, для которого надо архивировать проект перед submit. |
| Приёмка | `app/acceptance.py` выполняет зарегистрированную argv-команду в `shell=False`, различает passed/failed/inconclusive/skipped и умеет pinned oracle/manifest | Это контракт приемки изменения, а не оценка научной гипотезы; deliberately missing command может быть skipped с решением merge caller. |
| Merge | `app/workspace.py:1275+` под repo lock проверяет worker/target heads, clean trees, diff budget, merge-tree conflicts, делает squash; `app/merge_operations.py` сохраняет durable progress, partial/unknown, receipts и запрещает ручное обходное merge | Это строже и ближе к нашей реальности, чем OpenResearch node freeze: приёмка и восстановление учитывают races и неизвестный исход. После merge worker reset выполняется только по проверенному результату. |
| Заморозка | Terminal run outcomes в merge/review/run receipts нельзя произвольно переписать; task identity и task snapshot ref защищены | Нет общего правила «любая отвеченная ветка навсегда неизменна» — и это намеренно нужно для продолжения/исправления живой платформы. |

OpenResearch хранит локальный project repo/cache в `data_dir()/repos`, session worktrees в `data_dir()/worktrees/<project>/<session>` (`src/local/git.rs:48-76`), а experiments — branches в этом repo + строки `local_experiments`. У Orchestra worker worktree расположен в `worktrees/<repo-slug>/<worker>` рядом с продуктом (`app/workspace.py:26-35, 523-535`), а task Git store — отдельная canonical область с SQLite projection (`app/task_runtime.py:1-13, 30-57`). Это разные ownership boundaries; слияние их в одну experiment database не нужно.

## 3. Что можно взять (не более трёх)

### 1. Привязка внешнего run к immutable source — брать только при появлении такого run

Место у нас: слой task-run provenance (`app/db.py` `review_receipts`, `app/run_receipts.py`) и launcher/acceptance boundary рядом с `app/workspace.py`; дополнять следует commit SHA + content digest архива, а не вводить OpenResearch node table. Сейчас у нас уже есть `worker_head`, `target_sha`, `task_snapshot_ref` и `terminal_operation_id`, поэтому это будет узкое усиление для реального внешнего вычисления, не новый tree.

Цена: средняя/высокая — archive lifecycle, хранение и очистка/восстановление, проверка hash, размер и secret policy, плюс адаптеры внешнего backend. До появления повторяемого compute это лишняя запись и не окупается. Ценность: source drift и «какой код реально выполнялся» становятся проверяемыми.

### 2. Явно различать repair (run ничего не ответил) и answered result — брать как provenance, не как freeze

Место у нас: `review_receipts`/`task_run_receipt_finish` и `merge_operations` (`app/db.py:1340+`, `app/merge_operations.py`), с двумя исходами `answered`/`inconclusive` или эквивалентными failure codes. Это совместимо с нашей существующей моделью: ошибка acceptance может блокировать merge и быть исправлена, а успешный terminal outcome остаётся историей.

Цена: низкая/средняя — схема/миграция, маршрутизация статусов и тесты race/replay. Не переносить их жёсткий запрет редактирования узла: у нас repair живого кода — штатный путь.

### 3. Минимальный evidence packet для внешнего вычисления — взять контракт, не их plain-log-only дизайн

Место у нас: `.orchestra/tasks/<id>/` через существующие `evidence_refs`, с read-time trace в `app/run_receipts.py`; в packet достаточно ссылок/хэшей на commit, command, environment fingerprint, stdout/stderr и итог. Наши review/merge receipts уже связывают usage, logs, review и target transition, поэтому OpenResearch-стиль «печатай метрики в stdout» полезен только как рекомендация для нового backend.

Цена: низкая/средняя — формат и validator, без нового dashboard. Выигрыш — проверяемое свидетельство результата; ограничение — environment fingerprint не делает недетерминированную платформенную правку воспроизводимой.

## 4. Что не брать

* **Полный experiment-tree/stacked-bush auto-loop.** Он оптимизирует серию сравнимых гипотез; Orchestra обслуживает live platform changes, где parent branch может содержать параллельные исправления, а «winner» не определяется одной метрикой.
* **Freeze узла после любого answered run.** У нас это сломает исправление принятого результата, повторную проверку после race и обычное продолжение worker-задачи. Фиксировать следует commit/result receipt, не запрещать branch repair вообще.
* **Фиксированные command + environment как глобальный контракт.** Для OpenResearch это полезно в научном training sweep; у нас command, interpreter, provider, env и acceptance могут закономерно меняться между задачами. Технически OpenResearch сам не замораживает env hash, так что переносить следует только explicit provenance.
* **Remote service с доверием к host loopback.** В текущем коде ordinary `orx up` не имеет app auth, а даже persistent route требует правильного режима/SSH; shared host остаётся опасным. Orchestra не должен открывать аналогичный dashboard без auth.
* **Telemetry opt-out.** Production default — enabled, есть disk outbox и отправка user-entered onboarding background/areas. Для нашей локальной платформы default должен быть off и event payload должен быть отдельным согласованным контрактом; в эту задачу внедрение не входит.
* **`orx install-skills` и копирование всех 12 Markdown skills.** Установка пишет в пользовательские каталоги; кроме того, 11 operational skills не добавляют runtime механизма. Нужные правила Orchestra уже принадлежат нашим managed prompts/skills.
* **Plain append-only logs как единственная evidence truth.** OpenResearch run result — это прежде всего stdout/log + optional `result_markdown`; у нас уже есть richer receipts, pinned acceptance oracle и merge journal. Заменять их логом было бы регрессом.

## 5. Где подход сломается на нашей нагрузке

1. **Невоспроизводимость.** Фиксирование commit устраняет source drift, но не меняет живые внешние зависимости, provider state, network, model responses и race между агентами. Одинаковый `orx exp run` может иметь одинаковый code snapshot, но не одинаковый outcome. Для Orchestra metric winner и promotion будут создавать ложную уверенность.
2. **Неправильная единица изоляции.** OpenResearch считает узел вопросом и run — ответом; у нас единица работы — task + worker session + merge operation. Один worker может несколько раз менять код по обратной связи, а успешный merge должен пройти acceptance/receipt и вернуть работу в main. Freeze по первому «ответу» оставит платформенный дефект без repair path.
3. **Run command/env drift.** Наши задачи используют разные pytest subsets, interpreter selection, provider credentials и режимы; глобальный fixed command contract либо будет нарушен постоянно, либо начнёт описывать не реальную платформу.
4. **Конкурентность и неизвестный исход.** OpenResearch reserve lock разрешает максимум один run на node без `--force`, но его tree не является merge journal. У нас target branch может сдвинуться во время acceptance/merge; это уже обрабатывается `expected_target_head`, precheck, partial/unknown и durable operation state. Простое «взяли winner и branch» теряет именно этот риск.
5. **Стоимость и жизненный цикл артефактов.** SHA-архив на каждый внешний run, provider handles, logs и snapshot retention приемлемы для training jobs, но дороги и избыточны для коротких live edits. Их перенос без измеренной потребности увеличит disk/cleanup surface, не повышая безопасность merge.

## Проверки и ограничения

Проведены read-only проверки: `git clone --depth 1`, `git status --short --branch` в клоне, `git grep` по model/snapshot/freeze/auth/telemetry, чтение исходников Rust и наших Python/SQL модулей, подсчёт tracked `.orchestra/tasks`. Продуктовый `app/` не изменялся, сервисы и БД не запускались/не читались. Выводы о поведении OpenResearch — по указанному commit; README использован только для фиксации противоречия, не как источник модели.
