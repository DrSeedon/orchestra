## Tests
`python -m pytest tests/ -x -q 2>&1 | tail -20` упал на первом тесте:
`ERROR tests/test_api.py::TestDashboard::test_root_returns_html - AttributeError: <class 'app.session.AgentSession'> does not have the attribute '_make_client'`.
Локальный `python` = 3.13.7, проект заявлен как Python 3.12.

## Summary
Phase 0 частично сделан: `auth.py` подключен в `main.py`, cookie-login работает по env, Claude proxy читается из окружения в `backend_claude.py`. Для публичного VPS деплой пока нельзя считать безопасным: один write-endpoint остался без auth, а uploads отдаются публично. План в целом рабочий, но в нём есть секрет в тексте и несколько шагов, которые на чистой Ubuntu могут остановить деплой. In-memory sessions для MVP допустимы, если разлогин после рестарта принят как нормальное поведение.

## Замечания
blocking: app/auth.py:64 + app/main.py:386 — `POST /api/sessions/{name}/send` освобождён от auth, поэтому любой снаружи может отправить команду агенту через Nginx. Фикс: требовать dashboard session для этого endpoint, а для MCP добавить отдельный локальный/internal token header (`ORCHESTRA_INTERNAL_TOKEN`) и проверять его в `mcp_stdio.py`.

blocking: app/auth.py:60 + app/main.py:810 — `/uploads/*` публичный при включённом dashboard auth; туда попадают файлы из dashboard/TG bridge. Фикс: убрать `/uploads/` из bypass auth или заменить на signed URLs с TTL.

blocking: docs/deploy-amsterdam/PLAN.md:109 — в плане лежит реальный-looking Telegram bot token, пусть и закомментированный. Фикс: удалить секрет из docs и rotate token, если он настоящий.

blocking: docs/deploy-amsterdam/PLAN.md:96 — план вызывает `uv sync`, но не устанавливает `uv` на чистой Ubuntu. Фикс: добавить шаг установки `uv` до `uv sync` и проверить, что `/opt/orchestra/.venv/bin/python` появился.

suggestion: app/manager.py:29 — `MCP_BASE_ENV` собирается на import, а `.env` грузится позже в `app/main.py:34`; proxy из `.env` не попадёт в MCP env до restart с systemd Environment. Фикс: строить env внутри `_make_mcp_config()` или вызывать `load_dotenv()` до импорта `SessionManager`.

suggestion: app/backend_claude.py:86 — `CLAUDE_CLI_PATH` не может override-нуть найденный в PATH `claude`, потому что порядок `shutil.which("claude") or env`. Фикс: `os.environ.get("CLAUDE_CLI_PATH") or shutil.which("claude") or "claude"`.

suggestion: app/main.py:145 — session cookie без `secure=True`; после SSL cookie всё равно можно выставить/передать по HTTP, если редирект или доступ к 80 сломан. Фикс: на VPS ставить `secure=True` хотя бы при `DASHBOARD_COOKIE_SECURE=1`.

suggestion: .env.example:1 — `.env.example` не обновлён под Phase 0: нет `DASHBOARD_USER`, `DASHBOARD_PASSWORD`, `CLAUDE_CLI_PATH`. Фикс: добавить новые переменные с безопасными placeholder-значениями.

suggestion: docs/deploy-amsterdam/PLAN.md:87 — `rsync` не исключает локальную `.claude/`; сейчас там нет файлов, но при появлении `settings.local.json` он уедет на VPS до перезаписи проектного config. Фикс: добавить `--exclude='.claude'` и создавать `/opt/orchestra/.claude/settings.json` только явным шагом 2.5.

suggestion: docs/deploy-amsterdam/PLAN.md:196 — Phase 4 использует `nginx` и `certbot`, но плана установки пакетов нет. Фикс: добавить `apt install -y nginx certbot python3-certbot-nginx` и проверку DNS перед certbot.

question: app/auth.py:28 — in-memory sessions означают logout всех пользователей при restart/deploy. Для 1 клиента и MVP это, вероятно, нормально; если нет, хранить sessions в SQLite с TTL.

## Вердикт
Не деплоить публично до фикса двух auth bypass и удаления секрета из плана.

## Round 2

### Blocking status
1. `/api/sessions/{name}/send` без auth — STILL BROKEN. План добавил правильное направление, но фикс описан слишком узко: MCP вызывает не только `/send`, а также `/api/sessions`, `/api/jobs`, `/api/orchestrators`, `/api/tg/send_file` и другие защищённые `/api/*`. Фикс: `AuthMiddleware` должен принимать `X-Orchestra-Token` для всех internal API callbacks до cookie-check, а `app/mcp_stdio.py` должен добавлять header на каждый HTTP-запрос.

2. `/uploads/` без auth — FIXED in plan. Условие перед деплоем: реально убрать `/uploads/` из `requires_auth()` и smoke-test `GET /uploads/<existing>` без cookie должен давать `302` на login или `401`, не `200`.

3. TG token в плане — FIXED. В обновлённом `PLAN.md` реального токена больше нет, остались placeholders.

4. `uv` не установлен — FIXED. Проверка `uv --version` с fallback на установку достаточна, учитывая что VPS уже проверен.

### New issues
blocking: docs/deploy-amsterdam/PLAN.md:162 — `ORCHESTRA_INTERNAL_TOKEN` генерируется в `.env`, но проектный `.claude/settings.json` передаёт в MCP subprocess только `PYTHONPATH` и `ORCHESTRA_URL`. Даже после кода с header `mcp_stdio.py` не узнает token и internal callbacks будут получать `401`. Фикс: либо `mcp_stdio.py` грузит `/opt/orchestra/.env` через `load_dotenv`, либо шаг 2.5 явно записывает `ORCHESTRA_INTERNAL_TOKEN` в `.claude/settings.json`.

blocking: docs/deploy-amsterdam/PLAN.md:114 — деплой теперь делает `git clone` из публичной репы, а Phase 0.5 пока описана как будущая работа. Если фиксы не будут закоммичены и запушены до Phase 2, VPS получит старый уязвимый код. Фикс: добавить gate перед deploy: commit/tag с Phase 0.5, `git rev-parse HEAD`, и deploy именно этого commit.

suggestion: docs/deploy-amsterdam/PLAN.md:217 — заявленные smoke tests для auth bypass в плане фактически не добавлены: после запуска есть только `curl /`. Фикс: добавить команды: unauth `POST /api/sessions/<name>/send` → `401`, unauth `GET /uploads/<file>` → not `200`, MCP request с `X-Orchestra-Token` → success.

suggestion: docs/deploy-amsterdam/PLAN.md:132 — `.env` создаётся от текущего shell-пользователя, потом `chown/chmod`; это ок, но если команда выполняется после `su - orchestra`, `chown` может упасть без root. Фикс: явно пометить, какие блоки выполняются root, а какие `orchestra`, или использовать `sudo -u orchestra` для git/uv и root для service/env ownership.

### Verdict
NOT YET. План стал существенно лучше, но internal token flow должен быть описан end-to-end до approval.

## Round 3

### Blocking status
1. `/api/sessions/{name}/send` / internal token для всех `/api/*` callbacks — FIXED. План теперь требует проверку `X-Orchestra-Token` до cookie-check для всех internal API calls и header на каждый запрос из `mcp_stdio.py`.

2. `ORCHESTRA_INTERNAL_TOKEN` не попадал в MCP subprocess — FIXED. Шаг 2.5 читает token из `/opt/orchestra/.env` и записывает его в env block `.claude/settings.json`.

3. Phase 0.5 мог не попасть в git перед deploy — FIXED. Добавлен gate `commit + push` до `git clone`, плюс проверка последнего commit на VPS.

4. Smoke tests для auth bypass были неполные — FIXED enough. Добавлены проверки `/send`, `/uploads`, `/api/*` без auth и positive test с `X-Orchestra-Token`.

### New issues
suggestion: docs/deploy-amsterdam/PLAN.md:21 — в реализации token-check явно запретить пустые значения. Иначе наивный `compare_digest(header_or_empty, env_or_empty)` может принять пустой header при пустом `ORCHESTRA_INTERNAL_TOKEN`. Фикс: `return bool(expected and provided and hmac.compare_digest(provided, expected))`.

suggestion: docs/deploy-amsterdam/PLAN.md:311 — smoke login использует `password=PASS`, а реальный пароль генерируется в `.env`. Фикс: перед тестом читать `DASH_PASSWORD=$(grep '^DASHBOARD_PASSWORD=' /opt/orchestra/.env | cut -d= -f2-)` и использовать его.

suggestion: docs/deploy-amsterdam/PLAN.md:315 — при `DASHBOARD_COOKIE_SECURE=1` cookie smoke через `http://127.0.0.1:8888` может не round-trip как в браузере/клиенте. Фикс: либо гонять cookie smoke после SSL через `https://orchestra.zahoron.ru`, либо временно ставить `DASHBOARD_COOKIE_SECURE=0` до certbot и сразу вернуть `1`.

suggestion: docs/deploy-amsterdam/PLAN.md:318 — `/api/events` в `app/main.py` нет; живой SSE endpoint сейчас `/api/sessions/{name}/stream?scope=...`. Фикс: создать тестового worker/orchestrator и проверять его stream, либо убрать этот smoke.

suggestion: docs/deploy-amsterdam/PLAN.md:135 — `uv sync` лучше явно выполнять от `orchestra`, чтобы `.venv` не стала root-owned при запуске отдельными блоками. Фикс: `sudo -u orchestra bash -lc 'cd /opt/orchestra && uv sync'`.

### Verdict
APPROVED for the deployment plan. Сам деплой всё ещё должен ждать фактической реализации Phase 0.5, push в `main`, и прохождения smoke tests.
