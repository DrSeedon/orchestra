# Plan — вырезать hot-switch/DB, .env = единственный источник истины

**Дата:** 2026-07-01
**Требование:** прокси управляется ТОЛЬКО через `.env` HTTPS_PROXY + рестарт. Нет DB, нет hot-switch, нет cache/refresh. + #4 backoff/health-gate (багфикс зомби).

---

## Источник истины (после рефактора)
```
.env HTTPS_PROXY  →  systemd EnvironmentFile  →  os.environ (load_dotenv в lifespan)
                                                    ├→ Orchestra process
                                                    ├→ CLI агенты (backend_claude._make_client снимает os.environ)
                                                    └→ MCP subprocess (runtime_env.MCP_BASE_ENV снимает os.environ при импорте)
Сменить прокси: правка .env → sudo systemctl restart orchestra. Всё.
```
Ничего не мутирует `os.environ` в рантайме → рассинхрон невозможен by design.

---

## ЧЕКЛИСТ УДАЛЕНИЯ

### 1. `app/proxy_manager.py` — вырезать всю мутацию/DB/cache
Оставить: чтение `PROXY_LIST` из .env + on-demand `check` (проверка живости для дашборда). Read-only.
- ❌ `load_saved_proxy()` — удалить (читала kv.active_proxy, мутировала os.environ)
- ❌ `select_proxy()` — удалить (писала kv, мутировала os.environ + MCP_BASE_ENV)
- ❌ `refresh_loop()` — удалить (фоновый рефреш)
- ❌ `_cache`, `CACHE_TTL`, `_ts` штампы, stale-drop в `list_proxies` — удалить кеш целиком. `check`/`check_all` возвращают результат напрямую, дашборд дёргает on-demand
- ❌ `_active_id`, `_get_active_id()`, `load_saved_proxy` — удалить (нет «активного» состояния)
- ✅ `_parse_proxy_list()` — оставить (читает .env)
- ✅ `check_proxy()` / `_do_check()` / `check_all()` — оставить, но без записи в `_cache` (возвращать напрямую)
- ✅ `list_proxies()` — оставить, но БЕЗ `active` флага и БЕЗ кеша: просто список из .env. «Активный» = тот что в HTTPS_PROXY (можно пометить сравнением с `os.environ["HTTPS_PROXY"]`, read-only, для индикатора)
- Импорты `kv_get/kv_set`, `MCP_BASE_ENV`, `time`, `kv_set` — убрать осиротевшие

**Альтернатива (проще, обсудить):** оставить `proxy_manager` как есть по структуре, но урезать до 2 методов: `list_proxies()` (read .env + пометить активный из os.environ) + `check_all()` (on-demand живость). Файл ~60 строк вместо 207. **Выбираю этот вариант** — proxy_manager нужен дашборду для списка+check, целиком выпиливать = больше правок в routes/frontend.

### 2. `app/routes/proxy.py`
- ❌ `POST /api/proxy/select/{proxy_id}` — удалить endpoint целиком (вместе с interrupt-логикой живых агентов)
- ✅ `GET /api/proxy/list` — оставить (read-only список)
- ✅ `POST /api/proxy/check/{proxy_id}` — оставить (on-demand проверка)
- ✅ `GET /api/tunnel/status` — оставить

### 3. `app/main.py` (lifespan)
- ❌ строка 25 `proxy_manager.load_saved_proxy()` — удалить
- ❌ строка 57 `proxy_refresh_task = asyncio.create_task(proxy_manager.refresh_loop())` + cancel в shutdown — удалить
- ✅ `load_dotenv()` уже грузит .env → os.environ. Это и есть источник

### 4. `app/db.py` (kv)
- Код к `active_proxy` не обращается после удаления из proxy_manager → kv-таблица остаётся (мёртвая колонка, миграцию НЕ трогаем per требование). Разово почистить строку: `DELETE FROM kv WHERE key='active_proxy'` (или оставить — код её не читает)

### 5. `app/ssh_tunnel.py` — #4 багфикс (backoff + health-gate)
- ✅ `_port_open(host, port, timeout)` — TCP health-probe (УЖЕ написан в WIP)
- ✅ exponential backoff 5→300с в `_tunnel_loop` (УЖЕ написан в WIP)
- ✅ health-gate перед спавном ssh (УЖЕ написан, НО баг — см. ниже)
- ⚠️ **БАГ в текущем WIP**: тест показал health-gate НЕ заблокировал спавн к unroutable `10.255.255.1` (1 ssh проспавнился). Причина: `open_connection` к blackhole-IP не фейлится быстро (SYN без RST висит до сетевого таймаута, не до нашего `HEALTH_TIMEOUT=2`). Реально `wait_for(timeout=2)` ДОЛЖЕН отменить через 2с → вернуть False. Надо перепроверить: возможно тест словил race (loop успел войти в spawn до первого probe). Исправление: probe СТРОГО до spawn в начале итерации (уже так), + увеличить проверку в тесте (ждать >HEALTH_TIMEOUT). Разберусь при реализации, тест дам корректный.

### 6. `scripts/check-proxies.sh`
- Оставить как ДИАГНОСТИКУ. Убрать автопереключение через API (его и не было — он писал в .env через sed). Оставить sed .env + подсказку «рестартни orchestra». Это ок — .env источник истины, sed в .env легитимен.
- Убрать переключение Codex/TG? Нет — оставить (它們 тоже читают .env-подобные враппера). Не трогаю сверх нужного.

### 7. Frontend `app/static/js/app.js` (координирую с frontend-opus ИЛИ сам — мелко)
- ❌ `.proxy-select-btn` кнопка (строка 4896) + её handler (4911-4920) — удалить. Переключение только через .env
- ✅ `.proxy-check-btn` (Check живости) — оставить
- ✅ `loadProxyList` — оставить (список + индикатор активного)
- ✅ `#proxy-check-all` — оставить
- Индикатор «активный» = сравнение url с текущим HTTPS_PROXY (бэк отдаёт флаг). Строки 4921-4925 оставить

### 8. `CLAUDE.md` — задокументировать источник истины
Добавить секцию:
```
## 🔌 ПРОКСИ (единственный источник истины)
- **`.env` HTTPS_PROXY = ЕДИНСТВЕННЫЙ источник.** Нет DB, нет hot-switch, нет кеша
- Сменить прокси: правка `HTTPS_PROXY` в .env → `sudo systemctl restart orchestra`
- systemd EnvironmentFile → os.environ → наследуют все (Orchestra, CLI агенты, MCP)
- Дашборд: только индикатор + Check (проверить живость). Кнопки «выбрать» НЕТ
- `scripts/check-proxies.sh` — диагностика, подсказывает живой прокси (вписывает в .env, но рестарт — руками)
```

---

## Что НЕ трогаем
- DB миграции (мёртвая kv-колонка пусть висит)
- SSH туннели по сути (только #4 багфикс)
- backend_claude._make_client (снимает os.environ — правильно, .env источник)
- runtime_env.MCP_BASE_ENV (снимает os.environ при импорте — правильно)
- Codex/TG враппера

---

## Риски / edge cases
1. **`list_proxies` без `active` флага** — фронт (4921) ищет `p.active`. Надо либо оставить `active` (вычислять из os.environ, read-only), либо поправить фронт. Оставлю `active` (read-only вычисление) → фронт не трогать сверх удаления кнопки.
2. **`load_saved_proxy` удаление** — сейчас восстанавливал прокси при старте из DB. После удаления прокси берётся ТОЛЬКО из .env (load_dotenv). Если .env HTTPS_PROXY пуст → нет прокси (Direct). Это корректное новое поведение
3. **kv.active_proxy=fornex-nl в DB** — после удаления кода не читается. Оставить или DELETE — не влияет. Сделаю DELETE для чистоты
4. **#4 health-gate race** — разобраться почему тест показал спавн. Дать корректный тест (мёртвый VPS → 0 ssh за >HEALTH_TIMEOUT)

---

## Порядок реализации
1. #4 багфикс ssh_tunnel (backoff + health-gate, починить тест) — уже WIP
2. Вырезать proxy_manager до read-only (list + check)
3. Удалить select endpoint + main.py refresh_loop/load_saved_proxy
4. Фронт: убрать select-кнопку
5. CLAUDE.md секция
6. kv DELETE active_proxy
7. Тесты: старт, list из .env, select-endpoint 404, #4 зомби

Коммиты раздельные: `#4 backoff`, `simplify: .env single source`.

---

## Codex review — НЕ УДАЛСЯ (proxy churn)
Codex exec упал: `websocket connection refused (chatgpt.com)`. Причина — Codex-враппер ходит через мёртвый прокси (`:12340` Ёжик / `:12342` Fornex squid down). Ирония: та самая проблема которую чиним ломает и Codex. Живой прокси сейчас только `:12343` Contabo (405), но Codex-враппер на него не настроен.

### Self-review вместо Codex (все точки проверены grep'ом):
1. **Импорты не сломаются**: `proxy_manager` юзают только `main.py` (2 строки — удаляю), `routes/proxy.py` (select — удаляю, list/check — оставляю). `runtime_env`/`backend_claude` берут прокси из `os.environ` напрямую, `proxy_manager` не импортят. ✅
2. **select endpoint** — зовётся ТОЛЬКО из frontend (app.js:4916). Нет в tests/mcp_stdio/scripts. Безопасно удалить. ✅
3. **`p.active`** — 4 использования (highlight/badge/select-btn/indicator). Оставляю `active` вычисляемым read-only из `os.environ["HTTPS_PROXY"]` → фронт трогаю МИНИМАЛЬНО (только select-кнопку). ✅
4. **load_saved_proxy удаление** — прокси берётся из .env через `load_dotenv()` в lifespan (строка 22, ДО остального). Достаточно. Пустой HTTPS_PROXY → Direct (корректно). ✅
5. **#4 health-gate — БАГА НЕТ** (перепроверил чисто): `open_connection` к blackhole `10.255.255.1:22` таймаутит РОВНО за 2с (`wait_for` отменяет). Тест на чистом окружении: dead VPS → **0 ssh спавнов**. Прошлый «1 ssh» = stale-процесс от предыдущего прогона теста засорял `pgrep`, не баг гейта. `_port_open` верен: open→True, closed→False, blackhole→False(2s). ✅

Retry Codex — когда починим прокси (после этого же рефактора). Не блокер: deletion-план, все зависимости выверены grep'ом.
