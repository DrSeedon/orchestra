# Report — прокси: .env единственный источник истины + #3/#4 фиксы

**Дата:** 2026-07-01
**Задача:** упростить управление прокси до `.env` + рестарт. Вырезать DB/hot-switch/cache. + #3 direct id, #4 zombie backoff.

---

## Что сделано

### #3 — Direct id fix (commit 19176e3)
`_parse_proxy_list()` форсит `id="direct"` когда `url=="direct"`. Раньше id генерился из имени → `direct-(vpn/соту)` (кириллица+скобки) → `POST /api/proxy/select/direct` 404'ил. Имя в `.env` упрощено до `Direct`.

### #4 — Zombie backoff + health-gate (commit 5fec40a)
`ssh_tunnel.py _tunnel_loop`:
- TCP health-gate `_port_open(host, 22, 2s)` перед спавном ssh — не долбиться в недоступный VPS.
- Exponential backoff 5→300с (`BACKOFF_MAX`) вместо фиксированных 5с.
- Reset backoff при uptime >60с (`HEALTHY_UPTIME`) — здоровый туннель.
- Устраняет бесконечный спам мёртвых VPS (timeweb/ezhik: `kex_exchange_identification: Connection reset` каждые 10с в логах).

### Основной рефактор — .env single source (commit 916047b)
**Root cause рассинхрона (докопался):** DB `kv.active_proxy` побеждал `.env` (`load_saved_proxy` перезаписывал `os.environ` при старте). Живые CLI-агенты держали разный прокси — `backend_claude._make_client()` снимает `os.environ["HTTPS_PROXY"]` в момент `connect()` в персистентный клиент.

**Вырезано:**
- `proxy_manager.py` → read-only: удалены `load_saved_proxy`, `select_proxy`, `refresh_loop`, `_cache`/`CACHE_TTL`, `_active_id` state. Осталось `list_proxies` (active из `os.environ`) + `check_all` (on-demand). −107 строк net.
- `routes/proxy.py` → удалён `POST /api/proxy/select`.
- `main.py` → убраны `load_saved_proxy()` + `refresh_loop` task.
- `app.js` → убрана select-кнопка + handler.
- DB → `DELETE kv active_proxy` (миграция не тронута).
- Codex-враппер → добавлен `HTTP_PROXY` (websocket падал без него).
- CLAUDE.md → секция «🔌 ПРОКСИ».

---

## Файлы

| Файл | Изменение |
|------|-----------|
| `app/proxy_manager.py` | −107 net (read-only) |
| `app/ssh_tunnel.py` | +30 (#4 backoff+gate), +#3 в парсере |
| `app/routes/proxy.py` | −20 (select endpoint) |
| `app/main.py` | −4 (load_saved+refresh) |
| `app/static/js/app.js` | −11 (select btn+handler) |
| `tests/route_surface_snapshot.json` | −6 (select route) |
| `tests/test_proxy.py` | +82 (новый, 6 тестов) |
| `CLAUDE.md` | +секция прокси |
| `~/.local/bin/codex` | +HTTP_PROXY |

---

## Тесты
- `tests/test_proxy.py` — 6 новых, все зелёные: direct id стабилен, active из env, no-mutation-methods удалены, port probe (open/closed), health-gate блокирует dead VPS спавн.
- Полный релевантный набор: **48 passed**. 2 fail (`test_route_surface_snapshot`, `test_api::test_list_empty`) — **пре-экзистинг** на base (env: auth-mode + `/workspace` sandbox mkdir; проверено `git stash`).

## Codex review
⚠️ **Output tool не записал файл** (recurring flakiness — reported "done" но файла нет ни в worktree, ни в main repo). Первый прогон вообще упал (websocket refused — Codex-враппер ходил без HTTP_PROXY, теперь починено).

**Self-review вместо** (все точки выверены grep + import-test):
1. Dangling refs: `MCP_BASE_ENV`/`kv_get`/`kv_set`/`time` удалены из proxy_manager. `MCP_BASE_ENV` жив в runtime_env+manager (не осиротел).
2. `_active_id` из `os.environ["HTTPS_PROXY"]` — edge HTTP_PROXY без HTTPS покрыт (`or` fallback), в .env оба ставятся вместе.
3. `select` endpoint — звался ТОЛЬКО из frontend. Удалён вместе.
4. proxy_manager singleton потерял `_active_id`/`_cache` state — ок для read-only.
5. `app.main` + `routes.proxy` импортятся, старт-путь чист.

---

## Breaking changes
- `POST /api/proxy/select` удалён — переключение прокси только через .env+рестарт.
- Прокси НЕ восстанавливается из DB при старте — берётся из .env (load_dotenv). Если .env HTTPS_PROXY пуст → Direct.

## Осталось юзеру (root/ручное)
1. Установить NM hook (из прошлой итерации): `sudo cp scripts/99-orchestra-proxy /etc/NetworkManager/dispatcher.d/ && sudo chmod 755 ...`
2. Прибить legacy root-zombie: `sudo pkill -f "ssh -N -L 12338:"`.
3. Fornex squid (:3128) лёг — поднять или оставить fallback.

## 📝 RULE (предложен, ждёт approval)
When источник конфига неоднозначен (.env vs DB) → документировать ЯВНО кто побеждает, не оставлять юзера гадать почему правка .env не действует. → добавлено в CLAUDE.md секцию «🔌 ПРОКСИ».
