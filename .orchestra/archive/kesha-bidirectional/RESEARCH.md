# Двусторонняя связь Kesha ↔ Parsing-orchestrator — ресёрч

> Дата: 2026-05-30 · Автор: kesha-bidirectional-research (worker)
> Статус: РЕСЁРЧ (не имплементация)

## TL;DR

**Корень проблемы:** `send_message(to, ...)` доставляет сообщение, только если получатель
зарегистрирован в **in-memory словаре** `SessionManager.sessions` на сервере Orchestra
(147.45.101.84 / localhost:8888). Kesha — это отдельная Claude CLI-сессия на **чужом VPS**
(89.127.206.225), которую Orchestra-сервер никогда не спавнил, поэтому в `manager.sessions`
её нет. Исходящие сообщения Kesha работают (он бьёт по HTTP API через SSH-туннель), а
входящие — нет: `/api/sessions/kesha/send` → `manager.get_by_name("kesha")` → `None` → **404**.

**Рекомендация (минимальное изменение, максимальный эффект):**
**Вариант B' — «remote agent» как лёгкий тип сессии в Orchestra.**
Регистрируем Kesha как сессию с `backend = RemoteBackend`, у которого `send()` не пишет
в локальный SDK-клиент, а делает HTTP-POST на webhook Kesha-VPS (через тот же SSH-туннель,
только в обратную сторону, либо через уже существующий reverse-port 18080). Это переиспользует
весь механизм `send_to_session` / `list_agents` / inbox без переписывания транспорта.

---

## 1. Как работает send_message в Orchestra (реальный код)

### 1.1 MCP-клиент (`app/mcp_stdio.py`)

`send_message` — это просто HTTP-обёртка. Никакой магии «доставки» в самом MCP нет:

```python
# app/mcp_stdio.py:142
@mcp.tool()
async def send_message(to: str, message: str) -> str:
    result = await _api("POST", f"/api/sessions/{to}/send", json={
        "message": message, "sender": WORKER_NAME or ROLE, "scope": SCOPE,
    })
    if isinstance(result, dict) and result.get("error"):
        return f"Send failed: {result['error']}"
    return f"Message sent to '{to}'"
```

`_api` (`mcp_stdio.py:35`) бьёт по `ORCHESTRA_URL` (env, дефолт `http://127.0.0.1:8888`)
с `Authorization: Bearer <INTERNAL_TOKEN>`. То есть **любой** процесс с правильным
`ORCHESTRA_URL` + `INTERNAL_TOKEN` может вызвать API. Kesha именно так и шлёт наружу.

Env, которым параметризуется MCP-клиент (`mcp_stdio.py:20-24`):
- `ORCHESTRA_URL` — куда стучаться
- `ORCHESTRA_SCOPE` — scope агента
- `ORCHESTRA_ROLE` — роль (дефолт `orchestrator`)
- `WORKER_NAME` — имя агента (дефолт `worker`)
- `INTERNAL_TOKEN` — auth

### 1.2 HTTP-эндпоинт `/api/sessions/{name}/send` (`app/main.py:493`)

```python
@app.post("/api/sessions/{name}/send")
async def send_message(name: str, req: SendRequest):
    sess = manager.get(req.scope, name) if req.scope else manager.get_by_name(name)
    if not sess:
        return JSONResponse({"error": f"Session '{name}' not found"}, status_code=404)
    await manager.send_to_session(sess, req.message, sender=req.sender)
    return {"ok": True}
```

**Вот здесь ломается всё для Kesha.** Поиск получателя:

```python
# app/manager.py:35
def get_by_name(self, name: str) -> Session | None:
    for s in self.sessions.values():
        if s.name == name:
            return s
    return None
```

`self.sessions` — это **in-memory dict процесса Orchestra-сервера** (`manager.py:24`).
Заполняется только когда сервер сам спавнит/резюмит сессию (`spawn`, `auto_resume_orchestrators`).
Kesha там никогда не появляется → `get_by_name("kesha")` = `None` → 404.

### 1.3 Доставка — `send_to_session` (`app/manager.py:301`)

```python
async def send_to_session(self, sess, message, sender=None):
    display = f"[from {sender}] {message}" if sender else message
    save_inbox(sess.id, message, sender=sender)      # persist
    save_log(sess.id, "user_message", display)       # log
    await sess.backend.send(display)                 # mid-turn inject в SDK-клиент
    update_session_status(sess.id, "running")
    await broadcast_sessions_safe()
    return True
```

Ключевое: доставка идёт через **`sess.backend.send()`** — это инъекция в живой
`ClaudeSDKClient`, который держит локальный процесс Claude CLI. Этот механизм
**физически не дотянется до процесса на другом VPS** — backend знает только про локальный stdin.

### 1.4 Где регистрируются сессии

- **Spawn** (`manager.py:61`): создаёт `Session`, кладёт в `self.sessions[key]`,
  стартует `ClaudeBackend`/`CodexBackend`, пишет в БД.
- **Auto-resume** (`manager.py:315`): при старте сервера поднимает из БД **только**
  оркестраторы (`role in ("orchestrator","sub-orchestrator")`), воркеры эфемерны.
- `key = f"{scope}::{name}"` (`manager.py:29`).

### 1.5 list_agents / list_orchestrators

- `list_agents` → `GET /api/sessions?scope=` → `manager.list(scope)` (фильтр по scope).
- `list_orchestrators` (`main.py:1016`) → `manager.list_all()` отфильтрованный по
  `role in ("orchestrator","sub-orchestrator")` — **across all scopes**.

Оба читают тот же `self.sessions`. Значит: **чтобы Kesha был виден и достижим, его
Session-объект обязан жить в `manager.sessions` на сервере.** Это инвариант всей системы.

---

## 2. Как Kesha подключён к Orchestra (реконструкция)

Код Orchestra напрямую про Kesha ничего не знает (grep по `kesha` — пусто). Из архитектуры
и `ssh_tunnel.py` собирается картина:

### 2.1 SSH-туннель (`app/ssh_tunnel.py`)

Orchestra-сервер при старте (`main.py:44`) поднимает **исходящий** SSH-туннель:

```python
# ssh_tunnel.py:38 — local forward
ssh -N -L {local_port}:127.0.0.1:{remote_port} -i {key} root@{host}
```

Env: `SSH_TUNNEL_HOST`, `SSH_TUNNEL_KEY`, `SSH_TUNNEL_LOCAL_PORT` (12338),
`SSH_TUNNEL_REMOTE_PORT` (18080).

Это `-L` (local forward): `localhost:12338` на Orchestra-сервере → `127.0.0.1:18080`
на удалённом хосте. То есть **сервер Orchestra может достучаться до сервиса на :18080
удалённого VPS**. Это потенциальный готовый канал «сервер → Kesha-VPS» (см. Вариант B').

> ⚠️ Точные значения env не прочитаны (`.env` в этот заход не отдался тулзой). Нужно
> сверить: `SSH_TUNNEL_HOST` = 89.127.206.225? и что слушает на :18080 на той стороне.

### 2.2 Как Kesha шлёт наружу (работает сейчас)

Kesha = Claude CLI на 89.127.206.225 с настроенным Orchestra MCP. Чтобы его
`send_message` доходил до сервера, у Kesha в env MCP-сервера прописан `ORCHESTRA_URL`,
указывающий на Orchestra-сервер (либо через свой SSH-туннель Kesha→сервер:8888, либо
прямой доступ к 147.45.101.84:8888 + `INTERNAL_TOKEN`). Эндпоинты read-only / send
работают, потому что не требуют, чтобы **отправитель** был зарегистрирован — только
получатель (`Parsing-orchestrator`, который реально живёт в `manager.sessions`).

### 2.3 Регистрируется ли Kesha автоматически при старте MCP?

**Нет.** Запуск `python -m app.mcp_stdio` (`mcp_stdio.py:622`) поднимает только MCP-сервер
(набор tools). Он **не** создаёт Session и **не** дёргает `/api/sessions`. Регистрация
происходит исключительно через `manager.spawn` на стороне сервера. Поэтому Kesha —
«агент-призрак»: умеет звать API, но сам в реестре отсутствует.

---

## 3. Варианты решения

### Вариант A — Kesha как orchestrator (через свой Orchestra-инстанс)

**Идея:** на Kesha-VPS поднять отдельный Orchestra-сервер; Kesha регистрируется там
оркестратором; связь между двумя серверами — через `list_orchestrators` cross-project.

- ➖ `list_orchestrators` читает **локальный** `manager.sessions` одного процесса. Два
  разных сервера = два разных реестра, они друг друга не видят. Cross-project в коде —
  это «across scopes внутри одного процесса», **не** «across machines».
- ➖ Чтобы связать два сервера, всё равно нужен сетевой мост (тот же webhook/queue) —
  то есть это Вариант B/C сверху, плюс лишний сервер.
- ➖ Дорого, дублирование инфраструктуры.
- **Вердикт: нет.** Самый дорогой и не решает корень.

### Вариант B — Webhook/callback (сервер → Kesha-VPS)

**Идея:** при `send_to_session(kesha, ...)` сервер делает HTTP-POST на endpoint,
который слушает на Kesha-VPS; Kesha инъектит сообщение себе в текущий turn.

- ➕ Прямой, понятный, односторонний канал ровно для недостающего направления (вход).
- ➕ SSH-туннель `-L ...:18080` уже даёт серверу доступ к `:18080` на той стороне —
  можно POST'ить на `http://127.0.0.1:12338/inject` (= remote :18080), без открытия портов наружу.
- ➖ Нужен HTTP-listener на стороне Kesha + способ инъекции в его Claude-сессию
  (Kesha — голый Claude CLI, у него нет нашего backend.send; нужен мини-сервис, который
  получит webhook и сделает `claude --resume`/inject в его сессию).
- ➖ Сообщение должно ещё «разбудить» turn Kesha — это зависит от того, как Kesha запущен
  (если как Orchestra-воркер на том VPS — есть свой manager; если как чистый CLI — сложнее).

### Вариант B' — Remote agent как тип сессии (РЕКОМЕНДУЕМЫЙ) ⭐

Уточнённый B: вместо «костыля снаружи» — **встроить Kesha в реестр сервера как Session
с remote-backend**, чтобы переиспользовать `send_to_session`, inbox, `list_agents`,
дашборд.

**Что нужно:**
1. Новый backend `RemoteBackend(sess)` (рядом с `ClaudeBackend`/`CodexBackend`), у которого
   `send(message)` делает HTTP-POST на webhook Kesha-VPS (через `127.0.0.1:12338` = туннель
   на remote :18080). `start()` — no-op. Остальные методы (`interrupt`, `stop`) — no-op/HTTP.
2. Способ зарегистрировать remote-сессию: либо новый эндпоинт `POST /api/sessions/remote`
   (создаёт `Session(role="orchestrator", ...)`, `sess.backend = RemoteBackend(sess)`,
   кладёт в `manager.sessions`, сохраняет в БД с пометкой `kind="remote"`), либо флаг в spawn.
3. В `auto_resume_orchestrators` (или отдельной ветке) поднимать remote-сессии из БД c
   `RemoteBackend` вместо `ClaudeBackend`.
4. На стороне Kesha — лёгкий HTTP-listener на :18080, который принимает `{message, sender}`
   и инъектит Kesha (механизм инъекции зависит от того, как там запущен Claude — см. вопрос 2.1).

**Плюсы:** минимальная хирургия в ядре (`backend_kind` уже выбирается по модели в
`manager.spawn:71` — добавить третью ветку тривиально); Kesha сразу виден в `list_agents`,
дашборде, получает inbox/логи; двусторонняя связь «из коробки» через существующий
`send_to_session`.
**Минусы:** нужен listener на Kesha-VPS + договорённость о payload/инъекции.

### Вариант C — Shared message queue (Redis / общая SQLite)

**Идея:** общая очередь; обе стороны polling/pubsub.

- ➖ Orchestra использует локальную SQLite (`app/db.py`), не сетевую. Сделать её общей
  через сеть — отдельная инфраструктура (Redis/Postgres), переписывание db-слоя.
- ➖ Polling добавляет латентность и нагрузку; pub/sub = новый брокер на VPS.
- ➖ Overkill для связи **двух** агентов. Очередь оправдана при N>>2 распределённых агентах.
- **Вердикт: на будущее (если будет рой remote-агентов), не сейчас.**

### Вариант D — TG bridge relay (через Telegram как транспорт)

**Идея:** оба бота в одном TG-чате/топике; сообщения ходят через TG.

- ➕ `tg_bridge.py` уже есть и двунаправленный (topics, voice). Транспорт «бесплатный».
- ➕ Возможно, частично уже работает (если Kesha и оркестратор сидят в одном чате).
- ➖ TG — для human-in-the-loop, не для agent-to-agent: парсинг «кто кому» хрупкий,
  есть rate limits, сообщения мешаются с человеческими.
- ➖ Семантика `send_message(to="kesha")` ≠ «кинуть в TG-чат». Маппинг agent→topic нужно
  городить, и это всё равно не делает Kesha видимым в `list_agents`.
- **Вердикт: быстрый хак для демо, плохой как постоянное решение.**

---

## 4. Архитектура Orchestra в multi-VPS контексте

- Orchestra — **один процесс на одном сервере**, всё состояние агентов в его
  in-memory `manager.sessions` + локальной SQLite. Понятия «remote agent» в ядре **нет**.
- `list_orchestrators` «cross-project» = across scopes **внутри одного процесса**, не across machines.
- SSH-туннель (`-L`) уже создаёт защищённый канал «сервер → удалённый :18080». Это
  фундамент для Варианта B/B': серверу не нужно открывать порты Kesha наружу — он ходит
  по туннелю на `localhost:12338`.
- Чтобы Kesha стал полноправным двусторонним участником, **его Session обязан существовать
  в `manager.sessions`** (иначе невидим и недостижим). Единственный вопрос — каким backend'ом
  доставлять `send()` на чужую машину. Ответ: remote-backend поверх существующего туннеля.

---

## 5. Рекомендация

| Критерий | A (свой Orchestra) | B' (remote agent) ⭐ | C (queue) | D (TG relay) |
|---|---|---|---|---|
| Простота внедрения | низкая | **средняя** | низкая | высокая (хак) |
| Архитектурная чистота | плохая | **хорошая** | средняя | плохая |
| Виден в list_agents/дашборде | нет | **да** | нет | нет |
| Переиспользует ядро | нет | **да** | нет | частично |
| Новая инфраструктура | целый сервер | listener на VPS | брокер | — |

**Делать: Вариант B' (remote agent).**

- **Самый правильный архитектурно:** Kesha становится first-class сессией, всё ядро
  (`send_to_session`, inbox, logs, дашборд, `list_agents`) работает без переписывания.
- **Минимальное изменение:** новый `RemoteBackend` + одна ветка в `manager.spawn`
  (`backend_kind`) + эндпоинт регистрации + поднятие в `auto_resume`. Транспорт —
  уже существующий SSH-туннель.
- **Цена (оценка сложности):**
  - Ядро Orchestra: ~0.5–1 день (RemoteBackend + регистрация + resume + БД-поле `kind`).
  - Listener на Kesha-VPS + инъекция в его Claude-сессию: ~0.5–1 день
    (зависит от ответа на открытые вопросы ниже).
  - **Итого ~1.5–2 дня**, основной риск — механизм инъекции на стороне Kesha.

**Быстрый временный мост, пока B' не готов:** Вариант D (общий TG-топик) — если Александру
нужно «вчера». Но это демо-костыль, не финал.

---

## 6. Открытые вопросы (нужно подтвердить перед имплементацией)

1. **Как именно запущен Kesha на 89.127.206.225?** Чистый `claude` CLI в screen/tmux,
   или это Orchestra-воркер на втором инстансе? От этого зависит механизм инъекции
   входящего сообщения (B'/B шаг 4).
2. **`.env` Orchestra-сервера:** `SSH_TUNNEL_HOST` = 89.127.206.225? Что слушает на
   remote :18080? Туннель `-L` сейчас живой? (в этот заход `.env` не прочитался — тулза
   вернула пусто; перечитать).
3. **`INTERNAL_TOKEN` у Kesha** — какой `ORCHESTRA_URL` прописан в его MCP env, как
   именно его исходящие доходят (свой обратный туннель Kesha→сервер:8888 или прямой IP)?
4. **Куда инъектить входящее** — есть ли на Kesha-VPS уже HTTP-listener, или поднимать с нуля.

---

## 7. Карта кода (для имплементатора)

| Что | Файл:строка |
|---|---|
| MCP `send_message` (HTTP-обёртка) | `app/mcp_stdio.py:142` |
| MCP env (URL/scope/role/name/token) | `app/mcp_stdio.py:20`, `app/backend_claude.py:22` |
| Эндпоинт `/api/sessions/{name}/send` | `app/main.py:493` |
| Поиск получателя `get_by_name` (← тут 404) | `app/manager.py:35` |
| Доставка `send_to_session` (backend.send) | `app/manager.py:301` |
| Реестр сессий `self.sessions` (in-memory) | `app/manager.py:24` |
| Spawn + выбор backend по модели (← добавить remote) | `app/manager.py:61`, `:71` |
| Auto-resume оркестраторов (← поднимать remote) | `app/manager.py:315` |
| `list_orchestrators` (across scopes, 1 процесс) | `app/main.py:1016` |
| SSH-туннель `-L` (канал сервер→remote:18080) | `app/ssh_tunnel.py:38` |
| Backend MCP-config / env инъекция | `app/backend_claude.py:22` |
