# #174 T3 — native long-history canary

Дата: 2026-08-11. Это промежуточный результат T3, не DONE всей Phase 3.

## Предзаданный критерий

Оба target runtime должны принять одну и ту же синтетическую форму измеренной длинной
сессии и в следующем ходу дословно вернуть три значения, отсутствующие в текущем вопросе:

- UUID из самого раннего user message;
- UUID только из завершённого historical tool result;
- UUID только из текущего system/developer prompt.

Фикстура содержит ровно 7 251 DB row, 1 760 169 символов в user/assistant rows и
4 646 tool/tool-result rows. Renderer обязан явно сообщить `truncated > 0`: общий
256 000-символьный tool budget режет старые полные пары, но не user/assistant rows.
Таймаут одного semantic recall turn задан до прогона: 600 секунд.

## Версии и изоляция

Выполненная проверка версий:

```text
/usr/bin/claude --version → 2.1.197 (Claude Code)
/usr/bin/codex --version  → codex-cli 0.146.0
claude-agent-sdk          → 0.2.114 (проверяется default tripwire)
```

Оба canary создавали отдельный `tmp_path`, отдельный Claude config / `CODEX_HOME` и
копировали в него только credential-файл. Live transcript homes и Orchestra sessions не
использовались как target storage. Claude failure traceback зафиксировал isolated cwd:
`/tmp/pytest-of-kesha/pytest-1328/test_pinned_runtime_semantical0`.

## Выполненные команды и результаты

Fast shape + оба renderer paths:

```text
uv run --active python -m pytest -q tests/test_native_history_import.py -k long_fixture
1 passed, 3 deselected in 10.37s
```

Codex semantic canary:

```text
uv run --active python -m pytest -q \
  tests/test_native_history_import.py::test_pinned_runtime_semantically_recalls_long_native_history[codex]
1 passed in 37.33s
```

Codex 0.146.0 принял `thread/resume.history`, выполнил следующий turn и вернул все три
UUID. Проверка не опирается на summary: сами UUID не присутствуют в recall-вопросе.

Первый Claude semantic canary:

```text
uv run --active python -m pytest -q \
  tests/test_native_history_import.py::test_pinned_runtime_semantically_recalls_long_native_history[claude]
FAILED in 611.67s
```

`ClaudeBackend.connect()` с CLI 2.1.197 / SDK 0.2.114 и `SessionStore.load()` завершился
внутри отдельного 180-секундного connect budget. Тест затем завершился по 600-секундному
таймауту. Первоначальная интерпретация «Claude не отдал completed turn» была неверна и
опровергнута диагностикой ниже.

## Единственный 1 800-секундный диагностический прогон

По отдельному разрешению выполнен ровно один повтор той же Claude-фикстуры с диагностикой
`/proc/<pid>/stat`, backend events, stderr и materialized JSONL:

```text
R174_CLAUDE_DIAGNOSTIC=1 uv run --active python -m pytest -q -s \
  tests/test_native_history_import.py::test_pinned_runtime_semantically_recalls_long_native_history[claude]
FAILED in 1812.82s
```

Два сохранённых замера из `bg_jobs.last_output`:

```text
elapsed=1200s state=S cpu=20.55s events=8 last_event=turn_end text=161 stderr=0
elapsed=1800s state=S cpu=29.49s events=8 last_event=turn_end text=161 stderr=0
jsonl=3,698,027 bytes; mtime_ns=1786454261204660194 в обоих замерах
```

За последние 600 секунд CLI набрал 8,94 CPU-секунды, но это не ожидание модели:
`turn_end` и 161 символ ответа уже находились в event stream и не менялись. JSONL тоже не
рос. Job стартовал в 15:17:16, а последний mtime JSONL — 15:17:41.

Причина таймаута находится в тестовом collector, не в адаптере. `ClaudeBackend.events()`
читает persistent SDK stream и остаётся открытым после `turn_end`; прежний `_response_text`
продолжил `async for` и ждал следующий ход. `CodexBackend.events()` сам возвращается на
`turn/completed`, поэтому тот же дефект helper не проявился в Codex canary. Collector
исправлен: после проверки `turn_end.metadata.ok` он выходит из цикла. Добавлен отдельный
тест на persistent stream, который краснеет без этого `break`.

## Текущий вердикт

Codex long-history adapter доказанно проходит заданную поведенческую приёмку за 37,33 с.
Claude long-history import доказанно материализовался и завершил ход; гипотезы «процесс
завис» и «440K токенов требуют больше 600 секунд» опровергнуты. Однако дословное содержимое
161-символьного ответа diagnostic progress не сохранял, поэтому exact three-marker recall
Claude после исправления collector на этом этапе ещё не было перепроверено. Называть его
прошедшим до такой проверки было нельзя.

Бинарный поиск размера не запускался: его предусловие («Claude считает дольше budget»)
оказалось ложным. Disposable-worker E2E не запускался и не запрашивался по прямому указанию
до завершения этой диагностики.

## Разрешённый финальный повтор Claude

После диагностики оркестратор разрешил ровно один повтор длинного Claude canary на
исправленном collector. Команда сохраняла дословный ответ в pytest output до assertions:

```text
R174_PRINT_CANARY_RESPONSE=1 uv run --active python -m pytest -q -s \
  tests/test_native_history_import.py::test_pinned_runtime_semantically_recalls_long_native_history[claude]
```

Полный model-visible ответ:

```text
EARLY_USER_CANARY=17410000-0000-4000-8000-000000000001
TOOL_RESULT_CANARY=17420000-0000-4000-8000-000000000002
SYSTEM_CANARY=17430000-0000-4000-8000-000000000003
```

Literal pytest result:

```text
1 passed in 23.96s
```

Итог: Claude CLI 2.1.197 / SDK 0.2.114 и Codex 0.146.0 оба проходят long-history
semantic recall на одной фикстуре 7 251 / 1 760 169 / 4 646. Claude вернул ранний user
UUID, UUID только из завершённого tool result и текущий system-prompt UUID дословно.
Summary fallback не участвовал. Разница адаптеров осталась в lifecycle: Claude SDK event
stream persistent после `turn_end`, Codex stream завершается сам. Disposable-worker E2E
отложен по прямому указанию до следующего этапа T3.
