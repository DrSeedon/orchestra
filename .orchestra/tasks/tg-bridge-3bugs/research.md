# TG Bridge — 3 бага: RESEARCH

Дата: 2026-06-10. Файлы: `app/tg_bridge.py`, `app/diff_image.py`, `app/mcp_stdio.py`, `app/main.py`.

## Архитектура (как сейчас)

- `stream_logs(orch_name, thread_id)` (tg_bridge.py:976) — поллит `get_logs` из SQLite каждые 2-5 сек, по типу лога (`text`/`tool`/`tool_result`/`status`/`user_message`/`error`) шлёт в TG.
- Формат tool-лога (backend_claude.py:246-251): `"{block.name}: {json indented}"`, напр. `Edit: {\n  "file_path": ...}`. Парсинг через первый `:`.
- Отправка текста: `_tg_send_safe` (tg_bridge.py:492) с rate-limit (1 msg/сек) + flood-handling.
- Diff images: `_send_diff_image` (880) → `app.diff_image.render_edit/write` → `_send_png_to_tg` (862).
- Result images: `_send_result_image` (903) для Read/Grep/Bash.
- `send_file_to_tg` (691) — MCP send_file → endpoint `/api/tg/send_file` (main.py:1401) → топик через `_find_orch_for_scope(scope)` (651).

---

## БАГ 1: текст агента не доставляется → ROOT CAUSE = FLOOD CONTROL

**Симптом**: text-логи в БД (132991, 132993), но в TG только `turn ended`, текста нет.

**Не md_convert** (как предполагалось в задаче). Проверено: цепочка `md_convert`/`_split_message` на таблицах не крашит критично — есть except-fallback (1052-1054).

**Реальная причина** — журнал прода завален:
```
TG send failed: ... Flood control exceeded on method 'SendMessage' ... Retry in 40 seconds
TG flood: pausing 41s
result image send failed (Read/Grep/Bash): ... SendPhoto ... Retry in 37s
TG edit failed: ... EditMessageText ... Retry in 41s
Topic status update failed: ... EditForumTopic ...
```

Бот превышает лимит Telegram (~20 msg/min в группу). Источник флуда — на КАЖДЫЙ tool шлётся:
1. expandable-сообщение (`_send_expandable`)
2. edit с результатом (`_edit_tool_with_result`)
3. diff/result PNG (`SendPhoto`) — для Edit/Write/Read/Grep/Bash
4. mirror-копия
5. topic status edit (`EditForumTopic`)

Когда приходит `text` (important=True): `_tg_send_safe` ловит `TelegramRetryAfter`, ждёт `retry_after+0.5`, делает ОДНУ повторную попытку (492:510-516). Если и она во флуде → `except Exception: pass` (515-516) → **текст теряется МОЛЧА**. `turn ended` (status) приходит позже, когда окно отпустило, потому доходит.

**Тихие except (теряют ошибки):**
- `_tg_send_safe` 515-516: `except: pass` после флуд-ретрая — потеря важного текста без лога
- `_stream_logs` text-ветка 1052-1054: `except Exception:` без логирования (и fallback тоже может молча упасть в `_tg_send_safe`)
- `_send_expandable` 460-463: вложенный except — ок, логирует warning

**Фикс**:
- `_tg_send_safe`: `logger.warning` при потере important-сообщения после флуд-ретрая (вместо `pass`)
- text-ветка 1052: `logger.warning` в except с превью текста
- Снизить флуд: result images (Read/Grep/Bash) — самый частый спам. Они НЕ критичны (это «красивости»). Опция — гейтить их отдельным env / убрать edit-spam. Минимальный фикс: логировать потери; рассмотреть отключение result-images по умолчанию (оставить только diff для Edit/Write).

---

## БАГ 2: diff images не показываются для Edit/Write → ROOT CAUSE = PIL не установлен в prod

**Симптом**: код есть, картинки не приходят; на report_bug картинка РАБОТАЕТ.

**Реальная причина** — журнал прода:
```
diff image send failed (Edit): No module named 'PIL'
diff image send failed (Write): No module named 'PIL'
result image send failed (Grep): No module named 'PIL'
```

- Сервис стартовал **12:22:20**, `pillow` появился в `.venv` только **14:25:18** (после `uv sync`, который сделали позже добавления в pyproject).
- `from app.diff_image import ...` сделан ЛЕНИВО внутри функции → каждый вызов падает с ImportError пока PIL нет на диске.
- Сейчас PIL установлен (11.3.0), цепочка `Edit JSON → render_edit_diff → PNG (2892 байт)` проверена локально — **работает идеально**.

**Почему report_bug-картинка работает**: идёт через ветку `user_message` (1018-1031) — `bot.send_photo` напрямую с готовым файлом, БЕЗ импорта `app.diff_image`/PIL. А diff/result images импортируют PIL → ImportError.

**Это деплой-проблема, не баг кода.** Текущий запущенный процесс ImportError не кеширует — после установки PIL (14:25) diff images должны заработать БЕЗ рестарта. Последняя ошибка 14:25:13 (до установки), дальше тишина.

**Фикс (устойчивость, чтобы баг не был тихим)**:
- Импортировать PIL/diff_image на старте бриджа (или в `_diff_images_enabled`) и при ImportError — `logger.warning` ОДИН раз + автоотключение diff images (флаг), чтобы не спамить ошибками и не молчать.
- Убедиться что `pillow` в deps (есть: `pillow>=10.0,<12.0`). Деплой = `uv sync` + рестарт (делает юзер).

---

## БАГ 3: send_file кидает в неправильный топик → ROOT CAUSE = sender игнорируется

**Симптом**: `send_file` отправляет файл не в топик вызвавшего агента.

**Реальная причина**:
- MCP `send_file` (mcp_stdio.py:322-328) передаёт `sender = WORKER_NAME or ROLE` и `scope = SCOPE`. **Имя вызывающего агента ДОСТУПНО** (`sender`).
- `send_file_to_tg` (tg_bridge.py:691, 703-704) выбирает топик через `_find_orch_for_scope(scope)` → `config["topics"][orch_name]`, **полностью игнорируя `sender`**.
- `_find_orch_for_scope` (651-664) всегда возвращает **top-level оркестратора** скоупа (`top_level or any_orch`), независимо от того кто вызвал.
- Топики создаются НЕ только для оркестраторов: `ensure_topics` (818-822) делает топик для агентов с `tg_topic=True` ИЛИ ролью orchestrator/sub-orchestrator. → у воркера/саб-оркестратора с `tg_topic=True` есть СВОЙ топик в `config["topics"][имя]`, но send_file всё равно шлёт в топик top-level.

Тест `test_worker_ignored` (test_tg_bridge.py:219) фиксирует текущее (багованное) поведение.

**Фикс**:
- В `send_file_to_tg`: сначала пробовать топик САМОГО `sender` — `config["topics"].get(sender)`. Если есть — слать туда. Иначе fallback на `_find_orch_for_scope(scope)` (для агентов без своего топика → в топик их оркестратора).
- Обновить/добавить тесты: sender со своим топиком → его топик; sender без топика → топик оркестратора скоупа.

---

## Риски / edge cases

- **Баг 1 фикс**: нельзя «чинить» флуд агрессивным ретраем — усугубит. Правильно: меньше слать (result images) + честно логировать потери. Отключение result-images по умолчанию — поведенческое изменение, согласовать с оркестратором.
- **Баг 2**: код-фикс косметический (устойчивость к ImportError). Главное — деплой (`uv sync`+рестарт делает юзер).
- **Баг 3**: `config["topics"]` может содержать sender напрямую → простой lookup. Edge: sender=None/ROLE без топика → fallback на scope. Mirror тоже завязан на orch_name — при отправке в топик воркера mirror может быть не настроен (ок, mirror опционален).

## Тесты
- `tests/test_tg_bridge.py` — есть покрытие `_find_orch_for_scope`, `_send_diff_image`, `_diff_images_enabled`, health-check restart.
- Запуск: `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/test_tg_bridge.py -x -q`
