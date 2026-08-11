# #174 T1 — cross-review коммита `333fb31`

## Вердикт

**Не мержить как есть. Мержить после пяти исправлений:** пересобирать DB-history при
внутреннем reconnect Claude; не связывать неизвестный `tool_use_id` с чужим call;
ставить synthetic result сразу после незакрытого call; гарантировать rollback при сбое
построения summary fallback; закрыть обход sanitizer/budget через tool metadata и
URL-safe base64.

Внешнего вердикта Codex **нет**. Два запуска `codex_review(mode="exec")` прочитали
коммит и вернули содержательные findings, но оба завершились `exit 70` с итогом
`Codex could not execute workspace commands`; файл `codex-t1.md` не был создан.
По правилу review gate связный текст из такого запуска не считается вердиктом.
Во втором выводе была отсутствовавшая в запросе дословная строка `raise RuntimeError(`;
чтение исходника подтверждено отдельно:

```text
$ git show 333fb31:app/db.py | grep -F '    raise RuntimeError('
    raise RuntimeError(
```

Ниже — только находки, которые я независимо проверил по точному коммиту.

## Находки

### 1. Blocking — внутренний reconnect восстанавливает устаревший snapshot

`ClaudeLogSessionStore.append()` намеренно ничего не сохраняет
(`app/runtime_history.py:85-88`), поэтому новые ходы после импорта существуют durable
только в `logs`. При этом `ClaudeBackend.reconnect()` на
`app/backend_claude.py:433-442` создаёт новый client из прежнего поля
`self._history_import`; оно задаётся один раз в конструкторе и больше не обновляется.
Оба recovery-path вызывают этот метод напрямую:

- `app/session.py:1305` — listener recovery;
- `app/session_hibernate.py:174` — heartbeat recovery.

Сценарий: native import → несколько новых завершённых ходов → обрыв stream →
`backend.reconnect()` → SDK снова материализует только исходный snapshot. Новые ходы
молча исчезают из контекста, после чего continuation способен повторить уже совершённый
side effect. Заодно reconnect обходит повторную version-check.

Исправление должно возвращать DB-backed Claude recovery через `AgentSession`, где перед
новым client заново вызывается `_build_claude_history_import()`. Нужен тест: добавить
новые logs после первого connect, вызвать именно listener/heartbeat recovery и доказать,
что второй `SessionStore` содержит их.

### 2. Blocking — неизвестный ID результата присваивается чужому call

В `app/runtime_history.py:346-362` result с непустым, но неизвестным
`tool_use_id` после неудачного lookup всё равно попадает в общий
`pending_legacy.popleft()`. В очереди лежат и calls с настоящими ID. Поэтому result B
может стать результатом call A, хотя metadata прямо говорит обратное.

Минимальный прогон точного `runtime_history.py` из коммита:

```text
CALL CALL-A -> toolu_orchestra_030104361daeefe732e20c5a
RESULT RESULT-B -> toolu_orchestra_030104361daeefe732e20c5a
```

FIFO допустим только когда ID отсутствует с обеих сторон. Непустой unmatched ID должен
создавать synthetic completed call, не забирать identified pending call. Нужны случаи
mixed legacy/new rows и unmatched non-empty ID.

### 3. Blocking — synthetic completion ставится после следующего assistant text

`close_pending()` вызывается перед новым user message и в конце рендера, но не перед
веткой `text` (`app/runtime_history.py:319-335,365-366`). Для истории
`tool → text` получается:

```text
assistant tool_use
assistant text
user tool_result
```

То есть итоговый tail формально не pending, но terminal result находится уже после
следующего assistant message. Это не корректная completed-tool последовательность и
может быть отвергнуто native schema либо исказить причинность. Pending calls следует
закрывать до первой последующей записи, которая не может быть их result. Тест должен
проверять порядок блоков, а не только равенство множеств call/result IDs.

### 4. Blocking — ошибка построения fallback оставляет live object полупереключённым

На `app/session.py:2276-2284` старый backend уже отключён, а model/runtime/session ID
заменены целевыми. Затем обработчик `NativeHistoryImportError` строит fallback на
`app/session.py:2305-2309` **до** внутреннего recovery `try`. Если
`_build_runtime_handoff()` падает (например, DB read), исключение из одного `except`
не ловится соседним `except Exception`; `restore_old_state()` не вызывается. При ID
mismatch подключённый target backend также может остаться жив.

Это нарушает обещанный rollback unrelated failure. План требовал построить emergency
summary до отключения старого backend; такой порядок одновременно устраняет риск.
Нужен тест с пустым `last_summary` и исключением из `_build_runtime_handoff()`, который
проверяет model, runtime, session ID, history marker, handoff и отсутствие target process.

### 5. Blocking — часть binary/metadata обходит sanitizer и budgets

`_LARGE_BASE64` на `app/runtime_history.py:100` принимает только стандартный алфавит
base64. Валидный 1024-символьный URL-safe base64 с `-`/`_` прошёл в serialized entries
целиком, без redaction и truncation. Кроме того, `source_tool_name` копируется напрямую
на `app/runtime_history.py:269`, то есть не проходит ни sanitizer, ни отдельный limit.

Репродукция точного модуля:

```text
{'base64url_chars': 1024, 'base64url_survives': True,
 'metadata_secret_survives': True, 'redactions': 0, 'truncated': 0}
```

Это уже не неопознаваемый «произвольный секрет»: URL-safe base64 — конкретный бинарный
формат, а план обещает stub для base64/binary payload и единый sanitizer для всех
переносимых полей. Нужно распознавать URL-safe вариант и sanitize+bound model-visible
metadata; оба случая закрепить planted fixtures.

## Что проверено самостоятельно

### Схема и legacy resume

- `git show 333fb31:app/db.py` подтверждает только additive `ALTER TABLE`: nullable
  `sessions.history_import_source` и nullable `logs.tool_use_id/tool_name/tool_is_error`.
  `save_session()` задаёт отсутствующему marker `None`; destructive migration/UPDATE
  legacy rows нет.
- В обычной Claude-ветке при пустом marker остаётся только `options.resume = resume_id`;
  `session_store` и новый `system_prompt` назначаются исключительно при
  `_history_import`. Изменения прежнего resume-path не найдено.

### Snapshot boundary и последнее сообщение

- `_change_to_claude_with_history_locked()` делает `_drain_persist()`, затем фиксирует
  `MAX(log.id)` и выбирает `id <= max_id` до disconnect и до status/warning самого
  switch. Весь switch находится под `_lifecycle_lock`, поэтому параллельный `send()` не
  может записать/отправить сообщение посередине перехода.
- На wake текущее user message записывается до рендера, но передаётся в
  `exclude_history_users`; renderer исключает последние совпадения справа налево. Потери
  последнего сообщения на этой ветке не найдено.
- Замечание первого запуска Codex про отсутствие явной read transaction отклонено:
  concurrent INSERT получает ID выше boundary, UPDATE logs отсутствует, а
  `cleanup_old_logs()` в этом коммите всегда падает с `RuntimeError`. Для живой сессии
  на штатном T1 switch-path между двумя reads нет операции, меняющей старые строки.

### Секреты, объём и tool completion

- In-memory запуск точного `app/runtime_history.py` подтвердил, что Bearer, named API
  key, PEM и 600 символов standard base64 не остаются в entries; полный payload в
  30 000 символов тоже не уезжает. Найденные обходы перечислены в finding 5.
- Два отдельных прогона точного renderer воспроизвели неправильное ID-сопоставление и
  порядок `tool_use → assistant text → tool_result`.

### Fallback и цена reconnect

- Auth/network/process exception без четырёх schema markers остаётся обычным exception;
  автоматический summary fallback для него не найден. Rollback-дыра находится именно
  внутри typed fallback и описана в finding 4.
- Полный рендер не выполняется на каждом ходе: живой `_backend` даёт быстрый return из
  `_ensure_backend()`. Цена ~1,7 с повторяется после process-free startup/hibernate,
  identity restart, server-error retry и перед compact, пока marker активен. Но listener
  и heartbeat reconnect идут ещё опаснее: они не платят цену повторного рендера и
  восстанавливают устаревшую историю (finding 1).

Полный pytest коммита независимо не запускался: текущий checkout находится на другой
ветке, а создавать второй checkout или менять файлы правки ревьюеру запрещено. Заявленные
автором `2118 passed` не использованы как собственное доказательство.
