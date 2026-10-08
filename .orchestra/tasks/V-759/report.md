# V-759 — ghidra-mcp: пригодность для Orchestra

Исследование, без установки и подключения. Исходники проверены на default branch `dev`, HEAD `162c82643d27f28e68217fa417b30698bc98b9d4` (2026-10-07 23:00 UTC). GitHub на момент проверки показывал `dev` как default branch. Отдельно сверены release v6.0.0 и текущий официальный release Ghidra.

## 1. Репозиторий и соответствие посту

Это общий Ghidra↔MCP мост для анализа программ, а не игровой MCP со специальным знанием игровых форматов. Описание поста в основном верно: GUI-плагин и headless-вариант, широкий каталог инструментов, анализ бинарей. README ревизии `dev` указывает 210 MCP catalog entries, 206 GUI endpoints и 191 headless endpoint; лениво загружает по умолчанию 84 endpoint-группы плюс 8 статических bridge tools, остальное модель может запросить позже. Release v6.0.0 на странице релизов отдельно заявляет 272 tools. Это разные версии/счётчики, поэтому «200+» подтверждается, но одно число нельзя переносить на все сборки.

Группы инструментов включают:

| Область | Примеры |
|---|---|
| Импорт и инвентаризация | импорт файла, функции, строки, глобальные данные, точки входа |
| Дизассемблирование и декомпиляция | `disassemble_function`, `force_decompile`, просмотр функций |
| Символы и связи | переименование функций/переменных, xrefs, call graph, labels |
| Типы и документация | создание/применение структур и enum, комментарии, bulk-документирование |
| Анализ | control/data flow, P-code, поиск byte patterns, dead code, malware indicators |
| Динамика | P-code emulation; GUI live debugger: память, регистры, breakpoints, step/resume |
| Проекты и обмен | сравнение программ, Ghidra Server repositories, check-in/check-out |
| Скрипты | создание/изменение/запуск Ghidra scripts; запуск произвольного Java-кода отключён по умолчанию флагом окружения |

**Лицензия:** Apache-2.0. В API репозитория на проверяемом срезе было 45 открытых issue-endpoint записей; GitHub UI показывал 38 issue items и 10 PR items (счётчики между срезами расходились). Активность подтверждена независимо от звёзд: последний commit в `dev` — 7 октября, issue/PR обновлялись 7 октября; release v6.0.0 датирован 25 июля. То есть проект живой, но development-ветка движется быстрее стабильного тега. Есть и расхождение по версии Ghidra: v6.0.0 release указывает 12.1.2, current `dev` README — 12.1.4. `SECURITY.md` говорит, что security review/fixes относятся к latest release и ветке `main`; default branch `dev` там отдельно не упомянута.

Требования из текущего README `dev`: Ghidra 12.1.4, Java 21, Python 3.10+ и `uv`/venv для Python bridge; документированный build path использует Maven, при этом Gradle wrapper включён в репозиторий. Сервер состоит из Python MCP bridge и Java-кода внутри Ghidra. При обычном GUI-пути устанавливается Ghidra extension/plugin и запускается Ghidra; на отдельном headless-пути предусмотрен `GhidraMCPHeadlessServer`, GUI не нужен. Headless не означает «без Ghidra или Java» — остаётся нужен runtime Ghidra. Bridge по stdio (или loopback HTTP) вызывает HTTP API плагина/headless-сервера. В v6.0.0 опубликованы отдельные артефакты: extension zip 728,120 bytes и Python wheel 67,283 bytes.

## 2. Реальный предмет для анализа на VPS

`list_orchestrators` на момент проверки показал `cog-second-brain-orchestrator` со scope `/opt/cog-second-brain` и описанием Balatro; также есть `Claude-Code-Game-Master-orchestrator` для D&D, University, проекты Comfy и остальные штатные проекты. Это подтверждает наличие предмета для игровых задач, но не автоматически предмета для Ghidra.

В `/opt/cog-second-brain/04-projects/balatro` лежат веб-страницы/инструменты, JS/MJS solver и explanatory tools, JSON-данные и PNG ассеты карт/джокеров. `/home/kesha/publish/balatro-solver/README.md` описывает браузерный упрощённый клон и solver. В проверенных путях нет оригинального Balatro executable, `.love`, DLL/SO, ROM или другого машинного бинаря; `/home/kesha/.cache/balatro` пуст. Steam/Balatro install не найден в проверенных пользовательских Steam-каталогах. Поэтому текущие задачи Balatro — это анализ правил, математической модели, веб-кода и ассетов, а не reverse engineering compiled game. D&D Game Master и ai-table — прикладные web/AI проекты, не найденный target binary. Обнаруженные bundled Python DLL в oil-paint runtime и старые `.so` в dependency cache — исполняемые зависимости проектов, не игры или выбранная цель reverse engineering. Покрытие: срез 10 записей `list_orchestrators`, корни проектов на VPS, релевантные Balatro/D&D директории и файловые шаблоны машинных бинарей под `/home/kesha/projects`; это не рекурсивный инвентарь всех файлов владельца вне этих проектов.

**Проверка ссылки на V-639:** `.orchestra/tasks/V-639/report.md` в этом checkout посвящён System One/Jev и отклоняет применение из-за отсутствия GPU/размеченного корпуса; это не Ghidra/игровой артефакт. Отдельный прямой прецедент об отсутствии предмета — запись ARTEMIS в `.orchestra/kb/runtimes.md`: мобильное Android-управление отклонили без Android-приложения/QA-устройства. Здесь есть реальный игровой проект, но пока нет исполняемого target binary; применять критерий «есть ли конкретный артефакт для целевого инструмента» точнее, чем считать весь Balatro-проект его предметом.

## 3. Подключение и цена на нашей стороне

Orchestra уже принимает собственные MCP серверы без правки приложения:

- `spawn_worker(..., mcp_servers=<JSON object>)` передаёт дополнительные server definitions конкретному воркеру; конфигурация сохраняется для него, добавляется к defaults, ключ `orchestra` зарезервирован и не может быть переопределён.
- Проектный `.mcp.json` и `.claude/settings.json` / `settings.local.json` читаются в scope проекта. Профильный user config (`~/.claude.json`) подключается только ролям, которым задан `mcp_servers: all`.
- Текущий `pipeline.yaml` имеет пустой `defaults.mcp_servers`; в ролях default pipeline нет `mcp_servers: all`. Следовательно, добавление сервера в один worker не требует и не должно означать публикацию всему парку.

Типовая архитектура upstream: MCP client → Python bridge → HTTP API локального Ghidra plugin/headless server. Для stdio bridge в README используется `bridge-mcp-ghidra`; bridge default для HTTP bind — `127.0.0.1`, а UI/backend API указан как localhost:8089. HTTP MCP transport по умолчанию тоже bind на loopback. В этом окружении уже установлен OpenJDK `21.0.12.1` и `uv`; `mvn` и команда `ghidra` в PATH не найдены, и Ghidra-каталог не обнаружен под `/opt` или `/usr/local` до depth 4. Это read-only проверка распространённых мест, не полный обход всего диска.

Официальный архив Ghidra 12.1.4 занимает 569,649,598 bytes (около 570 MB только скачанный zip). Extension/wheel меньше мегабайта суммарно; основная стоимость — сама Ghidra, распаковка, clone/build cache и Ghidra project/imported binaries, причём распакованный размер не измерялся, потому что ничего не ставилось. На VPS сейчас около 20 GB свободно при 94% заполнении диска: даже один архив равен примерно 2.9% текущего свободного места; реальная установка займёт больше. Java 21 уже есть, значит отдельная JVM для этого исследования не нужна; Ghidra же отсутствует.

**Безопасность:** это не read-only MCP. Каталог содержит rename/type/comment/create/delete, импорт и открытие файлов, изменение project data, debugger управление и интеграцию с Ghidra Server. Импорт бинаря сам по себе описан как анализ в Ghidra, а не запуск целевого executable; отдельно есть эмуляция функций и live debugger. Произвольный Java-script execution разрешается только при `GHIDRA_MCP_ALLOW_SCRIPTS=1` (по умолчанию выключен). При этом MCP tools могут менять локальную базу анализа, а серверный процесс работает с правами пользователя, который запускает Ghidra/bridge. `GHIDRA_MCP_FILE_ROOT` — опциональный filesystem-root gate для `import_file`, `open_project`, `delete_file` и подобных путей. Из этого следует риск доступа к доступным этому пользователю файлам, если tool вызван не по назначению или сервер не ограничен; это оценка по модели полномочий, не обнаруженная уязвимость. Строки/декомпиляция из чужого файла также могут стать prompt-injection входом агенту (инференс). Для внешнего bind README требует auth token; default loopback safer, но не изолирует сам Ghidra-процесс. Интеграция с внешним Ghidra Server/archive при отдельной настройке создаёт и риск передачи материалов наружу.

## 4. Вердикты

| Пункт | Вердикт | Основание |
|---|---|---|
| Общая reverse-engineering возможность для настоящего native binary | **Брать условно, под конкретную задачу** | В будущем подходит, если будет конкретный бинарь, который нельзя понять из исходников/документации и его анализ разрешён. Сейчас среди проверенных игровых проектов такого target нет. |
| Автоматически подключать глобально всем оркестраторам/воркерам | **Не брать** | Нет общего предмета; сотни изменяющих tools расширят поверхность полномочий и context/tool catalog. Current pipeline profile defaults MCP servers пустые; такой инструмент должен иметь узкий scope. |
| Считать Balatro проект достаточным предметом | **Не брать сейчас** | На VPS есть browser clone/solver, JS и ассеты, но не найден оригинальный исполняемый binary. Для текущих задач Ghidra не заменяет анализ Lua/JS и игровую математику. |
| Orchestra MCP support | **Уже есть** | Per-worker `mcp_servers`, project `.mcp.json`, role-scoped user config; новая интеграция в код платформы не требуется, если предмет появится. |
| Ghidra deployment mode | **Уже есть в upstream** | Отдельно GUI plugin и headless Java server. Выбор зависит от будущего workflow; сейчас нет причины устанавливать любой из вариантов. |
| Безопасная конфигурация | **Не брать без ограничения task/user/file/network scope** | Сервер имеет write/debug tools; scripts выключены по умолчанию, path root и auth/bind настройки существуют, но не все являются обязательными в локальном stdio use. Не устанавливал и не тестировал их фактическую защиту. |

### Источники

- Upstream README на зафиксированной ревизии [`162c826`](https://github.com/bethington/ghidra-mcp/blob/162c82643d27f28e68217fa417b30698bc98b9d4/README.md), [commit](https://github.com/bethington/ghidra-mcp/commit/162c82643d27f28e68217fa417b30698bc98b9d4), [LICENSE](https://github.com/bethington/ghidra-mcp/blob/162c82643d27f28e68217fa417b30698bc98b9d4/LICENSE), [SECURITY.md](https://github.com/bethington/ghidra-mcp/blob/162c82643d27f28e68217fa417b30698bc98b9d4/SECURITY.md).
- [v6.0.0 release](https://github.com/bethington/ghidra-mcp/releases/tag/v6.0.0), [Ghidra 12.1.4 official release](https://github.com/NationalSecurityAgency/ghidra/releases/tag/Ghidra_12.1.4_build).
- Наш код: `app/mcp_stdio.py::spawn_worker`, `app/manager.py::_make_mcp_config`, `app/runtime_registry.py::_load_scope_mcp_servers/_load_user_mcp_servers`, `.orchestra/pipelines/default/pipeline.yaml`.
- VPS inventory: `list_orchestrators`; `/opt/cog-second-brain/04-projects/balatro`, `/home/kesha/publish/balatro-solver/README.md`; `.orchestra/tasks/V-639/report.md`; `.orchestra/kb/runtimes.md` (ARTEMIS).

Ничего не устанавливал, не подключал и не менял вне этого отчёта.
