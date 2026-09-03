# #387 — Пять GitHub-проектов и применимость к Orchestra

Снимок: 24.08.2026. Исследованы текущие ветки репозиториев, официальные README/документация,
лицензии, структура кода, релизы и открытые технические ограничения. Никакого кода из проектов
в Orchestra не устанавливалось.

## Короткий вывод

Из пяти проектов два дают Orchestra действительно новые направления:

1. **OpenViking** — лучший кандидат на сравнительный shadow-пилот памяти. Брать не готовую
   замену вслепую, а проверить и при удаче перенести три идеи: L0/L1/L2, иерархический поиск и
   наблюдаемый маршрут retrieval.
2. **Semantica** — лучший источник модели аудита решений. Не тащить весь пакет; добавить
   небольшой серверный provenance-граф поверх уже существующих task, receipt, review, merge и
   restart-событий Orchestra.

Остальные три полезны точечно:

- **Cloudflare Computer** — архитектурный ориентир для будущих удалённых/одноразовых сред
  исполнения, но сейчас preview, Cloudflare-specific и не является управлением экраном.
- **Omarchy** — не новая агентная платформа, а Arch-десктоп. Саму ОС нам ставить не надо;
  интересны единая панель квот нескольких машин, coredump → agent и snapshot перед обновлением.
- **Needle 2** — выдающаяся инженерия размера, но плохой кандидат для оркестрации: независимый
  пользовательский тест показал слабое заполнение аргументов и плохо калиброванный confidence.

## Сначала поправка к пересказу

| Проект | Что сказано в пересказе | Что это на самом деле |
|---|---|---|
| [cloudflare/computer](https://github.com/cloudflare/computer) | Агент управляет экраном | Durable Object с SQLite-файловой системой и тремя execution backend: Worker shell, Worker JavaScript, Linux container. GUI/screen control в публичном API не является сутью проекта. |
| [volcengine/OpenViking](https://github.com/volcengine/OpenViking) | Единая база памяти/знаний/скиллов | Полноценная context database: виртуальная FS, семантическая обработка, LLM-извлечение памяти, retrieval, rerank, multi-tenant, шифрование и MCP. |
| [basecamp/omarchy](https://github.com/basecamp/omarchy) | Linux, переосмысленный заново | Сильно opinionated дистрибутив поверх Arch + Hyprland + Quickshell, с curated desktop workflow. |
| [cactus-compute/needle](https://github.com/cactus-compute/needle) | 14 МБ модель | Текущий Needle 2 — 45M параметров, CQ2-bit, 14 МБ binary, около 28 МБ RAM; описание GitHub про 26M уже отстаёт от README. |
| [semantica-agi/semantica](https://github.com/semantica-agi/semantica) | Граф решений делает агентов прозрачными | Большая graph/KG/provenance библиотека. Она хранит переданное ей объяснение, но сама не доказывает, что объяснение модели истинно. Базовый ContextGraph in-memory, если явно не сохранить/не подключить backend. |

## Снимок зрелости

Данные GitHub API и текущих репозиториев на 24.08.2026:

| Репозиторий | Stars | Текущий релиз | Основной язык | Лицензия | Состояние |
|---|---:|---|---|---|---|
| cloudflare/computer | 8 562 | 0.2.1, 17.08 | TypeScript | MIT | Сам README называет продукт preview-only и непригодным для production |
| volcengine/OpenViking | 32 619 | 0.4.16, 21.08 | Python/Rust | AGPL-3.0 | Самый зрелый из пяти по поверхности: server, SDK, Helm, MCP, multi-tenant, benchmarks |
| basecamp/omarchy | 29 394 | 4.0.0, 14.08 | Shell | MIT | Живой пользовательский дистрибутив, но другой класс продукта |
| cactus-compute/needle | 8 791 | GitHub Release отсутствует | Python + нативный engine | Apache-2.0 | Быстро развивается; benchmark reproducibility и качество out-of-box оспариваются в issues |
| semantica-agi/semantica | 10 527 | 0.6.6, 20.08 | Python | MIT | Очень широкая поверхность, реальные ограничения честно перечислены в документации |

OpenViking и Semantica активны в день снимка. Большое число stars подтверждает внимание, но не
production-готовность и не применимость к нашей нагрузке.

## 1. Cloudflare Computer

### Что в нём крутого

Авторитетное состояние Workspace лежит в SQLite внутри Durable Object. Один и тот же workspace
можно исполнять тремя способами:

- быстрый bash-подобный shell в Worker isolate;
- структурированный JavaScript в Worker isolate;
- полноценный Linux container с сетью и настоящими бинарниками.

Контейнер видит workspace через FUSE и синхронизирует изменения с Durable Object. У исполнения
есть backend identity, UUID владельца процесса, retained log, reconnect и важная семантика:
если транспорт оборвался после возможного принятия команды, команда не переигрывается.

Это почти дословно тот класс проблем, который Orchestra закрывала в #380/#381: receipt до
неоднозначной внешней границы, fencing поколения и запрет replay после possible submit.

### Ограничения

- README прямо говорит: preview only, API нестабилен, production пока нельзя.
- Архитектура требует Cloudflare Workers, Durable Objects и Containers; на нашем Contabo это не
  библиотека, а отдельная платформа и новый операционный контур.
- Это не desktop computer-use: нет основного сценария screenshot → mouse/keyboard.
- Полный контейнер медленнее на cold start и тяжёлом последовательном I/O; FUSE требует sync.
- Наши Claude/Codex рантаймы используют подписочные логины и долгоживущие CLI-процессы. Их
  безопасный перенос в Cloudflare container отдельно не решён.

### Как применить к Orchestra

**Не внедрять сейчас.** Забрать четыре контракта в собственную архитектуру:

1. стабильный backend ID за единым execution API;
2. generation UUID для каждого принятого процесса/turn;
3. durable execution journal отдельно от живого process handle;
4. явный результат EEXEC_LOST/OUTCOME_UNKNOWN вместо творческого replay.

Практический смысл появится, когда Orchestra понадобится запускать много одноразовых worker
environments вне одного VPS или когда появится реальный GUI/browser runtime. До этого git
worktree + systemd + текущие backend-классы дешевле и проще.

## 2. OpenViking

### Что в нём крутого

OpenViking превращает context в адресуемую файловую систему:

- resource, memory и skill получают viking:// URI;
- L0 — короткий abstract, L1 — overview, L2 — полный материал;
- поиск сначала находит подходящую директорию, затем рекурсивно углубляется;
- complex search использует session context и LLM intent planner, затем rerank;
- маршрут retrieval сохраняется и виден оператору;
- session commit архивирует диалог, асинхронно извлекает память и дедуплицирует её;
- есть локальное/S3-хранилище, локальный/Volcengine vector index, persistent queues, path locks,
  crash recovery, multi-tenant и AES-256-GCM at-rest encryption;
- Codex plugin делает recall перед prompt, capture после ответа и commit перед compact.

Публичный benchmark заявляет рост LoCoMo accuracy до 80–83% и снижение input tokens на
34.3–91.0%, но это результат авторов на Doubao-моделях. Скрипты воспроизведения есть, однако
перенос результата на наш bge-m3, Codex/Claude и русский корпус не доказан.

### Сходство и отличие от Orchestra

У Orchestra уже есть:

- curated память в docs/workers, docs/kb и docs/tasks;
- semantic search по Markdown и agent messages через FastEmbed bge-m3 + sqlite-vec;
- обязательный search_memory перед исследованием;
- нативная история Claude/Codex и собственный compact lifecycle.

Не хватает именно того, в чём OpenViking силён:

- структурной иерархии поверх плоских chunks;
- L0/L1/L2 budgeted loading;
- видимого retrieval trace;
- измеренного session → memory pipeline.

При этом автоматическое извлечение памяти конфликтует с философией Orchestra: сейчас память
проходит явный human/agent judgement и коммит. Автоэкстрактор может превратить agent slop или
ошибочный вывод в долговременный «факт».

### Как применить к Orchestra

**Shadow-пилот, не миграция.**

1. На неизменяемом снимке нашего корпуса поднять OpenViking локально.
2. Индексировать только docs/kb, docs/tasks, docs/workers и очищенные agent messages.
3. Взять 50 реальных прошлых search_memory-запросов с известными ответами.
4. Интерливить current/OpenViking и измерить recall, полезность ответа, latency, input tokens,
   ложные уверенные находки и полноту retrieval trace.
5. Auto-memory выключить; сначала сравнить только retrieval.

Если OpenViking выигрывает, первый production-шаг — не замена vec.db, а L0/L1 sidecars и
retrieval trace в текущем API. Полное подключение оправдано только после измеренного выигрыша.

Лицензия AGPL совместима с текущей AGPL Orchestra, но прямое встраивание всё равно требует
сохранить notices и соблюдать network-copyleft.

## 3. Omarchy

### Что в нём крутого

Omarchy делает coding agents частью рабочего стола, а не отдельной программой:

- lazy-installed launchers для Claude Code, Codex, OpenCode, Gemini, Grok и других;
- один default agent и горячая клавиша запуска с готовым prompt;
- панель подписок Claude/Codex/Fireworks с 5h/weekly windows, tokens/day/model;
- объединение usage records с других машин через синхронизированную папку;
- systemd-coredump notification, которую можно передать агенту с diagnose-crash skill;
- обновление ОС как единая транзакция packages + migrations + config + snapshot;
- rollback snapshot из boot menu;
- agent skills синхронизируются в каталоги нескольких harness.

Это не просто косметика: авторы сделали opinionated workflow, где число вариантов сокращено и
правильный путь становится самым коротким.

### Ограничения

- Это полноценная Arch desktop OS, а не пакет для сервера.
- Установка может занять диск, требует выключить Secure Boot/TPM и меняет весь пользовательский
  environment.
- Rolling distribution и Hyprland имеют цену сопровождения.
- Наш VPS headless, а пользовательский ноутбук уже рабочий и содержит активную Orchestra;
  переустановка ради нескольких функций несоразмерна.

### Как применить к Orchestra

**Не ставить Omarchy. Заимствовать три узких решения по MIT:**

1. cross-machine reconciliation квот VPS + ноутбук вместо оценки только одной машины;
2. coredump → task/agent с точным PID и server-owned evidence;
3. snapshot/rollback gate перед обновлением runtime или system unit.

Отдельно стоит сравнить omarchy-agent-usage-claude/codex с нашими collectors: у Omarchy есть
fallback по локальным transcripts и слияние расхода разных harness. Это полезный контроль полноты,
но не новый source of truth поверх provider usage API.

## 4. Needle 2

### Что в нём крутого

- 45M parameters в 14 МБ CQ2-bit binary;
- около 28 МБ RAM на сессию;
- 256-token sliding window с pinned tool schemas;
- JSON ограничивается byte-level grammar из schema;
- отдельная retrieval head выбирает top-5 tools из большого каталога;
- отдельная confidence head позволяет эскалировать сомнительные ответы;
- inference офлайн; LoRA можно слить обратно в единый binary.

Это впечатляющий edge-компонент: маленький размер достигается не просто квантизацией, а
специализированной архитектурой и узким контрактом tool calling.

### Почему нельзя верить только красивой картинке

В репозитории график Mobile-Actions показывает Needle примерно на 64%, ниже LFM2.5 около 69% и
рядом с FunctionGemma около 64%; главное преимущество — размер, не безусловное качество.
Raw benchmark protocol/results в репозитории не найдены, а issue #34 прямо просит способ
воспроизвести цифры.

Независимый пользовательский эксперимент issue #61 на 16 испаноязычных tools получил:

- до fine-tune: 2/3 выбора tool и 0/3 правильных аргументов в одном сценарии;
- после около 300 примеров: retrieval улучшился, но fabricated arguments сохранились;
- perfect precision при confidence threshold покрыла только 1 из 8 случаев;
- автор отказался от внедрения для необратимых действий.

Выборка мала и сложна, поэтому это не общий приговор модели. Но это ровно наш риск-класс:
Orchestra вызывает merge, kill, deploy и внешние tools, где неправильный аргумент важнее скорости.

### Как применить к Orchestra

**Не использовать для worker/orchestrator turns и опасных tool calls.**

Допустим только отдельный пилот на обратимых low-risk intents:

- status / help / quota / list;
- извлечение полей из голосовой команды перед подтверждением;
- on-device/offline клиент в будущем.

На VPS Needle не решает актуальную боль: сеть и модельный inference уже есть, а deterministic
Python/router дешевле и надёжнее для короткого фиксированного набора команд.

## 5. Semantica

### Что в нём крутого

Semantica делает decision отдельным типом данных: scenario, reasoning, outcome, confidence,
decision maker и causal links. Поверх этого есть:

- precedent search;
- causal chain и downstream impact;
- policy checks;
- W3C PROV-O provenance;
- temporal snapshots;
- SHACL/OWL/SKOS governance;
- Rete, Datalog и SPARQL reasoning;
- Neo4j/FalkorDB/Neptune/AGE и RDF backends;
- MCP, REST, CLI и graph explorer.

Для Orchestra это концептуально точное попадание: сейчас task, user message, worker turn,
tool result, review, merge, restart и incident связаны, но связь размазана по таблицам и Markdown.

### Где маркетинг опережает контракт

- README называет decision permanent, но простой ContextGraph хранит nodes/edges/decisions в
  Python dictionaries. Персистентность появляется только после явного save_to_file или выбора
  внешнего backend.
- record_decision принимает reasoning от вызывающего. Граф гарантирует происхождение записи,
  но не истинность reasoning.
- Документация честно называет ограничения: упрощённый Rete matcher, partial provenance у
  нескольких backend, RDF4J repository_id без эффекта и другие adapter-specific gaps.
- Полная библиотека намного шире нашей задачи и добавит ontology/vector/graph dependency surface.

### Как применить к Orchestra

**Заимствовать модель данных, не пакет.**

Минимальный MVP:

- таблица provenance_nodes: server-owned event IDs и типы;
- таблица provenance_edges: CAUSED, BLOCKED_BY, REVIEWED, MERGED_AS, DEPLOYED_AS, RETRIED_FROM;
- distinction facts vs claims: server fact, user claim, agent claim;
- payload hash/source log ID/task ID/merge operation ID;
- один API causal-chain и простой dashboard view.

Не записывать скрытую chain-of-thought. Для reasoning хранить короткое опубликованное основание,
а server facts строить автоматически из уже существующих receipt/merge/restart событий.

Так мы получим 80% ценности Semantica без нового graph server и без превращения Orchestra в
enterprise knowledge platform.

## Приоритет действий

| Приоритет | Действие | Польза | Риск/цена |
|---:|---|---|---|
| 1 | Shadow-eval OpenViking retrieval против current search_memory | Проверит главную боль: память и context rot на реальном корпусе | Средняя; не менять production |
| 2 | Минимальный server-owned provenance graph по идеям Semantica | Объяснимые worker/merge/restart цепочки и расследования | Средняя; можно оставить SQLite |
| 3 | Сверить Omarchy multi-machine quota collectors с нашими | Найти расход ноутбука, которого не видит один VPS | Низкая; read-only pilot |
| 4 | Зафиксировать Computer contracts в future remote-runtime ADR | Подготовит масштабирование и безопасный exec | Низкая сейчас, высокая при внедрении |
| 5 | Needle low-risk intent benchmark | Может дать офлайн router, но актуальной боли нет | Низкий ROI; не для опасных calls |

## Что я бы сделал

Следующий практический тикет — **только OpenViking shadow-eval**. Он проверяемый и может либо
дать заметный выигрыш, либо дешёво закрыть модную гипотезу. Параллельно можно отдельно
спроектировать server-owned provenance schema по Semantica, но не внедрять оба изменения одним
тикетом: иначе нельзя будет понять, что именно улучшило систему.

## Источники и зафиксированные ревизии

- [cloudflare/computer](https://github.com/cloudflare/computer), clone de87919;
  [runtime/lifecycle docs](https://github.com/cloudflare/computer/tree/main/docs).
- [volcengine/OpenViking](https://github.com/volcengine/OpenViking), clone 9eac8a6;
  [architecture](https://docs.openviking.ai/en/concepts/01-architecture),
  [retrieval](https://docs.openviking.ai/en/concepts/07-retrieval),
  [sessions](https://docs.openviking.ai/en/concepts/08-session),
  [Codex plugin](https://docs.openviking.ai/en/agent-integrations/04-codex).
- [basecamp/omarchy](https://github.com/basecamp/omarchy), clone 43bfe9b;
  manual files shipped in the repository.
- [cactus-compute/needle](https://github.com/cactus-compute/needle), clone 7bd8a63;
  [independent user evaluation #61](https://github.com/cactus-compute/needle/issues/61).
- [semantica-agi/semantica](https://github.com/semantica-agi/semantica), clone 6c2ccfd;
  source for ContextGraph/DecisionRecorder and conservative storage feature matrix.

## Confidence

- Project identity, public architecture, license, releases, repository state: **confirmed**.
- Applicability recommendations: **high confidence** from direct comparison with current Orchestra.
- Performance/quality claims from project authors: **directional only** until reproduced on our corpus.
