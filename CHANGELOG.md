# Changelog

## v2.26.3 — 2026-07-27 — #95 Grok T4: usage/cost под замком тестов

Кода почти нет — почти всё уже работало с T1. Ценность среза в том, что каждое допущение проверено, а не принято на веру: неверная стоимость не падает, она годами врёт в дашборде.

### Verified (замерами на живом CLI, зафиксировано тестами)
- 📏 **Знаменатель `context_pct` берётся из РАНТАЙМА, а не из нашей константы.** Проверено подменой `GROK_CONTEXT_LIMITS["grok-4.5"]` на заведомо неверные 12 345 → после коннекта окно стало 500 000, `context_pct` считается от него. Совпадение константы и рантайма (оба 500 000) прятало бы поломку механизма — тесты специально разводят эти значения. Это ровно та авария, что была с Opus, когда `CONTEXT_LIMITS` врал знаменателем и агент компактился не вовремя.
- 🧮 **`turn_completed.usage` — ПОХОДОВЫЙ, не кумулятивный.** Ключевое отличие от Codex, где он накоплен за тред и требует вычисления дельты. Замер трёх ходов в одной сессии: `outputTokens` 49 / 22 / 23 (кумулятив дал бы 49 / 71 / 94), вход почти целиком уходит в кэш. Значит payload потребляется как есть, `cost_is_delta=True` корректен, машинерия дельт не нужна. Раньше это было моим НЕПРОВЕРЕННЫМ допущением.
- 🧠 **`reasoningTokens` не биллятся поверх output** — тест сравнивает ход с ними и без них при равном `outputTokens`, стоимость обязана совпасть.
- 💵 **Валюта уже корректна, правок не потребовалось**: `MODEL_COST_CURRENCY = '$'` (`app/static/js/utils.js`) используется для `cost_usd` и прайсинга моделей, `data-currency` (рубли задач и платежей) в этот путь не заходит. Grok идёт тем же маршрутом, что Claude/Codex.

### Known issue
- ⚠️ **Цены Grok намеренно НЕ регистрируются в общем `TOKEN_PRICES`.** `routes/system.py:_cost_cached_for()` пересчитывает историю для любой модели из этого словаря по claude-эвристике кэша (cache_read = 10% от input). У Grok кэш стоит $0.30 против $2.00 input, то есть 15%, — на реальном замеренном ходе эвристика завышает стоимость на **+27.6%**. Пока модель отсутствует в словаре, функция отдаёт сохранённое значение, посчитанное из `costUsdTicks`. Тест это прибивает: попытка «заодно зарегистрировать цены как у Claude» будет поймана.
- Следствие: в выпадашке моделей у Grok не показываются `price_input`/`price_output` — как и у всех Codex-моделей по той же причине. Осознанный компромисс, не дефект.

### Tests
`tests/test_backend_grok.py` (58): окно из рантайма перебивает константу (и из `initialize._meta`, и из `session/new`), чужая модель в списке игнорируется, `context_pct` от рантайм-окна, cached-тир реально дешевле fresh, `cached > input` не даёт отрицательных токенов, неизвестная модель стоит 0 вместо догадки, reasoning не удваивается, usage не накапливается между ходами, Grok отсутствует в `TOKEN_PRICES` с проверкой размера ущерба.

## v2.26.2 — 2026-07-27 — #95 Grok T3: резюм сессии

### Fixed
- 🔥 **Гонка на `config.toml` общего `GROK_HOME` (изоляция MCP могла отключаться сама)** (`app/backend_grok.py`). `ensure_grok_home()` перезаписывал файл на КАЖДОМ коннекте обычным `write_text` — это truncate + write. Воркер, стартующий в этом окне, читал **пустой** конфиг: без `mcps = false` изоляция T2 выключена, чужие MCP-серверы поднимаются со своими секретами.
  - **Замер:** 4 писателя + 4 читателя, 3 секунды → **57.9% чтений видели пустой файл** (17 626 из 30 466). После фикса на том же замере — **0%**.
  - Фикс: запись через уникальный tmp + атомарный `rename`, плюс пропуск записи если содержимое совпадает. Тот же приём, что в `workspace.sync_agents_md`, и по той же причине.
- 🔁 **Протухший `sessionId` больше не блокирует воркера навсегда** (`app/backend_grok.py`). Ключ store — пара `(cwd, sessionId)`, поэтому перенесённый или подчищенный worktree делал `session/load` вечно провальным, а коннект — невозможным. Теперь падение `session/load` → новая сессия + **громкое** предупреждение о том, что история недоступна. Тихо историю не теряем.
- 📁 **Понятная ошибка при исчезнувшем worktree** — раньше был голый `FileNotFoundError` от спавна процесса, который называл путь, но не причину.

### Known tradeoff
Предупреждение о неудачном резюме сначала **не долетало до юзера**: оно несло старый `sessionId`, а `events()` отбрасывает нотификации с чужим id — сообщение о потерянной истории отфильтровывалось само собой. Ключ переименован в `staleSessionId`. Поймано живым тестом, который требовал появления предупреждения, а не только успешного коннекта.

### Reasoning
Замеры на живом CLI (риски, поставленные PM):
- **Общий `GROK_HOME` для всех воркеров безопасен для сессий.** Два воркера, одновременный коннект, разные cwd → разные id, ходы не пересекаются (`ALPHA`/`BETA`). Session store разложен по URL-кодированному cwd, так что пересечений нет by design. Опасность была только в общем `config.toml` — см. выше.
- **Резюм ПЕРЕЖИВАЕТ смену ветки в том же worktree.** `main` → `feature/x`, `session/load` вернул тот же id и вспомнил кодовое слово. Сессия привязана к пути, не к ветке — контракт «переживает рестарт» держится и при переключении ветки после мержа.
- **Чужой cwd** с тем же id → `Path not found` → фолбэк в новую сессию (проверено: id другой, история честно недоступна).

### Tests
`tests/test_backend_grok.py` (48): атомарность записи конфига под конкурентным читателем, перезапись при дрейфе содержимого и отсутствие tmp-мусора, предупреждение о резюме не отфильтровывается маршрутизацией, отказ коннекта при отсутствующем worktree.

## v2.26.1 — 2026-07-27 — #95 Grok T2: изоляция MCP

Закрытие канала утечки, а не гигиена: в артефакте T1 оказался живой ключ стороннего сервиса, потому что Grok сам поднимает чужие MCP-серверы и транслирует их env.

### Fixed
- 🔒 **Грок-воркер поднимается РОВНО с нашим набором MCP-серверов** (`app/backend_grok.py`). Два слоя: Orchestra-владеемый `GROK_HOME` (`data/grok-home`, в `.gitignore`) с `[compat.claude] mcps = false` — и проверка фактического состава на коннекте. Чужой сервер → `GrokMcpIsolationError`, воркер **не стартует** со списком нарушителей в тексте ошибки.
  - `auth.json` — симлинк на пользовательский, чтобы обновление токена не протухало в приватной копии. Каталог стабильный, а не временный: там же лежит session store, от него зависит резюм (T3).
- ⚙️ **`GROK_BIN` из окружения бьёт автопоиск в PATH** (`app/backend_grok.py`). Раньше `shutil.which()` шёл первым, и посторонний `grok` в PATH молча выигрывал у явной настройки.

### Reasoning
Замеры, определившие конструкцию (docs/tasks/95):
- **`session/new.mcpServers` МЕРДЖИТСЯ с обнаруженным, а не замещает его.** Передал только `orchestra` — получил `{orchestra, websearch, mcp-pandoc}`. Передал пустой список — всё равно два чужих сервера.
- **Единственный рабочий тумблер `[compat.claude] mcps = false` читается ТОЛЬКО из user-конфига.** Тот же ключ в проектном `.grok/config.toml` игнорируется (`on (default)` против `OFF (config)`). Правкой `~/.grok/config.toml` чинить нельзя — это личный файл юзера, сломало бы ему интерактивный grok. Отсюда собственный `GROK_HOME`.
- **`GROK_HOME` в плане был отклонён как ломающий авторизацию — замер это опроверг:** песочница с симлинком на `auth.json` логинится штатно (`logged in with grok.com`).
- **Источники discovery (точный список):** `~/.claude.json` (top-level + 47 per-project записей), `.mcp.json` в проекте, `~/.grok/config.toml`, проектные `.grok/config.toml` вверх до корня репо, плагины.
- **`.mcp.json` подавляется не тумблером, а folder-trust:** появление этого файла само снимает доверие с каталога, и в headless сервер не стартует. На это не полагаемся — рантайм-проверка ловит его независимо.

### Known tradeoff
Проверка на коннекте сначала опиралась на `_x.ai/mcp/server_status`, и это давало **ложное «чисто»**: наш `orchestra` рапортует `ready` уже ПОСЛЕ первого хода, а `mcp_initialized` приходит раньше — набор на момент проверки был пуст. Теперь состав берётся из `_x.ai/mcp/servers_updated` (приходит рано и сам является каналом утечки — именно он транслировал ключ), `server_status` остаётся дополнительным сигналом.

### Tests
`tests/test_backend_grok.py` (43): отказ коннекта при чужом сервере, состав только из наших источников, roster из `servers_updated` (регрессия на ложное «чисто»), `GROK_HOME` с отключённым claude-compat и симлинком, fail loud без кредов, инжект `GROK_HOME` поверх унаследованного, приоритет `GROK_BIN`. Живьём: с песочницей утечки нет, при обходе изоляции коннект отклонён.

## v2.26.0 — 2026-07-27 — #95 Grok Build runtime (T1)

Четвёртый рантайм наравне с `claude`/`codex`/`opencode` (`docs/tasks/95/research.md`, `plan.md`). Мотив — отдельный пул квоты SuperGrok: сам этот research не получил cross-review, потому что пул Codex кончился до 2 августа. Пока **registry-only**: рантайм выбирается явно, дефолты `pipeline.yaml` не тронуты.

### Added
- 🤖 **`GrokBackend` — ACP (Agent Client Protocol) поверх `grok agent stdio`** (`app/backend_grok.py`). Долгоживущий процесс + JSON-RPC 2.0 по stdio, аналог `codex app-server`. Резюм сессии через `session/load`, прерывание через `session/cancel` (проверено: срабатывает мгновенно, `stopReason=cancelled`, стрим встаёт). Модель `grok-4.5`, контекст **500 000** (значение рантайма; статьи про «256K» опровергнуты).
- 🧩 **Регистрация рантайма и модели** (`app/runtime_registry.py`, `app/models.py`). `_infer_backend()` отправлял всё, что не `gpt-*`/`claude-*`, в **`opencode`** — незарегистрированный `grok-4.5` молча уехал бы на чужой рантайм. Добавлено правило `grok-*` → `grok` + провайдер `x-ai`; провайдер-квалифицированные id вроде `x-ai/grok-4` намеренно остаются на `opencode`.

### Reasoning
- **Отдельный бэкенд, не общий слой с Codex.** Замер по строкам: из 1105 строк методов `backend_codex.py` лишь **220 (20%)** — общий JSON-RPC транспорт, а **826 (75%)** — собственный словарь событий Codex (`item/started`, `item/completed`, `collabAgentToolCall`), которого у Grok нет вовсе. Расхождение ~80% при пороге 30%. Прецедент: `backend_opencode.py` тоже не импортирует из `backend_codex.py` ничего — общий слой один, 16-строчный `BackendLike`.
- **Системный промпт идёт ТОЛЬКО через `--agent-profile`** (временный `.md` с YAML-frontmatter, удаляется на `disconnect`). ACP-поля `systemPrompt`/`_meta.systemPrompt`/`instructions` принимаются и **молча игнорируются** — воркер работал бы вообще без промпта. Проверено канарейкой до написания кода.
- **`mid_turn_inject=False`.** Prompt, посланный во время хода, не рулит им, а попадает в нативную очередь и исполняется ОТДЕЛЬНЫМ ходом → N посылок = N `turn_end`. Цикл событий завершается по опустевшей очереди, а не по первому `prompt_complete`, иначе ход из очереди стримится в никуда.
- **Стоимость берётся из рантайма.** `costUsdTicks` = **1e-10 USD** (не 1e-9 — первая версия research ошиблась в единицах и была ретрактирована). Сходится в ноль на 4 замеренных ходах с формулой `((in−cached)·$2 + cached·$0.30 + out·$6)/1e6`. Реальная ставка кэша **$0.30/M**, а не $0.50 из всех статей. Цены живут в `backend_grok.py`, а не в `TOKEN_PRICES` — там нет тира `cached`.

### Known issue
- **Форма терминального исчерпания квоты неизвестна** — исчерпать SuperGrok не удалось. `_classify_error` не угадывает паттерн: неопознанная ошибка остаётся `error` и падает громко (`report_bug`, без тихого ретрая). Классификация появится после первого реального упора в лимит.
- **Чужие MCP-серверы пока не подавлены** (T2). Grok сам подхватывает серверы из `~/.claude.json`/`.mcp.json` и транслирует их env — во время research так утёк живой `OPENROUTER_API_KEY`. Фабрика уже собирает набор явно из наших источников, но подавление неявного discovery — отдельный тикет.

### Tests
`tests/test_backend_grok.py` (33): маппинг событий на реальном дампе, идемпотентность `turn_end` при двух сигналах завершения, `x-ai/grok-4` не перехватывается, трансляция MCP в ACP-форму (env — список пар, не словарь), три замеренных хода как фикстуры стоимости. Плюс `grok` добавлен в контрактный `test_backend_classes_satisfy_structural_contract`.

## v2.25.1 — 2026-07-27

### Removed
- 🗑 **Opus 4.6 и 4.8 выпилены из реестра моделей** (`app/models.py`, `app/tg_bridge.py`, `app/static/js/app.js`). Убраны из `MODELS`, `CONTEXT_LIMITS`, `BACKENDS`, `TOKEN_PRICES`, семантических алиасов, короткиx имён TG и палитры дашборда — в выпадашке остаются только актуальные модели.
  - Старые id (`claude-opus-4-8[1m]`, `claude-opus-4-6`, с суффиксом и без) **ремапятся на `claude-opus-5[1m]`** — тем же приёмом, что `claude-sonnet-4-6` → Sonnet 5. Сессия со старой моделью в БД поднимется на Opus 5, а не упадёт.
  - Заодно удалён мёртвый auto-bump `effort low/medium → high` для 4.8 в `backend_claude.py` (auto-downgrade `xhigh → high` для Claude остаётся — он про API-ограничение, не про модель).
  - Живых сессий на 4.6/4.8 в БД не было ни одной (замер по `sessions.model`); единственный воркер на 4.8 переведён на Opus 5 до правки.

## v2.25.0 — 2026-07-27 — #90 lifecycle T1–T3

Аудит жизненного цикла worktree/merge (`docs/tasks/90/audit.md`, 12 подтверждённых дефектов, 19 экспериментов). Реализация идёт вертикальными срезами T1→T7; T4–T7 заморожены до сброса недельной квоты Codex (2 августа).

### Added
- 🌿 **Persisted base-branch contract** (T1; `app/db.py`, `app/session.py`, `app/workspace.py`, `app/routes/sessions.py`, `app/mcp_stdio.py`). Колонки `base_branch TEXT DEFAULT ''` и `needs_switch INTEGER DEFAULT 0`; база спавна резолвится ОДИН раз (explicit → symbolic remote HEAD → единственная local `main`/`master`) и хранится в сессии. `merge`/`switch`/`wip`/`kill` читают её вместо литерала `main`.
  - **Почему не «угадать по HEAD»**: после `checkout feature/x` symbolic HEAD равен feature-ветке — mainline задним числом не восстановить. Неоднозначная legacy-строка теперь fails loud до любой Git-операции, а не мержит в случайную ветку.
  - **Triggered case**: главная ветка ≠ `main` — Aperant живёт на `develop`, VPN-Service держит и `main`, и `master`.

### Changed
- 🔒 **Merge идёт в checkout-владельца target и отклоняет грязный target** (T2; `app/workspace.py`). Слияние в ветку, вычекаченную в родительском worktree, выполняется там же; auto-stash из merge-пути удалён — незакоммиченные правки возвращаются юзеру списком путей, ни target, ни ветка воркера не трогаются. Prunable worktree metadata больше не даёт 500 (найдено Codex-ревью).

### Fixed
- ♻️ **Squash-коммит атомарен: отказ хука откатывает target** (T3; `app/workspace.py`). Провал `git commit` (pre-commit hook, related и unrelated пути) теперь возвращает HEAD/index/worktree на исходный `old_head` и верифицирует откат; ветка воркера не меняется. Раньше падение оставляло cherry-pick'нутые коммиты в target и рапортовало ошибку — состояние «наполовину смержено».
- 🔗 **`merge_worker` больше не печатает `FAILED — unknown` при успешной линковке** (T3; `app/tm.py`, `app/routes/sessions.py`, `app/mcp_stdio.py`). `link_commits_to_task()` возвращал task-row или `None`, а MCP читал тот же объект как `{ok, added, error}` — успех без ключа `ok` рисовался безымянной ошибкой. Теперь функция отдаёт стабильный DTO `{ok, added, task_id | error}`, неизвестная задача даёт явный текст.
  - **Triggered case**: два мержа подряд отрапортовали провал при реально успешном слиянии; статус задачи ставился руками.
  - **Tests**: `test_related_commit_failure_rolls_back_target_and_preserves_worker`, `test_unrelated_commit_failure_rolls_back_target_and_preserves_worker`, `test_merge_links_commits_with_normalized_sqlite_results`, `test_merge_worker_formats_normalized_and_legacy_link_results`.

### Known tradeoff
- До рестарта Orchestra живой FastAPI держит старый код `app/routes/`, а MCP-процессы стартуют заново и берут свежий → `FAILED — unknown` и `target branch '' does not exist` ещё воспроизводятся. Обход: `merge_worker(name, target="main")` явно.

## v2.24.3 — 2026-07-27

### Changed
- 🔇 **Compact summary больше не улетает в TG** (`app/session.py:1201`). Полный текст саммари логировался типом `text`, а `text` в мосте = речь агента → мгновенный форвард в топик простынёй на несколько килобайт с @mention юзера.
  - Вернуть старое поведение: `LOG_COMPACT_SUMMARY=1` в `.env` (по умолчанию `0`, задокументировано в `.env.example`).
  - Саммари не теряется: живёт в `session.last_summary`, в preamble нового контекста (лог `user_message`) и в ответе `compact_worker`. В чат теперь идёт одна строка `compact done: X% → Y% (summary N chars)`.
  - **Triggered case**: юзер получил в TG стену текста после компактификации оркестратора и попросил флаг, а не правку поведения намертво.

## v2.24.2 — 2026-07-26

### Removed
- 🗑 **`_auto_commit_if_dirty` — спавн больше не коммитит незакоммиченную работу юзера** (`app/manager.py`). Функция делала `git add -A` + `git commit` в рабочем чекауте перед созданием worktree, обосновывая это тем, что «worktree наследует unstaged junk».
  - **Обоснование было ложным** — проверено экспериментом на чистом репо: `git worktree add <path> HEAD` строит дерево из коммита, unstaged-правки и untracked-файлы источника в него не попадают вообще. Вызывалась функция только при `use_worktree and repo_path`, то есть ровно в единственном случае, где не нужна.
  - **Triggered case**: оркестратор inscryption-ai обнаружил, что Orchestra закоммитила в `main` чужую папку `.serena/` перед спавном воркера. Это происходило при каждом спавне с dirty-репо, начиная с `1e39c47`.
  - Убраны 2 мока в `tests/test_manager.py` (функцию саму никто не тестировал).

### Fixed
- 📁 **Директория и ветка worktree именуются по repo root, а не по `scope` сессии** (`app/workspace.py:285-294`). Было: `wt_dir = WORKTREE_ROOT / _slugify(scope)`, репозиторий при этом брался из `repo_path` — два независимых источника, никем не сверяемых.
  - **Симптом**: воркеры `impl-deck-search`, `impl-inscryption`, `feat-inscryption-ai` лежали в `worktrees/home-maxim-cursor-cog-second-brain/`, хотя `git-common-dir` = `/mnt/data/Projects/Python/inscryption-ai/.git`. Проявляется, когда родитель живёт в одном проекте, а спавнит воркера в другой. Ветки при этом получали имена вида `feat/home-maxim-cursor-cog-second-brain/<name>` в чужом репо.
  - **Почему важно**: это источник серии ложных баг-репортов «`repo_path` игнорируется» — оркестраторы читали путь вместо `git-common-dir` и делали вывод о промахе. Расследование `fix-repo-path` тогда сняло обвинение с `repo_path`, но настоящую причину не нашло.
  - Параметр `scope` удалён из `create_worktree` — после фикса он не использовался. Существующие worktree не затронуты (их пути записаны в БД).
  - **Tests**: `test_repo_namespaced_path`, `test_branch_namespaced_by_repo`, `test_worktree_belongs_to_requested_repo`, `test_different_repos_no_collision` (заменил `test_different_scopes_no_collision` — свойство «разные scope → разные пути» перестало существовать). 152 зелёных.

## v2.24.1 — 2026-07-01

### Added
- 🔀 **`POST /api/proxy/set-env` — сменить прокси кнопкой без ручной правки .env** — фронт шлёт `{"id": "contabo-de"}`, endpoint находит прокси в `PROXY_LIST` и переписывает ТОЛЬКО строки `HTTPS_PROXY`/`HTTP_PROXY` в `.env` (line-surgery через `(?m)^KEY=.*$`, токены TG/YouGile нетронуты). `url=="direct"` → пустое значение (прямой выход). Ответ `{"ok": true, "wrote": <url>, "need_restart": true}`.
  - **НЕ hot-switch**: `os.environ` НЕ трогается, DB НЕ трогается. `.env` остаётся источником истины, применяется юзером через рестарт. Возврат старого `select_proxy` (мутировал env на лету → рассинхрон) исключён by design.
  - **Реализация** (`app/routes/proxy.py`): `_set_env_proxy(url)` — atomic write (temp + `os.replace`, .env с токенами не должен побиться при crash). `ENV_FILE = Path(__file__).parent.parent.parent/.env` (= systemd `EnvironmentFile`/`WorkingDirectory`). `re.sub` с lambda-replacement (URL/пароль пишутся буквально, без `\`-escape).
  - **Codex review**: 0 багов (проверены regex-anchor vs PROXY_LIST, case-sensitivity vs `https_proxy`, path traversal через `body.id`, direct→empty). Atomic write добавлен по остаточному замечанию.
  - **Tests**: `tests/test_proxy.py` — token preservation, direct→empty, append-when-missing (9 pass).
  - **Frontend**: кнопка выбора прокси под этот контракт — за frontend-opus.

## v2.24.0 — 2026-07-01

### Changed
- 🔌 **Прокси: `.env` HTTPS_PROXY = единственный источник истины (вырезан DB/hot-switch)** — юзер: «всё лишнее вырежем». Управление прокси только через `.env` + `sudo systemctl restart orchestra`. Вся runtime-мутация env удалена → рассинхрон (`.env` показывал 12343, а CLI-агенты держали 12342 из DB) стал невозможен by design.
  - **Root cause рассинхрона**: `kv.active_proxy` в DB **побеждал** `.env` — `load_saved_proxy()` при старте перезаписывал `os.environ` из DB. А живые CLI-агенты держали РАЗНЫЙ прокси, т.к. `backend_claude._make_client()` снимает `os.environ["HTTPS_PROXY"]` в момент `connect()` и запаивает в персистентный SDK-клиент (проверено: pid A→12334, pid B→12342).
  - **Вырезано из `proxy_manager.py`** (−107 строк net): `load_saved_proxy` (читала DB kv), `select_proxy` (мутировала `os.environ`+`MCP_BASE_ENV`, писала kv), `refresh_loop`, `_cache`/`CACHE_TTL`/`_ts`-штампы, `_active_id` state. Стало read-only: `list_proxies()` (`active` вычисляется из `os.environ` через `_active_id()`, read-only) + `check_all()`/`check_proxy()` (on-demand живость, без кеша).
  - **`routes/proxy.py`**: удалён `POST /api/proxy/select/{proxy_id}` (+ interrupt-логика живых агентов). Осталось `list` + `check` + `tunnel/status`. `route_surface_snapshot.json` обновлён.
  - **`main.py`**: убраны `proxy_manager.load_saved_proxy()` + `refresh_loop` task.
  - **Frontend** (`app.js`): убрана кнопка «выбрать прокси» (`.proxy-select-btn`) + handler. Осталась Check (проверить живость) + индикатор активного.
  - **DB**: `DELETE FROM kv WHERE key='active_proxy'`. Миграция/колонка не тронуты (мёртвые, код не читает).
  - **#3 Direct id fix**: `id="direct"` форсится когда `url=="direct"` — раньше генерился из имени → `direct-(vpn/соту)` (кириллица+скобки) → `select/direct` 404'ил. Имя в `.env` упрощено до `Direct`.
  - **#4 zombie backoff+health-gate** (`ssh_tunnel.py`): мёртвый VPS (timeweb/ezhik) реконнектил ssh каждые 5с вечно (`kex_exchange_identification: Connection reset` в логах) → зомби. Теперь TCP health-gate на `:22` (2с) перед спавном + exponential backoff 5→300с + reset при uptime >60с.
  - **CLAUDE.md**: секция «🔌 ПРОКСИ» — источник истины, как сменить, дашборд read-only.
  - **Codex-враппер** (`~/.local/bin/codex`): добавлен `HTTP_PROXY` (был только HTTPS) — websocket Codex падал без него.
  - **Tests**: `tests/test_proxy.py` (6 — direct id, active-from-env, no-mutation-methods, port probe, health-gate). 48 зелёных.
  - **Reverted из v2.23.0**: `CACHE_TTL`/`refresh_loop`/`_cache` (были добавлены в прошлой итерации, теперь не нужны — дашборд on-demand).
  - **Docs**: `docs/tasks/proxy-fix/{best-practices,plan-simplify}.md`.

## v2.23.0 — 2026-07-01

### Fixed
- 🔌 **SSH-туннели к прокси зависели от VPN + zombie-процессы (proxy-fix)** — все прокси Orchestra = `ssh -L` туннели к VPS. При смене сети / выключении Reality VPN старые ssh-процессы висли в полумёртвом состоянии, держали local-порт → новый туннель не мог забиндить → прокси молча возвращал HTTP 000. Плюс дубли копились (9 ssh на 4 туннеля).
  - **Root cause**: НЕ блокировка РКН. Contabo (158.220.127.161) и Fornex (89.127.206.225) достижимы напрямую с РФ-WiFi без VPN (проверено: SSH-баннер + `curl -x :12343 https://api.anthropic.com/v1/messages` → HTTP 405). Проблема — (1) при VPN ON xray TUN-режим (`ip rule 9001 lookup 2022`) заворачивал VPS-трафик в tun0, (2) stale ssh не убивались.
  - **`_kill_stale(t)`** (`app/ssh_tunnel.py:37`) — `pkill -f "ssh -N -L {local}:127.0.0.1:{remote} .*root@{host}"` перед стартом каждого туннеля (once в `start_tunnel`, НЕ в reconnect-loop). Паттерн пинит local+remote порт **и** host → убивает только СВОЙ tunnel-def, не чужой same-port форвард. Протестировано на реальных ssh-процессах (kill свой / оставить чужой).
  - **Hard-kill**: `stop_tunnel` + CancelledError-handler теперь `terminate()` → `wait_for(KILL_GRACE=3s)` → `kill()` (SIGKILL) если ssh завис на мёртвом маршруте. `KILL_GRACE=3` (`ssh_tunnel.py:18`).
  - **Дашборд TTL** (`app/proxy_manager.py`) — `_cache` без TTL показывал мёртвый прокси 🟢 навсегда. Теперь `CACHE_TTL=60s`, результаты штампуются `_ts` (monotonic), `list_proxies` дропает stale → фронт рисует ⚪ (unknown, уже поддержано `app.js:4879`). `refresh_loop()` (bg task в `main.py:56`) перепроверяет каждые 60с → самозаживает.
  - **.env**: `SSH_TUNNELS` переупорядочен — живые (contabo, fornex) первыми, мёртвые (ezhik, timeweb) последними. `check-proxies.sh` кандидаты аналогично.
  - **NM hook**: `scripts/99-orchestra-proxy` — dispatcher-скрипт (up/down/vpn-*/connectivity-change → `check-proxies.sh`). Ставит юзер вручную (root, инструкция в шапке файла).
  - **Triggered case**: юзер выключил Reality VPN на домашнем WiFi → Orchestra упала, т.к. туннели дохли. Цель: прокси как ЗАМЕНА VPN, а не зависимость от него.
  - **Skipped**: `ip rule` split-tunnel (#5) — юзер использует VPN **или** прокси, не одновременно → перехватывать нечего при VPN off.
  - **Codex review**: подтвердил safe (12340≠123400), правильное размещение `_kill_stale` в start_tunnel; принята суггестия сузить pkill-match до host+remote (сделано).
  - **Research**: `docs/tasks/proxy-fix/research.md`.

## v2.22.0 — 2026-06-21

### Added
- 📡 **Real-time token streaming in dashboard (task #83)** — agent text now types out live in the chat bubble as the model generates it, instead of appearing all at once when the turn's text block completes. Latency drops from "whole block after completion" to ~5 chunks/sec (~80-100 chars/chunk — the Claude CLI batches deltas; not per-token).
  - **Backend**: `include_partial_messages=True` in `ClaudeAgentOptions` (`app/backend_claude.py:138`). `_convert` gained a `StreamEvent` branch (`backend_claude.py:242`) that emits `AgentEvent("stream", text)` — STRICTLY scoped to main-agent `text_delta`: `parent_tool_use_id is not None` (subagents), non-`content_block_delta` events, and `thinking_delta`/`input_json_delta`/`signature_delta` are all filtered out. The final `AssistantMessage` still emits `text`/`thinking`/`tool_use` and is persisted exactly as before.
  - **Pub/sub**: new `app/live_broker.py` — in-memory per-session broker (`broker.subscribe/publish/unsubscribe`). Bounded `asyncio.Queue(maxsize=256)` per viewer, drop-oldest on overflow (partials are ephemeral, never block the agent loop). Single-process/single-loop only (like the session manager). Sync `publish` — never awaits.
  - **Routing**: `session._handle_event` (`session.py:519`) routes `stream` events to `broker.publish(self.id, ...)` — NO DB write. Key is `self.id` (== `manager.get_session_id` == `logs.session_id`), NOT the Claude `session_id` (often `None` on first turn).
  - **SSE**: `stream_session_logs` generator (`app/routes/sessions.py:279`) now subscribes to the broker, drains live partials BEFORE polling the DB each tick (ordering: partials always precede their final `text` row → no orphan bubble), 0.1s poll while active / 0.5s idle, `unsubscribe` in `finally`.
  - **Frontend**: the `type:"stream"` bubble renderer existed since 2026-05-01 (`c82e725`) but was DEAD CODE — no backend ever emitted it. Now wired up. Fixes: final `text` replaces the bubble body with the DB-authoritative content (`app.js:2155`, handles dropped/truncated partials); `firstId`/`lastId` bookkeeping guarded with `Number.isFinite(l.id)` (`app.js:189` — partials carry no id).
  - **NOT touched**: DB schema, cost/usage accounting, TG bridge (stays final-only — partial spam would be insane), codex/opencode backends (emit no `StreamEvent`).
  - **Tests**: `tests/test_live_broker.py` (7 — fan-out, drop-oldest, unsubscribe cleanup, session isolation), `tests/test_backend_stream.py` (7 — scope filter: text_delta passes; thinking/input_json/signature/subagent/non-delta dropped). All 14 green.
  - **Codex review**: APPROVED, 0 blocking — verified no subscription leak, no broker race, no orphan bubble, correct scope filter.
  - **Research artifacts**: `docs/tasks/83/` (research.md, plan.md, capture_partial.py, partial_dump.jsonl).

## v2.21.1 — 2026-06-15

### Fixed
- 🐛 **OpenCode turn never ends → orchestrator stuck `running` (task #97, 11h in prod)** — the turn boundary relied on the fire-once SSE `session.idle` event (global bus, 30s heartbeats, frequently MISSED) plus a chat `POST /message` that could hang forever. When both failed, `events()` never yielded `turn_end`, the listen task never exited, status stayed `RUNNING` indefinitely.
  - **Technical core**: rewrote `OpenCodeBackend.events()` (`app/backend_opencode.py`) to detect completion by POLLING `GET /session/status` every `STATUS_POLL_INTERVAL=3s` — an authoritative daemon query that cannot be "missed" like an event. Idle ⟺ session absent from the status dict OR `type=="idle"`; `busy`/`retry` ⟶ keep waiting. SSE is kept ONLY for live streaming of `text`/`thinking`/`tool` parts (`_handle_sse` helper + `_SESSION_IDLE`/`_SESSION_ERR` sentinels — SSE idle just triggers an immediate status poll, never ends the turn on its own).
  - **Send path**: `send()` now submits via `POST /session/{id}/prompt_async` (returns `204` immediately) instead of a chat-POST task that could hang. Dropped `_chat_task`/`_post_chat`; per-turn state is a single `_turn_active` flag. Body uses NESTED `model:{providerID,modelID}` (the `prompt_async` schema differs from the old `/message`).
  - **turn_end** built from `GET /session/{id}/message` (last assistant message) via new `_fetch_last_message()` — cost/tokens independent of the submit. `_turn_end` normalizes both `{info,...}` and flat-`AssistantMessage` shapes (`info = msg.get("info") or msg`).
  - **No-stuck guarantees (all Codex-flagged)**: HARD deadline enforced INSIDE `events()` (`TURN_TIMEOUT`) — the `session.py` timeout only runs when `events()` yields, so a perma-`busy` daemon would've still hung; `_turn_active`/`_sse_response` reset in the `finally` (cancel-safe); status-poll tolerates transient failures (`STATUS_FAIL_THRESHOLD=3` consecutive OR `_proc_dead()` before declaring dead); message-fetch is total → exactly one `turn_end` on every exit path.
  - **`app/session.py:365`** — wrapped `await backend.send(message)` in try/except: a `send()` failure after `status=RUNNING` and before the listen task is created was a SECOND stuck-running path (any backend). Now resets to `IDLE` on failure.
  - **Removed**: all the prior debug-patch cruft — `INACTIVITY_TIMEOUT`, `wait_timeout`, the SSE-drain loop, the useless heartbeat daemon-poll.
  - **Tests**: `tests/test_backend_opencode.py` event-loop suite rewritten for the poll model (fake SSE + scripted `/session/status`). New cases: SSE-never-sends-idle (THE bug), perma-busy hits hard deadline, single vs repeated status failures, retry-not-premature, message-fetch empty/raises, flat-message shape, cancel resets `_turn_active`, submit-grace. 44 tests green.
  - **Triggered case**: orchestrator on opencode backend sat at `running` for 11h after a turn the daemon had actually finished — the `session.idle` SSE event was dropped and the chat POST response was lost.

## v2.21.0 — 2026-06-14

### Added
- 🔌 **OpenCodeBackend (`app/backend_opencode.py`)** — third `BackendLike` backend wrapping the `opencode serve` daemon (HTTP + global SSE bus), alongside Claude/Codex. Wired into `session.py:_make_backend` (`backend_type == "opencode"`) + `events.py` type-comment. Task #96, Codex-reviewed plan + impl (4 rounds → APPROVED). 39 unit tests, all green.
- 🧭 **Backend routing → opencode (`app/models.py`, Phase 2)** — `_infer_backend()` now: `gpt-*`→codex, `claude-*`→claude, **everything else** (deepseek, gemini, llama, mistral, …) → `opencode`. `backend_for_model()` infers from the ID prefix for UNregistered models instead of defaulting to claude — a never-seen `deepseek/deepseek-v4-flash` from the proxy routes correctly. No model IDs hardcoded; dynamic `fetch_models_from_proxy` populates `BACKENDS` via `_infer_backend`. Provider/model split (`OpenCodeBackend.__init__`) parses proxy `provider/model` IDs (`deepseek/deepseek-v4-flash` → provider `deepseek`, model `deepseek-v4-flash`; first slash only). `tests/test_backend_routing.py` (9 tests).
  - **Shape**: Codex-like managed subprocess (one turn per `send`, native `cost` from the chat response — NO `TOKEN_PRICES` table needed) but with Claude-like streaming richness (`text`/`thinking`/`tool_use`/`tool_result`) delivered over a SEPARATE global SSE stream (`GET /event`), not inline.
  - **Dual-source turn coordination**: `events()` does `asyncio.wait({next_sse_line, chat_task}, FIRST_COMPLETED, timeout=TURN_TIMEOUT)`. `session.idle` = turn boundary; the awaited chat POST (`{info:{cost,tokens}}`) supplies authoritative `turn_end` metadata. Exactly ONE `turn_end` on every exit path (idle / sse_failed / timeout / chat_failed / chat_cancelled / early-close).
  - **Transport**: plain `httpx` (not the `opencode-ai` SDK) — the SDK's pydantic event types silently drop `reasoning`/`message.part.delta`/unknown events; raw-dict parsing keeps full fidelity. No new dependency (httpx already present).
  - **MCP**: Orchestra stdio `{command,args,env}` → OpenCode `McpLocalConfig {type:"local",command:[...],environment,enabled}`, written into a per-worker `opencode.json` in the worktree (merged if one exists). `permission: {edit,bash,webfetch:"allow"}`.
  - **Daemon lifecycle**: one daemon per backend instance, free-port alloc with 3× retry, readiness via `GET /app` 200 poll, stdio → DEVNULL (no pipe back-pressure), teardown = abort → terminate → wait → kill → **reap** (verified: no zombies).
- **Reasoning**: re-derived the whole seam from a LIVE probe (opencode v1.17.6 + SDK 0.1.0a36) because the referenced `docs/research/RESEARCH-OPENCODE.md` never existed in the worktree. Captured real event shapes from a daemon turn — that's how the `reasoning` part (→ `thinking`) and cumulative-text streaming (suffix-only emit) were found.

### Fixed (caught during Codex review, in the new backend)
- 🐛 **SSE `aclose()` on a running generator** — `next_line.cancel()` must be `await`ed BEFORE `sse.aclose()`, else `RuntimeError: asynchronous generator is already running` silently swallows the close → HTTP-stream leak. Now: cancel → await → aclose.
- 🐛 **`CancelledError` leak on normal-end await** — `await wait_for(chat_task)` caught only `Exception`; an externally-cancelled task raises `CancelledError` (BaseException). Now a `chat_task.cancelled()` pre-check + explicit `except asyncio.CancelledError` → `turn_end(chat_cancelled)`.
- 🐛 **Concurrent `disconnect()` race** — snapshot `chat_task = self._chat_task` at the top of `events()`; a parallel `disconnect()` nulling the field no longer causes `AttributeError` mid-iteration.

## v2.20.0 — 2026-06-11

### Changed
- 🏗️ **Full architecture refactor P0–P4** (per `docs/reviews/arch-audit.md`, Codex-reviewed plan + impl, 5 commits `3a7b76a..57949c5`). Public API (HTTP/MCP/DB) byte-identical — guarded by `tests/test_routes_surface.py` snapshot (77 routes). 487 tests green.
  - **P0 fail-loud + async**: 24 silent `except: pass` → `logger.warning` with context; `tm_yougile.py`/`routes/tm.py` sync SQLite wrapped in `asyncio.to_thread` (connection-per-helper, transaction never crosses await); `tm.set_main_loop()` + `run_coroutine_threadsafe` fallback — YouGile sync fired from worker threads no longer silently no-ops; codex turn loop got `_on_task_done` callback; `_auto_continue` capped at 5 consecutive max_turns
  - **P1 union-type fix**: `manager.get_by_name()` always returns `AgentSession | None` — detached DB-hydrate via `_hydrate_row()` with `loaded=False` discriminator + `db_row` for legacy response shape; 34 `isinstance(found, dict)` sites killed; `manager.update_session_fields()` replaces handler-level `_persist()` triplets
  - **P2 main.py drain**: 1574 → 91 lines; 56 handlers → `routes/{sessions,system,tg}.py`; `templates` → `deps.py`; `/api/open-file` now passes `_is_safe_path` (was the one unguarded sibling)
  - **P3 cycles → wired callbacks**: session→tg_bridge via module hooks `on_scope_idle`/`on_scope_running`; manager→tg_bridge via `tg_topics_remover` slot; tm→tm_yougile via `on_task_synced`/`on_payment_changed` registered at import; `MCP_BASE_ENV` → `runtime_env.py` leaf; `_fire_sync`/`_fire_journal_sync` deduped
  - **P4 session split**: `session_cost.py` (CostTracker), `session_turns.py` (TurnManager), `session_hibernate.py` (HibernateManager), `session_state.py` (AgentStatus leaf). Systems-over-state: ALL fields stay on `AgentSession` dataclass, systems hold methods. Cost math delta-based AS-IS, locked by `tests/test_p4_cost.py` contract
- **Reasoning**: audit found 43% of codebase (4 files) carrying all architectural debt; import graph was a DAG only via ~75 lazy imports. Now: downward-only edges, one lookup type, thin transport layer.

### Fixed
- 🐛 **Test hot-loop starvation** — `_MockBackend.events()` re-yielded `turn_end` infinitely with zero suspension points after `finish()`; tests hung when default DB had `bg_jobs` table. Fix: re-arm `_finish_event` after yield. Triggered case: full-suite run started hanging mid-`test_session.py` after stale WAL cleanup
- 🐛 **stop_bridge stale globals** (Codex impl review) — `bot`/`_manager` now cleared on stop; a handler racing past the unhook sees inactive state

### Known tradeoff
- Pending `tm_sync_log` row dangles if sync fired in a CLI context with no event loop — byte-identical legacy behavior, kept for behavior-preservation (in TODO)


## v2.19.0 — 2026-06-04

### Added
- 🔧 **Pipeline-as-config (PR #2)** — opt-in YAML manifests for roles/pipelines. Each client gets isolated `pipelines/<name>/` with custom roles, prompts, workflow. Rebased from v2.16.0 onto v2.18+, all conflicts resolved. `app/pipeline.py`, `pipelines/`

### Fixed
- 🐛 **TG topic icons for sub-orchestrator workers** — running status wasn't propagated to sub-orchestrator's TG topic. Added `notify_scope_running()` + `_find_scope_orch_name()` dedup. `session.py`, `tg_bridge.py`
- 🐛 **Single tilde rendered as strikethrough** — agents writing `~5 min` got false strikethrough between two tildes. Fix: escape single `~` before marked.parse. `app.js`

## v2.18.0 — 2026-06-03

### Added
- 🔧 **`needs_switch` guard** — after `merge_worker`, session is flagged `needs_switch=True`. Sending tasks to a merged worker returns 400 error until `switch_worker_branch` is called. Eliminates LLM-dependent "remember to switch" failure mode. `session.py`, `main.py`
- 🔧 **`merge_worker(next_task_id=)` atomic merge+switch** — optional parameter auto-switches to new branch after merge. One tool call instead of two. `mcp_stdio.py`, `main.py`
- 🔧 **Auto-cleanup stale worktrees** — on startup + every 24h, scans `worktrees/` and removes directories without active DB sessions. Checks dirty tree before removal. `workspace.py`, `manager.py`
- 🔧 **Cross-project `send_message`** — fallback to `ensure_loaded_any(name)` when same-scope lookup fails. Orchestrators can now message agents in other projects. `main.py`

### Fixed
- 🐛 **System prompt lost on compact/resume** — `backend_claude.py` had mutually exclusive `if resume_id` / `else` branches: resuming a session skipped `system_prompt` entirely. Fix: always set `system_prompt`, then optionally set `resume`
- 🐛 **Compact summary invisible in dashboard** — `session.py` sent compact preamble via `backend.send()` without `_log()`. Fix: added `_log("user_message", ...)`
- 🐛 **`switch_worker_branch` blocked after squash merge** — overly strict `merge-base --is-ancestor` check rejected worktrees diverged by squash merge. Fix: `git reset --hard from_ref` before branch switch. `workspace.py`
- 🐛 **Send errors hidden in dashboard** — `mcp__orchestra__send_message` renderer returned `null` on failure, silently hiding errors. Fix: show red `❌` with error text. `app.js`
- 🐛 **Spawn bubble text wrapping** — `task.slice(0, 200)` cut markdown mid-line, breaking bullet lists. Fix: cut at newline boundary. `app.js`
- 🐛 **Merge didn't update session** — `merge_session` reset worktree files but left `session.branch` and `session.task_id` stale. Dashboard showed outdated branch info. Fix: update session fields after merge. `main.py`

## v2.17.0 — 2026-06-01

### Changed
- **Merged `codex-review` module into `codex-debate` skill** — one skill, two modes: **Quick Review** (one-shot `codex exec review`/`codex exec` for pipeline Phase 2/3, no session) and **Debate** (multi-round persistent sessions, existing). All Bash rules preserved: `timeout: 300000` on the Bash tool, `timeout 300` wrapper, `EXIT:$?` check, `HTTPS_PROXY= HTTP_PROXY=`, anti-hallucination, MCP `codex_review()` as legacy fallback. `app/prompts/skills/codex-debate.md`

### Removed
- **`app/prompts/modules/codex-review.md`** — folded into the codex-debate skill. Removed `codex-review` from `modules:` in full-cycle, worker, reviewer; full-cycle body refs now point to the codex-debate skill (Quick Review)

### Added
- **`codex-debate` skill on orchestrator** — `skills: [html-artifacts, vps-deploy, codex-debate]` so the orchestrator can invoke Codex review directly when needed

### Reasoning
Two overlapping Codex prompts (review module + debate skill, both added via separate tasks #43/#46) caused divergence and double maintenance. Consolidated: review is just debate's one-shot mode. Skill > module here because Codex review is invoked on demand (lazy-loaded native skill), not needed in every turn's system prompt.

## v2.16.0 — 2026-06-01

### Fixed
- 🐛 **Zombie workers after restart** — `auto_resume_all` flipped ALL non-idle rows to idle, including archived. Killed workers resurrected every restart. Fix: only flip `running`/`waiting` → `idle`, leave `archived` alone
- 🐛 **Deepgram SSL BAD_RECORD_MAC** — aiohttp 3.13+ defaults trust_env=True → picks up VLESS proxy → TLS record corruption. Fix: explicit trust_env=False + ssl=certifi
- 🐛 **Codex through proxy → Reconnecting 5/5** — Codex CLI inherited HTTPS_PROXY (VPS tunnel) → OpenAI API unreachable. Fix: strip proxy env from codex commands
- 🐛 **User message duplication** — pending bubble not cleaned after SSE delivers real message. Fix: track finalized bubble ref
- 🐛 **send_file silent false-positive** — returned "File sent to TG" on non-JSON TG response. Fix: validate response, explicit error on failure
- 🐛 **Tinyproxy MaxClients exhaustion** — old VPS Tunnel (12338) connections filled Tinyproxy pool. Fix: MaxClients 50→200, Timeout 600→120

### Added
- 🔧 **SSH tunnels in lifespan** — 3 SSH tunnel proxies (Ёжик/Timeweb/Fornex) start/auto-restart from Orchestra lifespan via SSH_TUNNELS env. No separate systemd services needed
- 📋 **Prompt best practices** — Codex bash-primary (not MCP), orchestrator merge/kill safety (worker_wip before kill, cherry-pick on conflict), codex-review module rewritten
- 🔧 **Modular prompts** — `_load_modules()` in manager.py, `modules:` frontmatter key in roles → git-workflow, codex-review, report-format auto-injected
- 📊 **Proxy dashboard** — 4 proxies (Hiddify, Ёжик, Timeweb NL, Fornex NL) configured and benchmarked
- 🔒 **Security** — passwords removed from git history (BFG), .gitignore for sensitive docs + artifacts

### Fixed (11 P2 bugs from review #35 — task #42)
- Reconnect backoff cap (5 failures → give up)
- Hibernate pending messages guard
- GC task protection (`_spawn_bg` for all create_task calls)
- Log retention + WAL checkpoint
- rawMaxTokens from SDK instead of CONTEXT_LIMITS
- ~95 lines dead code removed (backend.py, 3 DB funcs, _react_processing, aliases)

## v2.15.0 — 2026-06-01

### Fixed (13 P1 bugs from review #35 — task #40)
- 🐛 **SDK errors silent (worst bug)** — `_convert` hardcoded `"ok": True`; `ResultMessage.is_error`/`errors`/`permission_denials` and `AssistantMessage.error` never read → auth/billing/rate-limit failures ended the turn as a normal idle, fired auto-report as success. Fix (`backend_claude.py`): `ok = not is_error`, surface `errors` in `turn_end` meta + `AssistantMessage.error` as an `error` event; `permission_denials` logged (informational, does NOT flip `ok`). `session.py _handle_turn_end` logs `turn FAILED` and `_fire_auto_report` skips when `_last_turn_ok` is False
- 🐛 **ThinkingBlock dropped** — extended thinking silently discarded → looked like a hang. Fix: `ThinkingBlock` branch in `_convert` → `"thinking"` event, logged in `_handle_event`
- 🐛 **dead `usage["iterations"]` branch** — SDK never emits `iterations`; the `if iters:` cost loop was dead, `last = iters[-1] if iters else usage` was noise. Fix: deleted, cost from flat usage dict
- 🐛 **billing-derived context_pct wrong** — `_convert` computed ctx% from billing tokens (input+cache) against CONTEXT_LIMITS, overwritten ~1s later by `get_context_usage()` → transient wrong %, spurious "context corrected" jumps. Fix: stopped computing it (meta `context_pct=0`); `_handle_turn_end` keeps prev `_last_context` when incoming is 0; auto-compact triggers on `live_pct` from `_last_context`
- 🐛 **cost under-counts after reconnect/compact** — `total_cost_usd` is cumulative per session_id; on a new session_id it resets smaller → `max(0, new-last)` clamped to 0 → first turn after every compact contributed $0. Fix (`session.py:_handle_turn_end`): reset `_last_cost`/`_last_cost_cached`=0 when `session_id` changes (before the assignment)
- 🐛 **stale prompt on failed inject** — `_template_hash`/`_prompt_injected`/`system_prompt` set BEFORE `backend.send()` → a failed connect left a false "injected" flag, worker ran rest of life on old instructions. Fix: commit inject flags only AFTER `send()` succeeds
- 🐛 **auto-report empty stop_reason** — manager re-read live `worker._turn_logs` for `stop_reason=`, which `_turn_logs` never contains (it holds text/tool only) → always empty. Fix: `_fire_auto_report` captures `_last_stop_reason` at fire time, passes it to `on_idle(... , stop_reason)`; manager dropped the dead scan
- 🐛 **resume drops `waiting` bg-job state** — `auto_resume_all` excluded `waiting` from the resumable filter and flipped it to idle. Fix: capture `was_waiting`, include `waiting` in filter, restore WAITING post-load if `bg_manager.has_active_jobs` (both worker AND orchestrator loops — Codex)
- 🐛 **`_flush_pending` loses batch on error** — `msgs` extracted + cleared, not requeued on send failure. Fix: `_pending_messages[0:0] = msgs` in except
- 🐛 **squash stats first-ref-only** — `_parse_merged_commits` used `.search()` → multi-task squash commit attributed stats only to the first `#N`, co-refs got zero. Fix: `.finditer()`, attribute commit to ALL distinct refs
- 🐛 **`_log`/`_persist` choke the default thread-pool** — shared with git ops (`asyncio.to_thread`) → 10 agents streaming logs starved merge/spawn. Fix: dedicated `_db_executor()` (ThreadPoolExecutor max_workers=4) for DB writes
- 🐛 **blocking git/merge in the event loop** — `_load_from_db` ran `git rev-parse` sync at resume; `/merge` + `/switch-branch` ran `merge_worktree_to_main`/`switch_worktree_branch` (fcntl.flock + ~10 subprocess) SYNCHRONOUSLY in async endpoints → froze the whole loop. Fix: `asyncio.to_thread` for all three
- 🐛 **stream_logs DB connection churn** — `get_logs` opened a fresh `_conn()` (fd + 3 PRAGMAs) every 0.5–2s tick per SSE/TG poller. Fix: `get_logs(conn=...)` optional connection; SSE + TG loops reuse one connection (try/finally close) with adaptive backoff (0.5→3s / 2→5s when idle)
- 🐛 **split-brain DB (tm.py)** — `tm.py` hardcoded its own `DB_PATH`+`_conn()`, ignoring `ORCHESTRA_DB_PATH` → tasks in one file, sessions in another for tests/worktrees. Fix: deleted the dup, `from app.db import _conn` (one path resolution)

**Known tradeoff:** 2 items deferred to separate tasks — #15 (scope-level spawn lock, larger design change) and #17 (persist `_pending_messages` to inbox table, heavy feature for a rare edge).

**Triggered case:** review #35 found 19 P1s; #39 fixed the 7 P0s, this round fixes the P1s. The error-silence bug (#1) was the worst — an autonomous orchestrator can't see a rate-limited/billing-dead worker reporting "done" with empty output.

## v2.14.0 — 2026-06-01

### Fixed (7 P0 bugs from review #35 — task #39)
- 🐛 **compact() re-entry corruption** — no re-entrancy guard + `_compacting` cleared BEFORE the ack send. `_auto_compact()` (ctx>90%) and a manual `compact_worker` could enter `compact()` concurrently, racing on `session_id`/`_backend`/`_listen_task` → `RuntimeError: not connected`, dangling client, or permanent `session_id=None` (full context loss). Fix (`session.py` `compact()`): guard `if self._compacting: return {...}` set synchronously at entry; `_compacting` held True across the ack turn; ack sent via `backend.send()` directly (bypasses `send()`'s pending-queue gate)
- 🐛 **compact 60s blind poll → fabricated success** — `compact()` returned `{"ok": True}` after a 60s sleep-poll regardless of whether the ack turn completed. Fix: `_compact_ack_event` (asyncio.Event) bound to `_compact_ack_gen`; `_handle_turn_end` sets it only for the matching turn gen; `await wait_for(event, 60)` → `{"ok": False, "error": "ack turn did not complete"}` on timeout. A stray `_flush_pending`/heartbeat turn can no longer false-positive the ack (Codex finding #2)
- 🐛 **persist race resurrects stale state** — full-row `save_session(_to_db_dict())` fired from `_handle_turn_end` (438) and `_refresh_context_from_api` (704) on unordered executor threads → a stale `status=running` snapshot could overwrite a fresh `status=idle`. Fix: single-flight persist (`_persist_task` + `_persist_dirty` coalescing in `_persist_loop`). Last snapshot always wins; `get_running_loop()` fails loud off-loop; done-callback logs crashes; in-loop try/except so one DB error doesn't stop future writes
- 🐛 **merge vs remove worktree race** — `merge_worktree_to_main` held `.git/orchestra-merge.lock` but `remove_worktree` took NO lock → removing a worktree mid-merge could abort the merge / leave repo on wrong branch. Fix: `remove_worktree` now acquires the same `fcntl.flock(LOCK_EX)` on `orchestra-merge.lock`
- 🐛 **orphaned worktree on spawn crash** — `create_session` except block only called `delete_session`, leaking the worktree if `start()`/`_inject_skills`/`_safe_format_prompt` raised after creation. Plus `create_worktree` itself leaked if `git worktree add` succeeded but the PROJECT_FILES copy then raised (Codex #4). Fix: rollback inside `create_worktree` (post-add copy wrapped, removes worktree on failure) + `remove_worktree` in the manager except block
- 🐛 **zombie CLI on connect timeout** — `ClaudeBackend.connect()` left `_client` set (subprocess alive) on timeout/exception, never disconnected. `reconnect()` had the identical leak (used by heartbeat/listener recovery), and `except Exception` missed `CancelledError` (Codex #5). Fix: shared `_cleanup_failed_client()`, `except BaseException` → disconnect → re-raise, in both `connect()` and `reconnect()`
- 🐛 **restart_cli → 500** — `/api/sessions/{name}/restart-cli` called `session._disconnect_client()` which doesn't exist (`AttributeError`). Fix: `_disconnect_backend()` + imported `AgentStatus` for `AgentStatus.IDLE`

### Known tradeoff
- **P1-1 (session_id NULL window) fixed as a side-effect** — Codex review (#1) showed the ack turn needs a FRESH SDK session (no resume token) so compaction actually drops context, but the *persisted* `session_id` must NOT be nulled. New `force_fresh` param on `_make_backend`/`_ensure_backend`: ack runs on a fresh session while the old token stays in DB until the ack `turn_end` writes the new one → crash mid-compact now resumes old context instead of losing everything

### Fixed (2nd Codex round — diff review)
- 🐛 **compact COMPACT_PROMPT phase unlocked** — the summary turn (`backend.events()` loop) didn't hold `_lifecycle_lock`, so a `_flush_pending` already past its outer `_compacting` check could interleave a non-ack turn. Fix: wrap the COMPACT_PROMPT phase in `_lifecycle_lock` + recheck `_compacting` INSIDE the flush's lock body (requeues if compact won the race)
- 🐛 **ack-timeout left turn running** — on the 60s ack timeout `compact()` cleared `_compacting` while the ack turn could still be live. Fix: `_disconnect_backend()` + status IDLE before returning, so no stale turn interleaves with the next send
- 🐛 **force_fresh ignored if backend exists** — `_ensure_backend(force_fresh=True)` returned the existing backend. Now disconnects + rebuilds fresh (correctness, not just-happens-to-work in compact)
- 🐛 **spawn cleanup missed CancelledError** — `create_session` except was `except Exception` → cancellation skipped worktree cleanup. Now `except BaseException`

### Reasoning
Full research → plan → Codex review (×1 plan) → implement → Codex review (×1 diff) → fix → tests. Codex found 5 holes in the PLAN + 4 more in the DIFF (1 P0, 3 P1), all incorporated. 17 new tests (`test_session.py`, `test_backend_claude.py`, `test_workspace.py`), 86 passing (6 pre-existing failures on clean HEAD are unrelated — stale `AUTO_REPORT_IDLE_SEC`/`remove` tests). Docs: `docs/tasks/39/{research,plan,findings,codex-diff-review}.md`

## v2.13.0 — 2026-06-01

### Fixed
- 🐛 **[1m] suffix stripped — ALL agents on 200K instead of 1M** — `_make_client()` did `model.replace("[1m]", "")` before passing to CLI. CLI REQUIRES `[1m]` suffix to enable 1M context window (`claude-opus-4-6` = 200K, `claude-opus-4-6[1m]` = 1M). Every [1m] agent in Orchestra silently ran on 1/5 of their context. Fix: pass `self.model` as-is, no stripping
- 🐛 **compact_boundary invisible** — CLI `SystemMessage` with `subtype="compact_boundary"` was not caught by any branch in `_convert()`. Now emits status event "CLI auto-compacted (trigger): pre→post tokens"
- 🐛 **max_tokens from API** — `_refresh_context_from_api()` now updates `max_tokens` from SDK alongside percentage and total_tokens

### Reasoning
CLI changelog 2.1.75: "Added 1M for Opus 4.6 by default for Max plans" — but ONLY when model name includes `[1m]` suffix. Our `_make_client` stripped it → CLI saw `claude-opus-4-6` (200K). Betas approach (`context-1m-2025-08-07`) also doesn't work on subscription ("Custom betas are only available for API key users"). The ONLY way to get 1M on subscription is passing the full model name with `[1m]`.

## v2.12.0 — 2026-05-31

### Fixed
- 🐛 **Phantom context loss** — `context_pct` was reverse-engineered from `ResultMessage.usage` iterations (last iteration tokens / model limit), NOT actual context window size. Replaced with authoritative `get_context_usage()` SDK method. Fixes wildly swinging % after tool-heavy turns
- 🐛 **CLI silent autocompact invisible** — Claude CLI has its OWN internal autocompact that fires independently. We now log when authoritative % diverges >20% from estimate ("context corrected: X% → Y%")
- 🐛 **Compact crash window** — `compact()` NULLed `session_id` and persisted before starting fresh session. Server restart in that window → agent not resumed (auto_resume_all filters NULL). Removed premature persist
- 🐛 **Stale 0% after resume** — `_last_context` not refreshed until first turn_end after reconnect. Now `_refresh_context_from_api()` fires on backend connect
- 🐛 **`_compacting` double-managed** — both `_auto_compact()` and `compact()` set/cleared flag. Now `compact()` is sole owner
- 🐛 **Multiproject scope UNIQUE crash** — `ensure_project()` crashed on UNIQUE(scope) when same agent created tasks in 2+ projects. Now skips scope binding if already bound to different project

### Added
- 🎨 **Role icons from frontmatter** — `icon:` field in role MD files (`app/prompts/roles/*.md`). `/api/role-icons` endpoint serves role→emoji map. Frontend + MCP load dynamically instead of hardcoded maps
- 📁 **New role templates** — `sub-orchestrator.md` (🎯), `reviewer.md` (🔍), `watcher.md` (👁️) with frontmatter + minimal prompts
- ✅ **#34 tg_topic** — `tg_topic` bool parameter for per-agent TG topics. Root orchestrators get `tg_topic=True` automatically. API: `POST /api/sessions/{name}/tg_topic`

### Changed
- `backend_claude.py` — new `context_usage()` method wrapping `ClaudeSDKClient.get_context_usage()`
- `session.py` — `_refresh_context_from_api()` called on turn_end + backend connect; `_auto_compact` simplified to just delegate to `compact()`

### Reasoning
Context bug was a CLUSTER of 5 root causes (RC1-RC5), found by Opus research worker + Codex cross-review. Primary: per-iteration token estimate ≠ actual context window, and CLI internal autocompact runs invisibly. Fix A (authoritative API) + Fix C (no NULL persist) + Fix D (refresh on resume) + Fix E (single flag owner) applied. Full research in `docs/research-context-bug.md`.

## v2.11.0 — 2026-05-31

### Added
- 📁 **Change orchestrator scope/repo_path without losing session** — move an idle orchestrator to a new root folder while preserving its Claude `session_id` (context survives via resume). `POST /api/orchestrators/{name}/change-scope` `{old_scope, new_scope, new_cwd?}` + context-menu item "Сменить папку" in the dashboard. MVP scope: orchestrator-only, idle-only, no live workers in the old scope
- `db.change_scope()` (`app/db.py`) — single transaction: move `sessions.scope+cwd`, optional `tm_projects.scope` migration (skip on UNIQUE collision), active `bg_jobs.target_scope`, `test_lock.scope`. Gated on `WHERE id=? AND scope=old_scope` → aborts before any migration on a stale/concurrent retry (no partial move)
- `manager.change_orchestrator_scope()` (`app/manager.py`) — guards (orchestrator-only, `is_dir`, no live workers via `_live_workers_in_scope` scanning memory + DB), all under `session._lifecycle_lock` (idle race). Rebuilds `mcp_servers` via `_make_mcp_config` so the lazy reconnect gets the new `ORCHESTRA_SCOPE`; `session.id` (dict key) unchanged

### Changed
- **`_is_safe_path` containment** (`app/main.py`) — replaced `startswith(root)` with `os.path.commonpath` containment. Closes sibling-prefix escape (`/tmproot_escape` no longer passes as inside `/tmp`). Affects ALL path-guarded endpoints, not just change-scope
- **Persist drain fence** (`app/session.py`) — `_persist()` now tracks every `run_in_executor` save future in `_persist_futs` (set, auto-discarded on done); new `_drain_persist()` awaits all pending. change-scope drains in-flight persists after backend disconnect and before the DB transaction, so the transaction is the last writer of `scope+cwd` (prevents a stale `save_session(old_cwd)` clobbering cwd → wrong root after restart)

### Reasoning
`scope` is the orchestrator's identity key (UNIQUE(name,scope)), woven through 5 DB tables, the MCP subprocess env, CWD, and dashboard tabs. The hard part isn't renaming a path — it's keeping the move consistent under concurrent control-plane ops. Three Codex-flagged cross-layer races were closed: stale/partial DB migration, worker-spawn TOCTOU (in-lock re-check; full scope-level spawn lock deferred), and async-persist cwd-clobber (set-based drain). Session context is preserved because `session_id` is independent of scope.

### Known tradeoff
- Worker-spawn TOCTOU is mitigated (in-lock re-check) but not fully closed — a true close needs a scope-level lock shared with the spawn path. Acceptable for the "orchestrator with no live workers" MVP; flagged as follow-up

## v2.10.0 — 2026-05-31

### Added
- 🛡️ **Directory ownership at spawn** — `spawn_worker(..., owned_dirs='["app/api/"]')`. New `owned_dirs TEXT` JSON column in `sessions`. At spawn, overlapping dirs with a live worker (idle/running, same repo) → advisory warning to orchestrator (NOT blocked). Injected into worker prompt as off-limits siblings. `parse_owned_dirs()`/`dirs_overlap()` (prefix-aware) in `workspace.py`
- 🛡️ **Pre-dispatch conflict simulation** — `check_conflict(worker_a, worker_b)` MCP tool + `POST /api/sessions/check-conflict`. `simulate_conflict()` in `workspace.py` dry-runs `git merge-tree --write-tree`, reports conflicting paths (regex-parsed, handles content + modify/delete). Pick merge order before collisions happen
- 🛡️ **Worker WIP visibility** — `worker_wip(name, base_ref)` MCP tool + `GET /api/sessions/{name}/wip`. `branch_wip_status()` shows uncommitted files + unmerged commit subjects before resuming a worker. Returns `{error}` on git failure, never a false "clean"
- 🔒 **Block ScheduleWakeup + Cron\* tools** — removed from all agents via `disallowed_tools`. Orchestra manages scheduling via bg_jobs, agents don't need client-side scheduling

### Changed
- **Safer auto-commit** — `_auto_commit_if_dirty()` (`manager.py`) no longer silently commits dirty source-repo state before spawn. Loud labelled WIP commit (branch + file list), fail-loud on git `status`/`add`/`commit` returncodes, warning surfaced to orchestrator via `spawn_warning`
- **Worker WIP commit prompt** — `worker.md` now mandates descriptive WIP commits (`WIP: #49 — done X, Y; TODO: Z`) instead of bare `WIP`

### Reasoning
Parallel workers in isolated worktrees can silently collide (same files) or bury source-repo work (silent auto-commit). These three advisory tools surface collisions to the orchestrator at decision points (spawn, resume, pre-merge) without blocking — fits the small-team MVP "warn, don't gate" philosophy.

## v2.9.4 — 2026-05-31

### Added
- **Module `codex-review.md`** — single source for Codex review rules: when to call (`exec` for plans, `review` for diffs), `codex_review(target, output, mode)` syntax, iterate-to-consensus, MCP-only (not bash/skill), PROJECT CONTEXT via `context`. Wired into `worker` + `full-cycle` via `modules:`. `app/prompts/modules/codex-review.md`
- **Module `report-format.md`** — single source for report shapes: DONE / WIP-STOPPED / pipeline-gate messages via `send_message`. Wired into `worker` + `full-cycle`. `app/prompts/modules/report-format.md`

### Changed
- **Dedup across roles** — removed inline Codex rules and `<report-format>` block from `worker.md`; replaced inline Codex syntax + DONE format in `full-cycle.md` Phase 2/3 with module references. Roles now carry only role-specific workflow; shared rules live in modules. `app/prompts/roles/worker.md`, `app/prompts/roles/full-cycle.md`

### Reasoning
Follow-up to prompt audit. Codex review + report format were duplicated/divergent across worker and full-cycle (two different DONE formats) → consolidated so the orchestrator parses one shape and Codex usage is consistent.

## v2.9.3 — 2026-05-31

### Changed
- **Git-rule dedup** — removed the `<git>` block from `worker.md` body (duplicated `modules/git-workflow.md`, injected via `modules: [git-workflow]`). The one non-dup behavioral rule ("workers do NOT create/switch branches themselves") moved into the module so it reaches all roles. `app/prompts/roles/worker.md`, `app/prompts/modules/git-workflow.md`
- **AskUserQuestion/Monitor compressed** — two NEVER lines merged into one in `base.md` (both denied via permission hook; kept short in case the model sees the tool). `app/prompts/base.md`

### Added
- **Worker context-limit rule** — `worker.md`: on CONTEXT CRITICAL → finish current sub-task, commit, report progress, do NOT start new sub-tasks. Closes audit gap 5.1
- **Full-cycle gate-idle rule** — `full-cycle.md`: explicit "do NOT self-approve and start implementation before orchestrator approves". Closes audit gap 5.2

### Reasoning
P2 batch from prompt audit (docs/tasks/prompt-audit/). Determinism-focused: dedup keeps git rules single-source (the module), the two new rules close behavioral gaps where Opus might improvise (start new work near context limit / self-approve a plan).

## v2.9.2 — 2026-05-31

### Fixed
- **Stale Codex instruction in worker.md** — `Skill(skill="codex-review")` → `codex_review()` MCP tool. worker.md lagged behind the v2.9.0 migration to the native tool (full-cycle.md already correct) → generic workers asked for Codex review followed the obsolete path. `app/prompts/roles/worker.md`
- **report_bug scope conflict** — base.md said "platform bug only", project CLAUDE.md said "any error". Disambiguated in base.md: `report_bug` = Orchestra platform/MCP/SDK/harness failures; task-code bugs → `docs/tasks/<id>/` + orchestrator message. `app/prompts/base.md`
- **bg_create cron drift** — `<background-jobs>` listed only one-shot types and stated "Jobs are one-shot", but `cron` (recurring, added #26 in v2.9.0) was undocumented for agents. Added `cron` to the list, corrected the blanket one-shot claim. `app/prompts/base.md`

### Changed
- **orchestrator.md `<tools>` trimmed** — removed bare tool signatures that duplicate MCP tool descriptions; kept only non-obvious constraints (must be idle, do-not-retry, debugging-only) and the routing map. ~14 lines saved per orchestrator turn without losing one-path routing. `app/prompts/roles/orchestrator.md`

### Reasoning
Result of prompt audit (docs/tasks/prompt-audit/). Codex cross-review corrected 2 v1 errors (run_in_background IS enforced via permission hook; Agent/Task stripped only for orchestrators, load-bearing for workers) → mass NEVER-rule deletion was cancelled. Calibration: for MVP, determinism > token minimalism. P0 manager.py:391 (orchestrator custom prompt replaces role template) tracked separately as #28 (backend, not in this commit).

## v2.9.1 — 2026-05-31

### Fixed
- 🍒 **merge_worker unrelated histories** — `git merge-base` detects unrelated histories before merge attempt. Falls back to `_cherry_pick_branch()` which replays commits individually via `git cherry-pick --no-commit`. Clean linear history, no fake merge nodes. `workspace.py`

### Changed
- **merge precheck flow** — `git merge-base` check added before `merge-tree --write-tree`. Unrelated histories skip precheck entirely (it would fail anyway) and go straight to cherry-pick strategy
- **Prompt restructuring** — all role prompts migrated to XML tags (`<role>`, `<rules priority="critical">`, `<tools>`, etc). Critical rules deduplicated into `base.md`. English-only prompts
- **Native skills** — skills copied as `worktree/.claude/skills/{name}/SKILL.md` instead of system prompt injection. `_inject_skills_to_worktree()` in `manager.py`
- **Agent role in dashboard** — info panel shows role (worker/orchestrator/full-cycle) in purple
- **Cost precision** — `.toFixed(2)` instead of rounded integer
- **File preview** — Download button + Open in browser button for HTML files

### Added
- 🧠 **Opus 4.8** model option in all frontend model pickers

## v2.9.0 — 2026-05-29

### Added
- 🔁 **Cron agents** (#26) — `bg_create(type="cron", cron_expr="*/5 * * * *")` recurring background jobs. Fires on schedule via `croniter`, survives restart. Non-terminal trigger keeps job `active`. `no_expiry` via `timeout_seconds=0`. `bg_jobs.py`, `db.py`, `mcp_stdio.py`
- 🔌 **MCP per agent** (#24) — `spawn_worker(mcp_servers='{"playwright": {...}}')` attaches custom MCP servers to workers. Persisted in DB (`mcp_servers_custom` column), re-merged on restart. Guards `orchestra` key from override. `manager.py`, `main.py`, `mcp_stdio.py`, `session.py`, `db.py`
- 🛡️ **validate_spawn** (#25) — `can_spawn: [worker, full-cycle]` in role YAML frontmatter. Parent role whitelist enforced in `create_session`. Absent/empty = allow all. `manager.py`, `mcp_stdio.py`
- 🤖 **codex_review MCP tool** — native `codex_review(target, output, mode)` tool. Runs Codex CLI via `bg_create(type="run")`, notifies worker on completion. Replaces bash/skill workaround. `mcp_stdio.py`
- 🎨 **Pretty tool result rendering** — `get_worker_info`, `send_message`, `get_worker_logs` results rendered as styled cards instead of raw JSON. `app.js`
- 🔧 **Skills library** — `app/prompts/skills/` directory with YAML frontmatter. Roles select skills via `skills: [html-artifacts]` in frontmatter. Auto-injected into system prompt via `_load_role_skills()`. `manager.py`
- 📋 **Click-to-copy inline code** — click `<code>` in chat to copy text (like Telegram). URLs/IPs open in new tab instead. Toast notification on copy. `app.js`, `style.css`
- 🔗 **Autolink URLs/IPs** — bare URLs and IP addresses in markdown auto-wrapped in `<a>` tags. DOM walker skips `<a>`, `<pre>`, `<code>`. `app.js`
- 🏷️ **Full-cycle role** — 3-phase pipeline (Research → Plan+Codex → Implement+Codex) with 2 orchestrator approval gates. All artifacts to `docs/tasks/<id>/`. `app/prompts/roles/full-cycle.md`

### Changed
- **codex-review skill removed** — migrated to native `codex_review()` MCP tool. `full-cycle.md` updated to reference MCP tool. `app/prompts/skills/codex-review.md` deleted
- **Reviewer/Watcher roles removed** — vanilla Orchestra ships with orchestrator, worker, full-cycle. Custom roles via constructor

### Fixed
- 🔗 **URL in code copies instead of opening** — clicking URL inside backticks now navigates instead of copying to clipboard. `app.js`

### Known issue
- 🧪 **Pre-existing test failure** — `TestRemoveScope::test_passes_orch_names_to_tg_bridge_when_flag_set` (KeyError 'names'). Unrelated to v2.9 changes

## v2.8.0 — 2026-05-27

### Added
- 🚀 **Deploy script** — `deploy/install.sh root@IP` ставит Orchestra на чистый VPS за 5 мин. systemd + nginx + .env с рандомными кредами. `deploy/`
- 🔐 **Test lock** — глобальный лок для параллельных тестов. `acquire_test_lock`/`release_test_lock` MCP tools + API + DB table (PR #1, Вадим)
- 🌿 **Base branch** — воркеры ответвляются от произвольной ветки (не только main). `spawn_worker(base_branch="feature/x")`, `switch_worker_branch(from_ref=)`. Merge в произвольный target (PR #1)
- 📊 **Progress bar** — `update_progress(percent, status)` показывает индиго-бар в карточке агента + инфо-панели + красивый рендеринг в ленте логов. `app/static/js/app.js`, `app/session.py`
- 📈 **Usage sparkline** — 7d график с понедельной навигацией (◀ ▶), midnight разделители, split по сбросам. Forward-fill пробелов в данных. `app/db.py`, `app/static/js/app.js`
- 💰 **cost_usd_cached** — расчёт стоимости с учётом prompt cache (cache_read×0.1 + cache_create×1.25). `app/backend_claude.py`, `app/session.py`, `app/models.py`
- 🔔 **TG @mention** — `TG_USER_MENTION` env для тега юзера в речи агента (не в agent-to-agent). (PR #1)
- 📱 **TG topic collision** — `_pick_unique_topic_name()`: pm-taksa → pm-taksa-2 при коллизии. Backward-compat. (PR #1)
- 🗑️ **TG topic cleanup** — чекбокс "Удалить TG-топики" при удалении проекта. Модалка. (PR #1)
- ⏱️ **Jobs UI** — realtime таймер (elapsed + expires каждую секунду), expandable details по клику, persistent expanded state
- 💳 **Payment auto-resolve** — `payment_receive` без client параметра, определяет клиента по scope проекта автоматически

### Changed
- **Codex token prices** — обновлены с заниженных ($1.25/$10) до реальных ($5/$30 per 1M). `backend_codex.py`
- **TG flood handling** — 3s min interval, important/unimportant prioritизация, drop tool/status при flood. `tg_bridge.py`
- **TG long messages** — `_split_message()` разбивает на чанки по 4096 вместо молчаливой обрезки
- **Worker prompt** — `update_progress` добавлен в инструкции воркеров

### Fixed
- 🔴 **cost_usd overcounting x85** — CLI отдаёт cumulative cost, мы складывали как delta. $24,609 → $302 реальных. Delta tracking + реконструкция из логов. `session.py`, `db.py`
- 🧟 **Codex zombie detection** — `_codex_turn_loop` не ставил IDLE при timeout/error. Heartbeat проверял backend=None → skip. Теперь: finally блок + zombie check до backend check. `session.py` (#11)
- 💥 **Compact running crash** — event loop обращался к None backend. Guard + disabled кнопка на фронте. `session.py`, `app.js` (#12)
- 📝 **report_bug permission denied** — воркеры писали напрямую в файл из worktree. Теперь через API endpoint. `mcp_stdio.py`, `main.py` (#13)
- ⚡ **TG иконка не возвращалась** — `_handle_turn_end` не логировал "turn ended" → stream_logs не ловил для icon update. `session.py` (#14)
- 🔇 **TG реакции убраны** — 👍/👂 на каждое сообщение убраны. `tg_bridge.py`
- 🔓 **Auth на /send** — POST /api/sessions/*/send был доступен без авторизации. (PR #1)
- 🤖 **Disallowed sub-agents** — оркестраторы спавнили Claude sub-agents вместо MCP spawn_worker. (PR #1)
- 🗑️ **manager.remove() leak** — не удалял session из DB, оставлял сироту. (PR #1)
- 🧪 **Test suite revival** — 128 passed, 5 skipped. conftest.py с моками, ORCHESTRA_DB_PATH изоляция. (PR #1)
- 📁 **/tmp allowed** — send_file из /tmp возвращал "access denied"
- 🌐 **Global exception handler** — все 500 теперь логируются с traceback
- 📊 **5h sparkline** — убраны лишние midnight линии (14 на 2 недели данных), обрезка до текущей недели

## v2.7.0 — 2026-05-21

### Added
- 🔒 **Dashboard Auth** — cookie session login/password из .env (`DASHBOARD_USER`/`DASHBOARD_PASSWORD`). Deterministic HMAC token переживает рестарты. 30-day cookie. Backward compat — без переменных = открытый доступ. `app/auth.py`, `login.html`
- 🔒 **Security hardening** — full Codex audit, 6 critical/high fixes: path traversal deny-list (dotfiles, .db, .key), internal token auth для MCP callbacks, upload extension blocking, safe_path на send_file/session create, limit caps на SSE/logs, rename validation
- 📊 **Task priorities** — 0=critical 🔴, 1=high 🟠, 2=medium 🟡, 3=low 🟢. CSS dots в task panel. Сортировка по priority. MCP tools `task_create(priority=)`, `task_update(priority=)`
- 📦 **Worker description** — `description` поле при spawn, `update_worker_description()` tool, отображается в `list_agents` + info panel + list_agents bubble
- 🔍 **get_worker_info** — MCP tool возвращает полную инфу включая system_prompt (500 chars), description, stats
- ✏️ **update_worker_prompt** — MCP tool обновляет system_prompt воркера
- 🗄️ **Archive workers** — kill_worker теперь архивирует (status=archived) вместо удаления. Логи и статистика сохраняются. Archived не блокируют повторный spawn
- 📈 **Session statistics** — `total_turns`, `total_input_tokens`, `total_output_tokens`, `total_tool_calls` трекаются per session. `/api/stats` endpoint
- 💰 **Payment journal** — автоматическая таска-журнал в YouGile. Description обновляется при каждом `payment_receive`. Баланс + пополнения + распределения
- 📂 **File tree auto-refresh** — поллинг открытых папок каждые 10 сек, diff-update без моргания
- 📎 **Drag & drop файлов** — drop на textarea загружает файл, вставляет путь. Drop hint при dragover
- 🕐 **Timestamps в сообщениях** — `[HH:MM]` prepend для LLM, strip в dashboard и TG mirror
- 🔄 **Mid-turn inject восстановлен** — Claude: try inject → fallback queue. Codex: always queue
- 🪞 **Mirror send_file** — файлы зеркалятся в TG топик агента
- 📋 **Tab context menu** — правый клик на таб: скрыть/удалить. Wheel scroll. Кнопка скрытых табов
- ⚖️ **AGPL-3.0 license** — dual licensing: AGPL + commercial от ООО «Сидон»
- 🚀 **VPS deployment support** — полный деплой-гайд, systemd service, nginx config, auth, security audit

### Changed
- **Task prefixes removed** — `PAR-49` → `#49`. Plain numbers, legacy prefixes accepted. `format_task_ref()`, `resolve_task_ref()`, workspace branches `task-N/name`
- **Proxy parametrized** — `HTTPS_PROXY` из os.environ, не hardcoded. cli_path через `CLAUDE_CLI_PATH` env
- **Merge auto-stash** — `merge_worker` автоматически stash/pop при dirty main repo
- **MCP scope passthrough** — `task_get`/`task_update` передают scope для disambiguación
- **Rename full** — обновляет system_prompt identity + git branch + DB
- **Compact блокирует send()** — сообщения в очередь во время compact, доставляются после
- **Auto in_progress** — spawn_worker/switch_worker_branch с task_id автоматом ставит in_progress
- **bg_jobs cleanup** — triggered/expired/cancelled jobs старше 24h автоудаляются
- **Scope MCP servers** — воркеры получают MCP из `.mcp.json` проекта (Playwright и т.д.)

### Fixed
- 🔴 **Crash loop sr/nt** — `_handle_turn_end` использовал удалённые переменные → listener reconnect loop
- 🔴 **Compact interrupted** — incoming messages во время compact → empty summary → cascade crash
- 💲 **Double "kk"** — price "8k" + фронт "k" = "8kk". Backend уже форматирует
- 🏷️ **Universal prefix strip** — `replace('PAR-','')` → regex `/^[A-Z]+-/` для всех prefix'ов
- 🔐 **Internal token для всех API** — MCP tools авторизуются через Bearer token, не только /send
- 🍪 **Cookie auth на /send** — фронт отправлял cookie, middleware проверял только token
- 📋 **Ambiguous task numbers** — scope resolves одинаковые номера в разных проектах
- 📂 **Hidden files visible** — убран `startswith('.')` фильтр в /api/files
- 🖱️ **Text selection restored** — document-level drag listeners убивали выделение текста
- 📊 **Sync indicator removed** — бесполезный sync indicator для проектов без YouGile
- 🎯 **Task detail modal** — pretty commits display, scope passthrough, informative task_update bubble
- 🔄 **YouGile description sync** — description пушился в push_update (была только title+column)

## v2.6.0 — 2026-05-14

### Added
- 🔄 **Auto-resume ALL sessions on restart** — `auto_resume_all()` restores orchestrators AND workers from DB (was orchestrators-only). Sessions that were `running` at shutdown get a restart notice injected after 3s: `[system] Orchestra server restarted. Your session was restored — continue where you left off.`
  - `_inject_restart_notice()` in `manager.py` — delayed inject with error handling
  - `auto_resume_orchestrators()` kept as backward-compat wrapper
- 🤝 **Cross-orchestrator awareness** — `_other_orchestrators_block(scope)` dynamically generates a list of all other orchestrators with project names, injected into `ORCHESTRATOR_SYSTEM_PROMPT`. Each orchestrator knows who else exists and can `send_message` them. List updates on restart/compact
- 👤 **TG sender name** — all messages from TG now include `[from TG: Name]` prefix so agents know who's writing. Works for text, photos, files, video, audio, voice, video notes, stickers
- 🔒 **TG polling auto-restart** — `_safe_polling()` wraps `dp.start_polling` with crash recovery (auto-restart after 10s) + logging. No more silent polling deaths
- 📊 **Usage cache persistence** — `data/usage_cache.json` survives server restarts. No more empty usage bar after reboot caused by Anthropic rate limit + cold cache
- 🔀 **merge_worker MCP tool** — orchestrator can merge a worker's branch into main with one call. `git merge-tree` precheck detects conflicts before merging. fcntl lock serializes parallel merges. Auto-commits dirty worktree. `workspace.py`, `mcp_stdio.py`, `main.py`
- 🛑 **stop_worker MCP tool** — interrupt + idle without destroying session/worktree. Resumable via send_message. Separate from kill_worker (full delete)
- 📈 **Worker progress tracking** — `update_progress(percent, status)` MCP tool. Green glow progress bar in sidebar. Resets on new task. `session.py`, `db.py`, `mcp_stdio.py`, `app.js`
- 🖼️ **TG images as photos** — `send_file` auto-detects images (.jpg/.png/.gif/.webp/.bmp) → `send_photo()` for inline preview. `as_document=True` forces file attachment
- 🌿 **Git status in worker cards** — sidebar shows `branch+N 💾N "last commit"` per worker. `GET /api/git-status?scope=` with 10s server cache. Green/yellow/gray coloring
- 💓 **Persistent client heartbeat** — 60s heartbeat detects silent listener death, auto-reconnects with inject notice. Silence warning >300s. Full tracebacks on crash

### Changed
- **Usage cache TTL 120→300s** — backend and frontend polling aligned at 5min to reduce Anthropic API rate limit hits
- **TG logger** — `tg-bridge` logger now has `StreamHandler` + `DEBUG` level, all TG events visible in journalctl
- **SSE disconnect leak** — `stream_session_logs` generator now checks `request.is_disconnected()`, stops on tab close

### Fixed
- 🟢🟡 **TG topic status desynced from frontend** — single source of truth via `_any_running_in_scope(scope)`. When orchestrator finishes turn but workers still running → stays 🟢 (was: immediately 🟡). When ANY worker goes idle → `_notify_scope_idle()` checks scope → flips to 🟡 only when ALL idle
  - `check_scope_idle()` in `tg_bridge.py` — public function called from `session.py` and `stream_logs`
  - `_notify_scope_idle()` in `session.py` — fires on every worker IDLE transition, not just auto-report
- 🟢🟡 **TG topic status on startup** — `_sync_all_topic_statuses()` sets correct 🟢/🟡 on all topics when bridge starts
- 🪞 **TG mirror formatting** — mirror messages now receive `converted` text + `entities` from `md_convert()` (was: raw plain text without formatting). All 3 send paths: text/status, tool, tool_result

## v2.5.0 — 2026-05-11

### Added
- 🚀 **Persistent client + mid-turn message injection** — replaced "fresh client per turn" with persistent client per session. `send()` → `client.query()` directly via SDK stdin transport. No more pending queue, debounce, turn boundary waiting. Messages inject mid-turn as system-reminders
  - `_ensure_client()` — connects once, reuses across turns
  - `_persistent_listen()` — infinite loop over `receive_messages()`, does NOT disconnect on ResultMessage
  - `_disconnect_client()` — clean shutdown helper
  - Auto-reconnect: detects dead listener, retries `query()` on failure
  - Removed: `_pending`, `_debounce_task`, `_turn_task`, `_run_turn()`, `_arm_debounce()`, `_on_debounce()`, `debounce_sec`
- 📊 **Usage status bar** — global bar at top of dashboard. OAuth API (`/api/oauth/usage`) with 120s cache, shows 5h/7d utilization with HSL gradient color (green=under budget, yellow=on track, red=burning fast), reset progress % in parentheses. `/api/usage` endpoint combines Anthropic data + per-agent cost from DB
- 🎯 **Spawn worker bubble** — card with `🚀 Spawning name` + model badge pill (color-coded) + markdown task preview + system prompt + repo path. Single click expands all
- 🌐 **WebSearch result renderer** — bracket-counting JSON parser for Links format, Perplexity markdown with token/cost header, standalone detection when `lastTool` is null. Collapsible (5 lines preview)
- 🔍 **ToolSearch bubble** — `🔍 Loading: query` → `✅ Loaded: ToolName` on result
- 🐛 **report_bug bubble** — `🐛 Bug: title` with collapsible description
- 🖼️ **Base64 image rendering** — tool_results with image data render as `<img>`, not raw base64 text
- 📝 **Textarea resize upward** — drag handle above textarea, pull up to expand (bottom of screen = can't drag down)
- 🔄 **Auto-compact for orchestrators** — removed `not self.is_orchestrator` exclusion, orchestrators auto-compact at >90% context

### Changed
- **`interrupt()`** — uses `client.interrupt()` SDK method instead of asyncio task cancellation
- **`compact()`** — stops listener first (race condition fix), bracket-counted JSON parse, disconnects cleanly
- **Turn timeout** — tracked via `_turn_start` timestamp instead of `asyncio.wait_for()`
- **send_message bubble** — split by lines (5 preview), re-render full on expand. No more mid-word cuts
- **Tool result expand** — line-based preview (was char-based), single element with maxHeight (no gap/separator), universal click-to-expand on all bubble types
- **Model aliases** — `claude-opus-4-6` → `claude-opus-4-6[1m]` auto-resolve
- **Worker custom prompt** — `_safe_format_prompt()` replaces `str.format()`, only substitutes known placeholders. Resume correctly extracts custom portion
- **Load-more tool_result matching** — `_findLastBefore()` constrains querySelector to prepended batch only

### Fixed
- **WebSearch `isEdit` bug** — spawn_worker/WebSearch/ToolSearch bubbles had `dataset.isEdit='1'` which caused tool_result handler to early-return, silently swallowing results
- **WebSearch regex** — replaced fragile regex with bracket-counting parser for Links JSON arrays (handles truncated SDK output, multi-item arrays, special chars)
- **Load-more rendering** — old messages now use `addChatEntry()` with full custom bubbles
- **compact() race condition** — listener paused before iterating `receive_messages()`
- **Persistent client dead process** — `_ensure_client()` checks `_listen_task.done()`, `send()` retries with reconnect on `query()` failure
- **Universal click-to-expand** — audit of all handlers, WebSearch and Read .md fixed (were hint-only)

## v2.4.0 — 2026-05-10

### Added
- 🎤 **TG Voice** — Deepgram Nova-3 транскрипция голосовых в TG bridge
- 📷 **TG Media** — полная поддержка: фото, документы, видео, video_note (ffmpeg), аудио, стикеры, forwards с caption. Кеши файлов + транскрипций
- 🔄 **TG Debounce** — state machine IDLE→COLLECTING→WAITING_MEDIA. 5s debounce + 30s media timeout. Батч сообщений в один turn
- 📂 **File preview** — клик по файлу → модалка. MD рендерится через marked.js, картинки через `<img>`, код с горизонтальным скроллом. `/api/files/content` + `/api/files/raw` endpoints
- ✏️ **Diff view** — Google `diff-match-patch` для char-level inline подсветки. LCS line diff + inline highlight для похожих строк (>40% common). Preview 5 строк + expand
- 📖 **Read view** — code viewer с shimmer skeleton, 5 строк preview + expand. Картинки рендерятся как `<img>`
- ✍️ **Write view** — содержимое как diff (всё зелёное)
- 📨 **send_message bubble** — `📨 → target` + markdown preview вместо сырого JSON
- 📜 **Prompt viewer** — 3 секции (📦 Platform / 🎭 Role / ✨ Custom) с реальными подставленными именами
- 📋 **Compact mode** — toggle 📋/📄 в header. Тулы в одну строку, клик раскрывает
- 🖼 **Картинки везде** — user messages, Read tool, text — кликабельные → file preview
- 💰 **Ценник в sidebar** — `$X.XX` зелёным рядом с моделью
- 🌐 **WebSearch рендер** — title (ссылка) + snippet вместо JSON
- 🔧 **Autocommit** — `git add -A && commit "wip:"` перед spawn_worker. Worktree создаётся от актуального кода — нет конфликтов
- ⚡ **Seamless turn** — после ResultMessage если есть pending → сразу новый turn (0ms вместо 2.5s debounce)
- 📊 **stop_reason логирование** — каждый turn пишет `stop_reason=X, num_turns=N`
- 🎼 **Orchestra skill** — `/orchestra` Claude Code skill в `app/skills/orchestra/SKILL.md`
- 🔒 **XSS fixes** — 3 innerHTML→textContent fixes (Codex review)

### Changed
- **max_turns 25→50** — воркеры не обрубаются на больших задачах
- **kill_worker** — теперь `DELETE` (полное удаление), не `POST /stop` (воркеры-призраки больше не висят)
- **Inject убран** — все сообщения в pending queue, нет потерянных/дублей
- **Logs limit 200→5000** — старые сообщения видны в чате
- **MAX_CHAT_NODES 500→5000** — DOM не обрезает историю
- **Deepgram Nova-2→Nova-3** — точнее для русского, та же цена
- **Orchestrator prompt** — обязательный system_prompt для воркеров (шаблон + примеры), file conflict rule, CTO delegation
- **Worker prompt** — bash rules (no polling loops), identity placeholders

### Fixed
- **TG flood control** — retry с backoff вместо fallback на plain text
- **TG error logging** — видно почему formatted send фейлится
- **HTML injection в tool_result** — escape `<>` перед innerHTML
- **Paste preview** — сохраняется/восстанавливается при переключении агентов
- **Markdown everywhere** — user messages, [from:worker], все рендерятся через marked.js
- **chat-bot border** — `#1e293b`→`rgba(99,102,241,0.1)` (видимый)
- **diff-code overflow** — `break-all`→`overflow-wrap: anywhere`
- **Read skeleton** — shimmer placeholder пока tool_result не пришёл
- **Expand hint** — rHint перенесён, querySelector работает
- **Restart без confirm** — убран confirm dialog
- **Prompt viewer identity** — реальные имена вместо `{worker_name}` placeholder
- **Custom prompt после ребута** — кастомная часть сохраняется при hot-reload
- **streamBubble на смене orchestrator** — сброс при переключении
- **initFilePanel drag listeners** — guard от накопления
- **refreshSessions stale scope** — capturedScope проверка

## v2.3.1 — 2026-05-09

### Added
- 🗜 **compact_worker MCP tool** — orchestrator can compact a worker's context (summary → reset session → continue fresh). Tested: 81%→17%, 56%→16%, 20%→16%
- ⚠️ **Context warning >90%** — platform auto-appends `⚠️ CONTEXT CRITICAL` to worker messages
- 🚫 **AskUserQuestion + run_in_background denied** — blocked via `can_use_tool` deny
- 🔧 **Tool+result merged** — one bubble on frontend, one expandable on TG
- 🎨 **Tool icons** — 🖥 Bash, 📖 Read, 🎼 orchestra, 🔌 MCP
- 📝 **Draft per agent** — unsent text preserved when switching
- 🔗 **URL linkify** — clickable links in tool_result
- 💊 **Status badge** — pill with colored bg on idle/running text

### Fixed
- **compact_worker timeout** — was 30s, compact takes ~40s → empty error → double compact. Now 120s
- **Prompt placeholders** — `{orchestrator_name}` was literal in hot-reload for workers
- **Scroll on switch** — chat now scrolls to bottom when opening agent
- **Timestamps overlap** — inline block instead of absolute positioning

## v2.3.0 — 2026-05-09

### Added
- 📱 **TG Bridge** (`app/tg_bridge.py`) — mirrors orchestrators to Telegram group topics.
  Auto-creates topic per orchestrator, bidirectional messaging, real-time log streaming.
  Separate bot (`@orchestraClaude_bot`), config in `.env` / `data/tg_bridge.json`
- 📬 **Kesha inbox server** (`inbox_server.py` in kesha-tg-bot) — HTTP endpoint :18081,
  Orchestra → Kesha via `notify_kesha` MCP tool → shows in Telegram chat
- 🔄 **Auto-report** — workers that finish without `send_message` get force-reported to
  orchestrator with last 3 text outputs. `[from:worker] [auto-report]` format
- 💉 **Message inject** — messages to RUNNING agents injected via `client.query()` immediately,
  no waiting for turn end. Fallback to pending queue on failure
- 🔥 **Prompt hot-reload** — updated `app/prompts/*.md` injected on first turn after restart.
  `[Orchestra platform note]` tag avoids prompt injection detection
- 📊 **Context tracking** — `input + cache_creation + cache_read` from last iteration,
  per-model limits (Opus 1M, Sonnet 200k), cache hit % in agent info panel
- 📈 **Context bar** — colored progress bar per agent in sidebar (green/yellow/red)
- 🌐 **Cross-project messaging** — `list_orchestrators()` discovers all orchestrators,
  `send_message` fallback searches by name across all scopes (`ensure_loaded_any`)
- 🐛 **report_bug MCP tool** — agents file bugs to `BUGS.md` with timestamp/reporter/scope
- ⟳ **Restart button** — dashboard header, `sudo -n systemctl restart orchestra`
- 💊 **Orchestrator tabs** — pill buttons replace dropdown, recent-first, live status dots
- 🖼 **Image paste** — Ctrl+V upload with md5 dedup, preview under input, render in chat
- ⚡ **Status badges** — `⚡ interrupted`, `⚡ system prompt updated` as centered badges in chat
- 📐 **Shared prompts** — `app/prompts/base.md` + `orchestrator.md` + `worker.md`, shared platform knowledge

### Fixed
- **Stop deleted logs** — `POST /stop` now calls `unload()` (preserves DB), not `remove()` (cascade)
- **Scroll hijack** — `showWaitingIndicator` respects `wasAtBottom`, no re-creation in refresh loop
- **Context 0%** — usage is dict not object (`.get()` not `getattr()`), last iteration not sum
- **Context 227%** — top-level usage sums all API calls, context = last iteration only
- **Trailing slash** — scope normalized with `rstrip("/")` at creation and lookup
- **Ghost workers** — `kill_worker` for DB-only sessions deletes from DB directly
- **MCP not visible** — `.mcp.json` no longer copied to worktrees (was overriding Orchestra MCP);
  `mcp_stdio.py` invoked by absolute path (was failing with `-m` from non-orchestra CWD)
- **SendMessage vs send_message** — prompts explicitly say `mcp__orchestra__send_message`
- **Interrupt stuck** — now awaits task cancellation, drops client, sets IDLE + persist
- **Newlines lost** — tool input via `json.dumps(indent=2)`, `white-space: pre-wrap` on frontend
- **Lost messages** — SSE user_message replaces pending bubble instead of skipping
- **Prompt injection** — `[SYSTEM UPDATE]` tag softened to `[Orchestra platform note]`
- **Repeated prompt inject** — `system_prompt` synced after inject, no more every-turn spam

### Changed
- **spawn_worker scope** — uses orchestrator's ORCHESTRA_SCOPE, not repo_path (workers visible in list_agents)
- **Prompts split** — old `orchestrator_prompt.md` + `worker_prompt.md` → `prompts/base.md` + role-specific
- **SDK 0.1.74** — updated from 0.1.72

## v2.2.0 — 2026-05-05

### Added
- 🗑️ **Delete orchestrator** — `DELETE /api/orchestrators/{name}` removes orchestrator + all
  workers in scope (active sessions, worktrees, DB records). Dashboard button `✕ Delete` with
  confirm dialog. `manager.remove_scope(scope)` handles cleanup.
- 💾 **Remember last orchestrator** — `localStorage` saves `lastOrchScope`/`lastOrchName` on
  switch, restores on page load. No more "always opens first in list".

### Fixed
- **Stop deleted logs (critical)** — `POST /stop` called `manager.remove()` which ran
  `DELETE FROM sessions` → `ON DELETE CASCADE` wiped all logs. Now stop calls `unload()`
  (stops session, removes from memory, preserves DB). Only explicit Delete removes from DB.
  - Triggered case: kesha-tg-bot orchestrator stuck running after interrupt, used stop to
    unstick it → 2318 log entries deleted by cascade. User saw empty chat.
- **Scroll hijack on history read** — three sources of forced scroll-to-bottom:
  1. `showWaitingIndicator()` unconditionally set `scrollTop` — now checks `wasAtBottom`
  2. SSE handler had duplicate scroll check after `addChatEntry` (which already handles it)
  3. `refreshSessions` re-created waiting indicator every 3s (SSE removed it → refresh
     recreated → scroll). Removed re-creation from refresh loop.

## v2.1.0 — 2026-05-04

### Added
- 📡 **SSE realtime logs** — `GET /api/sessions/{name}/stream` replaces polling for chat
- 🏥 **Health check loop** — detects crashed worker tasks every 60s
- 🔌 **Systemd service** — `orchestra.service` with auto-restart and Hiddify proxy
- 🎨 **Smart color picker** — unique color per worker, least-used fallback
- 🏷️ **Auto sender tag** — server adds `[from:name]`, workers send plain text
- 📴 **Offline CSS** — Tailwind/marked/DOMPurify bundled locally

### Fixed
- **Auto-resume crash** — error sessions marked stopped on startup
- **cli_path** — dynamic via `shutil.which("claude")`
- **Worker logs** — filtered (text/tool/error only), no raw dumps
- **tool_result parsing** — unwraps `{"result":"..."}` wrapper
- **Proxy** — `HTTPS_PROXY` set in session.py, manager.py, service file

## v2.0.0 — 2026-05-03

### Changed
- **External stdio MCP server** — MCP tools now run as separate process (`app/mcp_stdio.py`)
  via FastMCP, communicating with Orchestra API over HTTP. Replaces in-process `create_sdk_mcp_server`
  which caused deadlocks (SDK issue #425). External process = no shared event loop = no hang.
- **Simplified session.py** — removed persistent client, locks, _is_connected, _cleanup_client.
  Each turn: create fresh ClaudeSDKClient → connect → query → receive → disconnect (in finally).
  Root cause of ALL hangs was accumulated state in persistent connection.
  Proven: direct SDK test = 5 MCP calls in 17s. Old session.py = hang on 3rd call.
  New session.py = 18 MCP calls in 85s, zero hangs. -328 lines, +166 lines.
- **Worker communication via HTTP** — workers send reports via `curl POST /api/sessions/{name}/send`.
  Orchestrator receives via debounce → new turn. No MCP inject needed.
- **System CLI** — uses system Claude CLI 2.1.126 via `cli_path` instead of bundled 2.1.117

### Added
- 📬 **Worker Inbox** — `inbox` DB table + `GET /api/sessions/{name}/inbox` endpoint.
  `send_to_worker` queues messages in inbox. Real delivery semantics.
- 📋 **Job Registry** — `jobs` DB table + `GET /api/jobs` endpoint + `list_jobs` MCP tool.
  spawn/kill create tracked jobs with status (queued/executing/succeeded/failed).
- ⏱️ **Turn timeout** — 300s hard deadline on `_listen()`, 60s on `connect()`.
  TimeoutError → ERROR status. No more infinite hangs.
- 🔒 **Scoped lookups** — `find_worker(name, scope)`, `find_session_id_by_name(name, scope)`.
- 🧪 **`.mcp.json`** — project-level MCP config for local testing from Claude Code
- `alwaysLoad: true` — MCP tools skip ToolSearch deferral (v2.1.121 feature)

### Removed
- `create_sdk_mcp_server` in-process MCP (deadlock source)
- Persistent client connection in session.py (accumulation source)
- `.env` copy to worktrees (security fix)
- Prompt rule "max 2 MCP calls" (no longer needed)
- SDK monkey-patches (buffer, stdin) — no longer needed

### Fixed
- **Duplicate user_message logs** — send() logs once, _run_turn no longer duplicates
- **Timestamps** always visible in white on dashboard
- **pytest discovery** — testpaths=["tests"], norecursedirs for worktrees

## v1.3.0 — 2026-05-02

### Fixed
- **SDK MCP tool hang — root cause found and workarounds applied** — in-process MCP tool calls
  (`create_sdk_mcp_server`) hung after 2-3 calls per turn. Root cause: SDK `Query._read_messages`
  single read task handles both control_request routing AND bounded message stream (`max_buffer_size=100`).
  When buffer fills, read task blocks on `send()` → control_requests never reach Python MCP handlers → CLI
  waits for control_response forever → deadlock. SDK issue #425 (open, no PR).
  - **SDK patch: buffer 100→10000** — `query.py` monkey-patch, prevents backpressure up to 10000 messages
  - **SDK patch: stdin kept open** — `wait_for_result_and_end_input()` no longer closes stdin when SDK MCP
    servers present. Needed for persistent connections with multiple query() calls
  - **Spawn queue** — `spawn_worker` MCP tool no longer does heavy work (git worktree + session start)
    inside the MCP handler. Jobs enqueued to `asyncio.Queue`, processed by background supervisor task
    with 0.5s delay to let control_response flush first (Codex review finding)
  - **git worktree via to_thread** — `create_worktree()` sync subprocess moved to `asyncio.to_thread()`
    to avoid blocking event loop during MCP response path
  - **Inject removed** — `session.send()` no longer calls `client.query()` inject on RUNNING sessions.
    Messages queue in `_pending`, processed as new turn when session goes IDLE. Inject caused transport
    deadlock (both directions: worker→orch and orch→worker)
  - **Worker HTTP callback** — workers send reports via `curl POST /api/sessions/{name}/send` instead of
    MCP `send_message` inject. Eliminates transport deadlock entirely for worker→orchestrator communication
  - **Async DB writes** — `_log()` and `_persist()` via `run_in_executor()` to avoid blocking event loop
  - **include_partial_messages=False** — reduces stream event volume in SDK bounded buffer
  - **Orchestrator prompt: max 2 MCP calls per response** — prevents hitting CLI tool call limit per turn
  - Triggered case: every test with orchestrator + worker — spawn→list_workers→get_worker_logs chain hung
    on 3rd MCP call every time. Single MCP calls worked fine (5s). Multiple calls = deadlock.

### Changed
- **SDK pinned** — `claude-agent-sdk>=0.1.72` in pyproject.toml. Was unpinned, any `uv sync` could
  break everything. v0.1.72 fixes silent MCP tool result loss (v0.1.70+)

### Added
- **Spawn queue** — `SessionManager.enqueue_worker_spawn()`, `_spawn_worker_loop()` background task
- **Session error callback** — `AgentSession.on_error` + `SessionManager._on_session_error()` moves
  errored sessions from active to archived automatically

## v1.2.0 — 2026-05-01

### Changed
- **Data layer refactor — single source of truth** — `SessionManager` is now the sole data gateway.
  `manager.archived: dict[str, dict]` holds stopped/error sessions in memory. `list_sessions()` reads
  purely from memory (active + archived), zero DB merges. `stop()` moves session from active → archived.
  `tools.py` has zero direct DB imports (except `get_logs`). `main.py` reduced from 4 DB fallback paths to 0.
  - `load_archived()` at startup populates archived dict from DB
  - `find_worker()`, `find_session_id_by_name()`, `archive_by_id()`, `get_session_id()` — new manager methods
  - `ensure_loaded()` skips archived sessions (no zombie resurrections)
  - `kill_worker` for DB-only sessions now properly archives via `archive_by_id()`
  - 10 new TDD tests for archived dict behavior (107 total)
  - **Before**: 8 code paths with direct DB access scattered across tools.py + main.py, different formats (AgentSession vs dict), merge logic, fallback reconnects
  - **After**: manager = memory cache, DB = write-through backup + logs storage. One path, one format

## v1.1.0 — 2026-05-01

### Added
- 📡 **Streaming text** — responses appear live as chunks, not after full generation. `StreamEvent` + `content_block_delta` handling
- 📎 **Tool results visible** — MCP tool outputs (`ToolResultBlock`) shown in chat with 📎 prefix
- 🪦 **Agent archive** — stopped/killed workers get hash suffix (e.g. `worker-1-abc123`), move to archive section. Name freed for reuse. Chat history preserved, read-only
- 🏷️ **Model registry** — `app/models.py` single source of truth. Aliases resolved (`sonnet` → `claude-sonnet-4-6`). API validates, dropdown loads from `/api/models`
- 🔄 **restart_worker** MCP tool — kill + respawn in one call
- 📊 **Context display** — `5% (12k/200k)` format, cached on agent switch

### Fixed
- **Worktree preserved on stop** — `stop()` no longer deletes worktree. Only explicit `kill/remove` does
- **Auto-resume rehydrate** — all fields restored from DB (worktree_path, branch, created_at)
- **`_run_turn()` exceptions** — done callback logs errors, sets ERROR status
- **Error UX** — no "waiting for response" after 404/error. Debounce cancelled on failure
- **Stopped agent resume** — writing to stopped agent auto-resumes it (fallback cwd if worktree missing)
- **Duplicate names** — stopped agents archived with hash, name freed for new workers
- **`list_workers`** — shows active + archived workers

### Changed
- `shutdown_all` — orchestrators stay `idle` (not stopped) for auto-resume. Workers get stopped with worktrees intact

## v1.0.0 — 2026-04-30

Complete rewrite from MVP v0.4. One class, one way, Apple-level simplicity.

### Added
- 🏗️ **`AgentSession`** — single SDK wrapper replacing both `Worker` and `Orchestrator` classes. One class for all agents, config-driven (model, system_prompt, mcp_servers)
- 🌿 **`workspace.py`** — isolated worktree management. Scope-namespaced paths (`worktrees/{scope_slug}/{name}`), fail loud, no silent fallbacks
- 🔧 **MCP tools for orchestrator** — `spawn_worker`, `send_to_worker`, `list_workers`, `get_worker_logs`, `kill_worker`. Orchestrator manages workers natively via MCP, not prompt hacking
- 🔧 **MCP tools for workers** — `send_message` (to any agent), `list_agents`. Workers can communicate with orchestrator and each other
- 📝 **System prompts** — `orchestrator_prompt.md` and `worker_prompt.md` in `app/`. Editable .md files, not hardcoded strings
- 🖥️ **Dashboard v2** — single-screen UI: chat with any agent (left), agent list + info (right). Click to switch between orchestrator and workers. Markdown rendering, debounce indicator, adaptive polling (500ms when waiting, 3s idle)
- 📊 **Message debounce** — multiple rapid messages batched into one (2s window, like Kesha). Visual ring timer on pending messages
- 💉 **Live inject** — messages sent while agent is RUNNING inject directly into current turn (no queue, no "session busy")
- 🧪 **97 TDD tests** — `test_db.py` (29), `test_workspace.py` (16), `test_session.py` (18), `test_manager.py` (14), `test_api.py` (20). Written before code (RED→GREEN)
- 🔑 **UUID primary keys** — `UNIQUE(name, scope)` for display, UUID internally. No collisions between scopes
- 📡 **Multi-orchestrator support** — one dashboard, multiple orchestrators (one per project). Picker in header, scope filtering
- 🔄 **Auto-resume** — orchestrators survive server restart (status stays `idle`, SDK resumes via `session_id`)
- 🛡️ **Permission fix** — `default` + `can_use_tool` auto-approve instead of `bypassPermissions` (known regression: Claude Code #36497, #37157, #36923)

### Removed
- `worker.py` — replaced by `AgentSession` in `session.py`
- `orchestrator.py` — replaced by `AgentSession` in `session.py`
- `callbacks` table — replaced by session logs with `type="notification"`
- 18 API endpoints → 9 (one resource `/api/sessions`)
- `max_turns` parameter — SDK manages this
- `data/orchestrator_session` file — session_id now in SQLite
- Separate notifications tab — everything in chat

### Changed
- **DB schema** — `sessions` + `logs` (was `workers` + `logs` + `callbacks`). UPSERT, CASCADE, `busy_timeout=5000`, `foreign_keys=ON`
- **API** — one resource `/api/sessions`. Pydantic validation, proper HTTP status codes (404/409/422), no `{"ok": false}`
- **Dashboard** — HTML/CSS/JS split into separate files. DOM API rendering (no innerHTML XSS). Cursor-based log pagination

### Architecture
```
app/
  main.py            — FastAPI, 9 endpoints
  session.py         — AgentSession (single SDK wrapper)
  manager.py         — SessionManager (registry + lifecycle)
  workspace.py       — git worktree create/remove
  db.py              — SQLite (sessions + logs)
  tools.py           — MCP tools for orchestrator + workers
  orchestrator_prompt.md
  worker_prompt.md
  static/css/style.css
  static/js/app.js
  templates/dashboard.html
```

### Process
- 4-round Codex (GPT-5.5) adversarial review of spec before implementation
- TDD for all modules: tests written first, then minimal code
- Codex code review (Round 5) caught 4 real bugs post-implementation
