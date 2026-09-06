# Архитектура Orchestra

> **Как читать якоря на код.** Диапазоны вида `app/manager.py:594-636` во всех файлах портфолио,
> кроме переснятого `04-stack.md`, взяты на дереве `fbed73a377cce04bf7bb03c46eba6252d71bdda0`
> (28.08.2026) и разрешаются командой `git show fbed73a3:<путь>`. Проверка 06.09.2026: из 107
> таких якорей 24 указывают на тот же текст в `main`, 83 сместились — код рос, а миграция
> раскладки 03.09.2026 (#430) переименовала пути, не переписывая ссылки внутри файлов.
> Ссылки на артефакты (`.orchestra/tasks/...`) актуальны и разрешаются в текущем дереве.

## 1. Оркестратор → воркеры → worktree → merge

### Какую проблему решает

Один управляющий агент держит контекст задачи и принимает lifecycle-решения, а исполнители получают ограниченную роль, задачу и файловую зону. Создание сессии наследует pipeline/profile родителя, проверяет право на spawn до side effects и запрещает пересечение `owned_dirs` у живых работников (`app/manager.py:594-636`, `app/manager.py:685-739`, `app/manager.py:701-727`, `app/manager.py:762-767`).

Каждый coding-worker получает отдельный Git worktree и ветку `task-<N>/<worker>`; создание ветки и worktree сериализовано repository lock (`app/workspace.py:492-538`). Merge также проходит под repository lock: сервер проверяет неизменность worker/target HEAD, чистоту дерева и конфликт через `git merge-tree`, затем делает squash и один commit (`app/workspace.py:1229-1265`, `app/workspace.py:1267-1359`, `app/workspace.py:1463-1531`, `app/workspace.py:1594-1666`).

Поток данных:

```text
задача и AC
    ↓
оркестратор — декомпозиция, модель, роль, owned_dirs, приёмка
    ↓ spawn
worker — отдельная ветка + worktree, изменения и локальный commit
    ↓ DONE
merge_worker — HEAD/dirty/conflict/task-ref gates → squash commit
    ↓
main + receipt в трекере
```

### Кто чем владеет

| Владелец | Зона ответственности | Якорь |
|---|---|---|
| Оркестратор | выбор задачи и исполнителя, task context, роль/pipeline, проверка результата и решение о merge | `app/manager.py:594-636`; `.orchestra/pipelines/default/prompts/roles/orchestrator.md:1` |
| Worker | только назначенные `owned_dirs`, свой worktree, commit и доказательства | `app/manager.py:701-727`; `app/workspace.py:492-510` |
| Orchestra server | уникальность сессии, spawn authorization, Git lock, merge precheck, squash/rollback/receipt | `app/manager.py:608-670`; `app/manager.py:762-790`; `app/workspace.py:1229-1265`; `app/workspace.py:1594-1666` |
| Pipeline manifest | допустимая иерархия ролей и системный prompt | `app/manager.py:741-767`; `app/pipeline.py:1` |
| Git | reviewable рабочий результат и история принятого состояния | `app/workspace.py:944-969`; `app/workspace.py:1594-1666` |

### Что отвергнуто

- **Общий checkout для всех агентов.** Один автоматически записанный bug report раньше оставлял checkout грязным и блокировал все merge; хранилище репортов вынесли из Git lifecycle (`#114`, commit `4b7814b`). Worktree изолирует рабочие деревья, а `owned_dirs` запрещает логическое пересечение ещё до старта (`app/manager.py:701-727`).
- **Ручной merge как штатный путь.** Он обходит проверку target HEAD, конфликтов, task refs, squash-message и commit receipt; все эти проверки собраны в `merge_worktree_to_main` (`app/workspace.py:1229-1246`, `app/workspace.py:1313-1359`, `app/workspace.py:1463-1531`, `app/workspace.py:1627-1666`).
- **Считать SHA worker-коммита доказательством попадания в `main`.** Merge squash-ит N worker commits в один новый commit, поэтому исходные SHA по построению не входят в `main`; проверяется content/receipt, а не ancestry исходного SHA (`app/workspace.py:944-969`; `#323`).

## 2. Runtime-абстракция: Claude, Codex, Grok и Harness

### Какую проблему решает

У runtime разные transport и lifecycle semantics, но сессии нужен единый минимальный контракт. `BackendLike` фиксирует `session_id`, `connect`, `send`, `events`, `interrupt`, `disconnect`; `RuntimeDefinition` отдельно хранит capabilities и factory (`app/backend_protocol.py:8-16`; `app/runtime_registry.py:29-40`, `app/runtime_registry.py:78-126`). `AgentSession` получает runtime из model registry, собирает общий `BackendBuildContext` и создаёт adapter через `build_backend` (`app/session.py:823-869`).

| Runtime | Реализация за общим контрактом | Измеренное/закодированное отличие |
|---|---|---|
| Claude | `claude-agent-sdk`, persistent stream | `event_stream="persistent"`, reconnect/hibernate/mid-turn inject включены (`app/runtime_registry.py:171-210`, `app/runtime_registry.py:332-347`) |
| Codex | установленный CLI `app-server --stdio`, native thread | per-turn stream, process liveness, hibernate; production call path подтверждён в #240 (`app/runtime_registry.py:213-273`, `app/runtime_registry.py:348-360`; `.orchestra/tasks/240/architecture-snapshot.md`) |
| Grok | CLI JSON-RPC session | per-turn stream, без mid-turn inject и hibernate (`app/runtime_registry.py:276-314`, `app/runtime_registry.py:361-375`) |
| Harness | собственный in-process tool loop над OpenRouter | per-turn stream; JSONL session store рядом с DB (`app/runtime_registry.py:317-327`, `app/runtime_registry.py:376-388`; `app/backend_harness.py:203-212`) |

Capability flags не декоративны: `build_backend` проверяет, что adapter действительно реализует заявленные reconnect/process-liveness/model-retarget методы (`app/runtime_registry.py:109-126`).

### Что отвергнуто

- **Один adapter с одинаковым поведением для всех.** Это заставило бы либо обещать Grok steering/hibernate, которых нет, либо урезать Claude/Codex до наименьшего общего знаменателя. Вместо этого общим сделан transport-contract, а различия — явными capabilities (`app/runtime_registry.py:29-53`, `app/runtime_registry.py:330-388`).
- **Считать Codex Python SDK.** Реальный production path — CLI `app-server --stdio`; A/B показал, что сам Python wrapper не объясняет большую задержку: local JSON-RPC median 0.058 ms, а app-server против `codex exec` отличался на +0.270/+0.756 s total-to-final (`.orchestra/tasks/240/measurements.md`, разделы `No-model controls` и таблица A/B; #240).
- **Переключать runtime без явного handoff.** При cross-runtime switch native `session_id` сбрасывается, сохраняется bounded text tail и запись в `session_id_history`; Orchestra не делает вид, что provider-native threads совместимы (`app/session.py:3405-3464`).

## 3. Персистентность: рестарт, hibernate и compact

### Какую проблему решает

Состояние разделено на четыре уровня, чтобы смерть одного процесса не означала потерю всей задачи:

1. **Operational envelope в SQLite:** имя/scope/model/prompt/status/native `session_id`, worktree/branch, role/parent, task, counters и последнее summary (`app/db.py:48-77`; `app/db.py:1245-1360`; `app/session.py:5126-5165`).
2. **История UI и recovery:** `logs` привязаны к immutable session id; запись вынесена в DB executor и ошибки не глотаются (`app/db.py:116-126`; `app/session.py:5049-5100`).
3. **Native runtime state:** Claude/Codex/Grok возобновляются по provider/CLI session id; Harness хранит один crash-tolerant JSONL на сессию с fsync и atomic replacement после compact (`app/session.py:823-869`; `app/harness/sessions.py:1-27`, `app/harness/sessions.py:44-99`, `app/harness/sessions.py:100-127`).
4. **Рабочий результат:** Git branch/worktree и project memory лежат вне model context; worker memory снова инжектируется при spawn (`app/manager.py:750-755`; `app/workspace.py:492-538`).

На старте `auto_resume_all` читает `running/interrupted/idle/waiting`, восстанавливает сначала orchestrators, затем workers, усыновляет сохранённые CLI pipes либо загружает native session id и шлёт restart notice только реально прерванным (`app/manager.py:2207-2258`, `app/manager.py:2263-2329`). Lifespan запускает это до восстановления фоновых jobs и merge operations (`app/main.py:378-434`).

Compact не унифицирован искусственно. Codex делает native compact в том же thread; Claude получает структурированный handoff и новый native session id, после чего роль re-inject-ится (`app/session.py:536-553`; `app/session.py:2641-2703`; `app/session.py:2724-2765`; `app/session.py:2996-3019`).

### Что отвергнуто

- **Только память Python-процесса.** `auto_resume_all` восстанавливает сессии из SQLite и native IDs после process restart; in-memory-only состояние не прошло бы этот путь (`app/manager.py:2207-2329`).
- **Compact как durable memory/«забыть старое».** Summary остаётся частью session lifecycle, но проектные знания и рабочий результат живут в Git; старый `session_id` сохраняется в истории, а новый prompt доставляется заново (`app/session.py:2996-3019`; `app/manager.py:750-755`).
- **Один алгоритм compact для всех runtime.** Текущая policy различает Claude handoff и Codex native compact; для Grok/Harness автоматическая policy отсутствует, а не симулируется (`app/session.py:536-553`).

## 4. Фоновые задания

### Какую проблему решает

Долгая команда, таймер, cron или наблюдение за внешним состоянием не должны удерживать model turn и исчезать при hibernate. `bg_create` создаёт server-side job типов timer/file/command/ssh/run/cron/cron_command и явно обещает wake target после результата (`app/mcp_stdio.py:2859-2906`).

Job сначала записывается в SQLite, затем запускается server task; при рестарте active jobs перечитываются и запускаются снова (`app/bg_jobs.py:333-395`; `app/bg_jobs.py:397-446`; `app/bg_jobs.py:474-510`; `app/db.py:460-480`). Trigger захватывается atomic compare-and-set `active→triggering`, адресат разрешается по immutable session id, а результат доставляется как versioned injected message (`app/db.py:2437-2445`; `app/bg_jobs.py:531-580`).

### Что отвергнуто

- **Фоновый child процесса агента.** Такой child привязан к lifecycle CLI/turn и не даёт серверу durable receipt; поэтому background execution принадлежит `BgJobManager`, хранится в `bg_jobs` и восстанавливается из DB (`app/bg_jobs.py:1`; `app/bg_jobs.py:474-510`).
- **Polling моделью.** Он расходует отдельный model request на каждую проверку и ломает hibernate. Вместо этого watcher выполняется сервером, а model session получает одно событие завершения (`app/bg_jobs.py:397-446`; `app/bg_jobs.py:563-582`).
- **Wake по имени.** Имя можно переименовать или переиспользовать; код отказывается будить без immutable `target_session_id` (`app/bg_jobs.py:539-560`).

## 5. Git-canonical JSON и knowledge при существующем SQLite

### Какую проблему решает

SQLite хорош для запросов и ограничений, но один DB-файл плохо отвечает на вопросы «какая версия факта была принята», «какой task/evidence её поддерживает» и «что приедет в clone». Canonical task store поэтому хранит per-task `state.json`, отдельные event/evidence JSON и content-derived `canonical_head`; SQLite содержит content-bound projection (`app/ia/task_store.py:1`; `app/ia/task_store.py:308-390`; `app/ia/task_store.py:411-451`; `app/ia/task_store.py:698-729`).

Разделение владельцев выглядит так:

| Слой | Назначение | Что считается истиной |
|---|---|---|
| Git JSON/Markdown | review, diff, provenance, immutable events/evidence, portability | canonical record + Git commit/blob (`app/ia/task_store.py:338-358`; `app/ia/knowledge.py:701-763`) |
| SQLite current/FTS | быстрый current-state query, uniqueness/constraints | только projection, связанная с exact canonical head (`app/ia/task_store.py:319-333`; `app/ia/runtime.py:1633-1653`) |
| Vector index | semantic candidate retrieval | derived index с отдельным `indexed_head`, не independent truth (`app/ia/runtime.py:402-408`; `app/ia/runtime.py:1748-1750`) |
| Debt/receipts | видимая рассинхронизация и безопасный cutover | head-bound gate receipt (`app/ia/runtime.py:1633-1661`; `app/ia/runtime.py:1738-1756`) |

Проекция намеренно rebuildable: если task projection отсутствует/битая/устарела, runtime удаляет sidecars, пересобирает её из canonical states и проверяет равенство heads (`app/ia/runtime.py:74-102`). На копии живого корпуса из 1 545 JSON / 684 task states удалённая проекция восстановилась за 848.743 ms и вернула 684 строки с равным head (`.orchestra/tasks/408/measurements.md`, раздел `Deleted task-current.db probe`; #405).

### Почему не оставить только Markdown или SQLite

Первичный аудит #256 нашёл у Markdown-only контура source-link coverage 7/12, current index coverage 547/1 092 и freshness debt 545; retrieval R@5 для exact/current/rejected был 33.3%/33.3%/50.0% (`.orchestra/tasks/256/research.md:95-126`). Поэтому Markdown остаётся human evidence, но typed identity/status/supersession и head receipts принуждаются кодом.

DB-only вариант тоже отвергнут: SQLite даёт ACID/constraints/current query, но не должен становиться второй непроверяемой truth, оторванной от Git review и clone (`.orchestra/tasks/256/research.md:151-157`, `.orchestra/tasks/256/research.md:298-303`).

### Что ещё отвергнуто

- **Graph/LLM как canonical resolver противоречий.** В исследованном production-case Graphiti были 3 ложных retirement из 4 audit cases; семантика может предлагать candidate, но не отзывать факт (`.orchestra/tasks/256/research.md:52-55`, `.orchestra/tasks/256/research.md:167-179`; #256).
- **Один append-only JSONL для всех задач.** Он становится merge-hotspot для независимых writers; per-task state/events дают конфликт ровно на общей identity, а не на хвосте общего файла (`.orchestra/tasks/299/research.md`, раздел про primary write shape; #299).
- **Считать central store конечным владельцем знаний всех проектов.** Принятое направление — `<project>/.orchestra/kb/`; research #412 прямо отмечает, что кодовый cutover ещё требует смены шести owners. Поэтому текущий central canonical описан как действующий gen3 owner, а project-local раздача — запланированная, но не выданная за завершённую (`.orchestra/tasks/412/research.md`, разделы `Зафиксированное решение пользователя`, `3. Кто должен узнать`, `4. Порядок раздачи`).

## Авторство и границы заслуги

Максим владеет продуктовым направлением, правилами prompt/pipeline, архитектурными решениями, approval и финальной приёмкой; worker sessions выполняют значительную долю research, кода и тестов. Отчёты фиксируют model/runtime автора отдельно: durable Telegram delivery выполнял `gpt-5.6-sol`, а batch-review — `gpt-5.6-luna` (`.orchestra/tasks/333/report.md`, раздел `Review`; `.orchestra/tasks/402/report.md`, раздел `Review`). Git author identity этого различия не хранит: в текущей истории 2 913 коммитов подписаны `Maxim`/`DrSeedon`, 20 — foreign `vadimd`, 1 — служебный `Orchestra`; это ownership history, не доказательство ручного набора каждой строки (`docs/portfolio/04-stack.md:93-113`).
