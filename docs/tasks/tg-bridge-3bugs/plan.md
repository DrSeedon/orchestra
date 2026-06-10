# TG Bridge — 3 бага: PLAN

Аппрув оркестратора (2026-06-10): result-images OFF by default (`TG_RESULT_IMAGES=false`),
logger.warning на каждый тихий except, PIL-check на старте с автоотключением, send_file → топик sender с fallback на scope.
Коммитить каждый фикс отдельно.

---

## Фикс 1: Флуд + тихие потери текста (БАГ 1) + result-images OFF (decision 1)

### 1a. result-images отдельный env-гейт (`app/tg_bridge.py`)
- Новая функция `_result_images_enabled()` рядом с `_diff_images_enabled()` (859):
  ```python
  def _result_images_enabled() -> bool:
      return os.getenv("TG_RESULT_IMAGES", "false").lower() in ("1", "true", "yes")
  ```
  (default OFF — инверсия логики diff: явно opt-in).
- `_send_result_image` (903-906): заменить проверку `if not _diff_images_enabled(): return`
  на `if not _result_images_enabled(): return`.

### 1b. logger.warning в тихих except (decision 2)
- `_tg_send_safe` (492): в флуд-ветке для `important=True` после неудачного ретрая
  `except Exception: pass` (515-516) → `logger.warning(f"TG send lost after flood retry (important): {e2}; text[:80]={text[:80]!r}")`.
- text-ветка `_stream_logs` (1052-1054): в `except Exception as e:` добавить
  `logger.warning(f"text md_convert/send failed, fallback plain: {e}")` перед fallback-отправкой.

### 1c. .env.example
- Добавить `# TG_RESULT_IMAGES=false` рядом с `# TG_DIFF_IMAGES=true` (строка ~68).

**Коммит**: `#tg-bridge: result images OFF by default + log silent text losses (flood)`

---

## Фикс 2: PIL health-check на старте + автоотключение (БАГ 2, decision 3)

### 2a. Модульный флаг + проверка (`app/tg_bridge.py`)
- Глобальный флаг рядом с config: `_pil_available: bool | None = None` (None = не проверяли).
- Функция:
  ```python
  def _check_pil() -> bool:
      global _pil_available
      if _pil_available is None:
          try:
              import PIL  # noqa
              _pil_available = True
          except Exception as e:
              _pil_available = False
              logger.warning(f"Pillow not installed — TG diff/result images disabled. Run `uv sync`. ({e})")
      return _pil_available
  ```
- `_diff_images_enabled()` и `_result_images_enabled()`: добавить `and _check_pil()` в условие
  (чтобы при отсутствии PIL обе фичи молча-без-спама выключались, warning один раз).
- В `start_bridge` (после `load_config()`, ~1313): вызвать `_check_pil()` один раз для раннего warning в логах старта.

**Edge**: `_check_pil` кеширует результат → один warning, не спам на каждый Edit. ImportError больше не доходит до `_send_diff_image`/`_send_result_image` (гейт отрубает раньше).

**Коммит**: `#tg-bridge: PIL availability check at startup, auto-disable images + single warning`

---

## Фикс 3: send_file → топик вызвавшего агента (БАГ 3, decision 4)

### 3a. `send_file_to_tg` (`app/tg_bridge.py:691`)
- Текущее (703-707):
  ```python
  orch_name = _find_orch_for_scope(scope)
  thread_id = config["topics"].get(orch_name) if orch_name else None
  ```
- Новое — сначала топик САМОГО sender, потом fallback на scope:
  ```python
  topics = config.get("topics", {})
  if sender and sender in topics:
      orch_name = sender
      thread_id = topics[sender]
  else:
      orch_name = _find_orch_for_scope(scope)
      thread_id = topics.get(orch_name) if orch_name else None
  ```
- `orch_name` дальше используется для mirror (719-721) и label — остаётся консистентным
  (если шлём в топик sender, mirror тоже по sender; если у sender нет mirror — `_mirror_send_file` тихо вернёт, ок).

### 3b. Тесты (`tests/test_tg_bridge.py`)
- Добавить класс/тесты на `send_file_to_tg` routing (с моками bot/config):
  - sender со своим топиком → файл уходит в `config["topics"][sender]`.
  - sender без топика → fallback на топик оркестратора скоупа (`_find_orch_for_scope`).
- `test_worker_ignored` для `_find_orch_for_scope` НЕ трогаем — функция поведения не меняет,
  меняется только вызывающий код в `send_file_to_tg`.

**Коммит**: `#tg-bridge: send_file routes to caller's own topic, fallback to scope`

---

## Что НЕ трогаем
- `md_convert`/`telegramify_markdown` — не корень бага 1, работает с fallback.
- `_find_orch_for_scope` — логика прежняя.
- diff-images для Edit/Write — остаются ON (`TG_DIFF_IMAGES=true`).
- Rate-limit `_TG_MIN_INTERVAL`/флуд-механику — не переписываем (риск усугубить); только меньше шлём (result OFF) + честное логирование.
- Прод-деплой (`uv sync` + рестарт) — делает юзер.

## Риски
- `_check_pil` через `and` в гейтах: если PIL появится в рантайме после первого False — останется выключенным до рестарта. Приемлемо (PIL ставится при деплое + рестарт).
- send_file: `sender` может быть ROLE (напр. "orchestrator") без топика → fallback на scope, как раньше. Безопасно.
- result OFF по умолчанию — поведенческое изменение, согласовано.

## Тесты
`UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/test_tg_bridge.py -x -q`
