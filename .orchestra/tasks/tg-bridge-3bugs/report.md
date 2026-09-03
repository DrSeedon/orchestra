# TG Bridge — 3 бага: REPORT

Дата: 2026-06-10. Все три бага найдены по логам прода (не угадайка), root cause подтверждён.

## Что сделано

### Баг 1 — текст агента терялся (root cause: FLOOD CONTROL, не md_convert)
Чат завален Telegram flood control (каждый tool слал 5 сообщений: expandable+edit+PNG+mirror+topic-status).
Когда приходил text агента (important), `_tg_send_safe` после флуд-ретрая делал `except: pass` →
текст терялся МОЛЧА. `turn ended` доходил позже.

**Фикс** (commit b032858):
- `_tg_send_safe`: `except Exception as e2` + `logger.warning` с превью текста вместо `pass`.
- После успешного флуд-ретрая обновляется `_last_send` (иначе rate-limiter сразу шлёт следующее → новый флуд) — по замечанию Codex.
- text-ветка `stream_logs`: `logger.warning` перед plain-fallback.
- Снижение флуда — см. баг 2 (result images OFF).

### Баг 2 — diff images не показывались (root cause: PIL не установлен в prod venv)
Лог прода: `diff image send failed (Edit): No module named 'PIL'`. pillow добавлен в pyproject,
но `uv sync` на проде сделали (14:25) ПОСЛЕ старта сервиса (12:22). report_bug-картинка работала —
она идёт через `bot.send_photo` напрямую, без импорта PIL.

**Фикс** (commit 94b419f):
- `_check_pil()` — проверяет `from PIL import Image, ImageDraw, ImageFont` один раз, кеширует,
  логирует ОДИН warning при отсутствии (вместо тихого спама ImportError на каждый Edit).
- `_diff_images_enabled()` и `_result_images_enabled()` гейтятся через `_check_pil()` → нет PIL = чисто выключено.
- `_check_pil()` вызывается в `start_bridge` для раннего warning в логах старта.
- **Деплой**: `pillow` в pyproject (`pillow>=10.0,<12.0`). Прод требует `uv sync` + рестарт (делает юзер).

### Баг 2b / decision 1 — result images OFF by default
Read/Grep/Bash images — главный источник флуда, некритичны.

**Фикс** (commit 94b419f):
- Новый env `TG_RESULT_IMAGES` (opt-in, default `false`), отдельно от `TG_DIFF_IMAGES` (default `true`).
- `_send_result_image` теперь гейтится `_result_images_enabled()`.
- `.env.example` обновлён.

### Баг 3 — send_file в неправильный топик (root cause: sender игнорировался)
`send_file_to_tg` резолвил топик только через `scope → _find_orch_for_scope → top-level orch`,
игнорируя доступный из MCP `sender`. Воркер/саб-орк со своим `tg_topic` → файл в чужой топик.

**Фикс** (commit 8742d31):
- Сначала топик самого `sender` (`topics.get(sender)`, проверка на truthy — по замечанию Codex,
  чтобы None/0/stale падали в fallback), иначе fallback на `_find_orch_for_scope(scope)`.

## Файлы изменены
- `app/tg_bridge.py` — +~40 строк (3 фикса)
- `.env.example` — +3 (TG_RESULT_IMAGES)
- `tests/test_tg_bridge.py` — +114 (TestResultImagesEnabled, TestCheckPil, TestSendFileRouting,
  test_false_when_pil_missing, фикстура сбрасывает _pil_available)

## Коммиты (3, по одному на фикс)
- `8742d31` #tg-bridge: send_file routes to caller's own topic, fallback to scope
- `b032858` #tg-bridge: log silent text losses under flood control
- `94b419f` #tg-bridge: PIL guard for images + result images opt-in (off by default)
- `743d2df` #tg-bridge: probe Pillow only when image feature is enabled (Codex suggestion)

## Тесты
- `tests/test_tg_bridge.py` — **37 passed** (было 25, +12 новых).
- Цепочка `Edit JSON → render_edit_diff → PNG` проверена вручную (2892 байта).
- **Полный сьют непригоден как gate**: на чистом main 105 failed / 417 passed (предсуществующая
  проблема изоляции тестов между модулями + playwright без браузера). Мои изменения: 423 passed
  (+6 новых tg_bridge тестов прошли); 3 «провала» tg_bridge в полном прогоне — ТОЛЬКО из-за
  загрязнения глобального состояния другими тестами (изолированно все 37 зелёные).

## Codex review
- План: APPROVED с правками (все применены — except as e2, _last_send, robust sender fallback, точный PIL import, cached-PIL тесты).
- Имплементация: **SHIP, no blocking findings**. Одна suggestion (log-noise): `_check_pil()` пробовал PIL
  до чтения флага → шум warning при отключённых TG/images. Применено (commit 743d2df): гейты
  short-circuit на env-флаге первыми, ранний startup-probe убран (ленивая проверка при первом image).
- Первый impl-review запустился из корневого репо (не worktree) → отревьюил чужой diff; перезапущен
  на чистом diff моих коммитов (`/tmp/tg-bridge-impl.diff`).

## Breaking changes
- **Result images теперь OFF по умолчанию** (поведенческое, согласовано оркестратором). Включить: `TG_RESULT_IMAGES=true`.
- Diff images (Edit/Write) — без изменений, остаются ON.

## Деплой-нота (для юзера)
Чтобы diff images заработали на проде: `uv sync` (поставит pillow) + рестарт orchestra.
Без рестарта новый код (PIL-guard, result OFF, send_file routing) не подхватится.

## Known tradeoff
- `_check_pil` кеширует результат: если PIL появится в рантайме после первого False — останется
  выключенным до рестарта. Приемлемо (PIL ставится при деплое + рестарт).
- Флуд-механику (`_TG_MIN_INTERVAL`/rate-limit) не переписывали — снизили объём (result OFF) +
  честное логирование потерь. Полный редизайн анти-флуда — отдельная задача если флуд останется.
