# Codex CLI — JSONL long-line crash + Python SDK (research, 2026-07-16)

Исследование по багу с длинными JSONL-строками в `codex exec --json` и наличию Python SDK для Codex.
Все URL ниже — реально открыты (WebSearch + WebFetch). Версии/термины — English.

---

## Вопрос 1 — Длинные JSONL-строки / 64KB crash в `codex exec --json`

### Findings

**Главный вывод: "64KB crash" — это НЕ баг Codex, а ограничение читателя на стороне клиента.**
Codex спокойно печатает очень длинные JSONL-строки в stdout (один event = одна строка). Падает не Codex, а тот, кто читает его stdout построчно с дефолтным лимитом буфера.

**1.1. Python `asyncio.StreamReader` — дефолтный лимит 64KB (root cause нашего кейса).** `[tier: multiple sources]`
- `readline()` внутри вызывает `readuntil('\n')`. У `StreamReader` дефолтный `limit = 64 KiB` (65536 байт). Если строка длиннее лимита — при найденном `\n` бросается `asyncio.LimitOverrunError('Separator is found, but chunk is longer than limit')`; если `\n` ещё не встретился и буфер переполнен — вариант `'Separator is not found, and chunk exceed the limit'`. Это точный текст из CPython `Lib/asyncio/streams.py`. `[src 8, 10]`
- Аналогичный, документированный один-в-один кейс в другом CLI-агенте: **MoonshotAI/kimi-cli issue #831** — `asyncio StreamReader LimitOverrunError causes ACP server crash on large JSON-RPC messages`. Формулировка root cause там дословно применима к Codex: "JSON-RPC over stdio requires each message to be a single line terminated by a newline. `StreamReader.readline()` uses a fixed-size buffer (default 64KB) and raises `LimitOverrunError` when the buffer is full... stdio/pipes lack flow control (no backpressure)." `[src 9]`
- Codex `exec --json` — это именно JSONL-поток: каждый event (command_execution, file_change, agent message, mcp tool call) — отдельный объект в одну строку. Любой event, чей JSON >64KB на одной строке (большой diff, длинный вывод команды, большой `tool_result`, base64-картинка), рвёт дефолтный reader. `[src 9, подтверждено логикой формата из src 4]`

**Фиксы на стороне клиента (потребителя stdout):** `[tier: multiple sources]`
1. Поднять `limit` при создании subprocess/reader:
   ```python
   proc = await asyncio.create_subprocess_exec(
       "codex", "exec", "--json", task,
       stdout=asyncio.subprocess.PIPE,
       limit=100 * 1024 * 1024,  # 100 MB вместо дефолтных 64 KB
   )
   ```
2. Не читать построчно, а читать сырыми чанками `read(n)` и самому бить по `\n` (обходит внутренний лимит `readuntil`).
3. Ловить `LimitOverrunError` в цикле чтения, чтобы одна гигантская строка не убивала весь loop. `[src 9]`

**1.2. Codex-сторона: длинные строки реальны, но CLI-краша от них НЕ подтверждено.** `[tier: official GitHub]`
- **Issue #22004** (`RangeError: Invalid string length` on session load) — OPEN, открыт 2026-05-10. Это про **desktop app**, НЕ про `codex exec --json` stdout. Electron main-process копит stdout ребёнка в одну JS-строку и падает на лимите V8 (~512 MB). Root cause оверсайза: **каждая сгенерённая картинка вшита как base64 (~1–2 MB) прямо inline в rollout JSONL**; после ~300–500 картинок в одном треде файл превышает лимит. Фикс не зарелижен, issue открыт. Важно: подтверждает, что **Codex действительно пишет очень длинные JSONL-строки** (base64 inline) — но краш описан для desktop-загрузки сессии, не для exec-стрима. `[src 2]`
- **Issue #23042** — Codex Desktop должен fail-soft на control-символах и oversized historical tool output. Один historical tool render string ≈ 1 MB, несколько по сотни KB, с сырыми C0/ANSI escape. Опять desktop-рендер, не exec-stdout, но снова подтверждает: `tool_result` строки бывают ~1 MB. `[src 3]`

**1.3. Есть отдельный подтверждённый баг усечения `tool_result` (не про 64KB, но смежный).** `[tier: official GitHub]`
- **Issue #6426** — line-based truncation вывода тулов: хардлимит 256 строк ИЛИ 10 KiB (что раньше), head+tail (первые 128 + последние 128 строк). Предлагают token-based лимит. `[src 4 из первого поиска]`
- **Issue #10141** (CLOSED, codex-cli 0.92.0) — в `--json` `command_execution.aggregated_output` может быть пустым, если вывод шёл только через `ExecCommandOutputDelta`, а `ExecCommandEnd.aggregated_output` пуст. Предложенный фикс: буферить delta stdout/stderr отдельно с cap 1 MiB на поток. Это про потерю данных, не про длину строки. `[src 1]`

**Фикс в новой версии (0.144.4/0.144.5/0.145 alpha)? — НЕ найдено.** `[tier: official changelog]`
Проверены changelog и GitHub releases: ни 0.144.3, ни 0.144.4, ни 0.144.5, ни 0.145.0-alpha.* не упоминают `exec`, `--json`, JSONL, буфер stdout или длинные строки. См. Вопрос 4. `[src 5, 6]`

**Документированный workaround-флаг для лимита вывода `codex exec --json`? — НЕ найдено.**
Флага "ограничь длину JSON-строки" или "`--experimental-json`" в доке non-interactive нет (см. Вопрос 3). Есть `--output-schema` (структурировать финал) и `-o file` (писать финальное сообщение в файл), но они НЕ ограничивают длину промежуточных event-строк JSONL-стрима.

**Confidence:** высокая на root cause (клиентский 64KB-лимит asyncio) и на факте длинных base64-строк Codex; средняя на "нет CLI-краша именно в exec-режиме" (issue-трекер показывает краши только desktop-загрузки, не exec-stdout).

---

## Вопрос 2 — Codex SDK (Python / аналог claude-agent-sdk)

### Findings

**ДА, у OpenAI есть официальный Codex SDK. Python — в beta.** `[tier: official docs + PyPI]`

**2.1. Официальный Python SDK: `openai-codex`.** `[tier: official]`
- PyPI: `pip install openai-codex`, **publisher = OpenAI**. `[src 11]`
- Версии: `0.1.0b1`/`0.1.0b2` (2026-05-28), `0.1.0b3` (2026-06-03, последняя). Development Status = **"4 - Beta"**. Python >=3.10. `[src 11]`
- Архитектура (из офдоки): Python SDK **управляет локальным Codex app-server через JSON-RPC**, тянет pinned Codex CLI как зависимость рантайма. Есть sync `Codex` и async `AsyncCodex`. Sandbox-пресеты (`read_only` / `workspace_write` / `full_access`). Стартует threads, гоняет turns, стримит прогресс. `[src 12]`
- API-пример:
  ```python
  from openai_codex import Codex
  with Codex() as codex:
      thread = codex.thread_start()
      result = thread.run("Explain this repository in three bullets.")
      print(result.final_response)  # TurnResult: final_response, items, token usage
  ```
  `[src 12]`
- **Ключевое для нас:** SDK сам держит JSON-RPC/стриминг поверх app-server — то есть **разбор JSONL берёт на себя, не надо самому парсить stdout `codex exec --json`** (значит и 64KB-проблема из Вопроса 1 обходится, если идти через SDK, а не через subprocess+readline).

**2.2. TypeScript SDK: `@openai/codex-sdk`.** `[tier: official]`
- `npm install @openai/codex-sdk`, Node.js 18+. Позиционируется как более полный/гибкий способ управлять Codex, чем non-interactive режим. `[src 12]`

**2.3. Codex как MCP-сервер + Agents SDK (альтернативный путь).** `[tier: official]`
- Офдока прямо разделяет: "Use the Codex SDK for coding-focused Codex threads. If Codex is one specialist inside a broader orchestrated workflow, run Codex CLI as an MCP server and orchestrate it with the Agents SDK." То есть `codex mcp-server` — задокументированный программный путь для оркестрации. `[src 12]`

**2.4. Осторожно — есть чужие пакеты с похожими именами (НЕ OpenAI):** `[tier: PyPI verified]`
- `codex-sdk` (PyPI) — это **Cleanlab** (team@cleanlab.ai), internal для `cleanlab-codex`, вообще не про CLI-Codex OpenAI. Latest `0.1.0a34`, 2025-11-19. НЕ использовать. `[src 13]`
- `openai-codex-sdk` (PyPI, автор "tomasroda", 2026-01-19) — third-party обёртка над бинарником codex, спавнит CLI и обменивается JSONL-events по stdin/stdout. Не официальный. `[src, упомянут в результатах поиска — карточку отдельно не открывал, поэтому только как "mentioned", не подтверждено фетчем]`

**Confidence:** высокая на официальный `openai-codex` (beta) и `@openai/codex-sdk` — открыты офдока + PyPI. Средняя/низкая на third-party `openai-codex-sdk` (не фетчил карточку напрямую).

---

## Вопрос 3 — Альтернативы `--json` в `codex exec`

### Findings `[tier: official docs — learn.chatgpt.com/non-interactive]`

Из офдоки non-interactive режима подтверждены флаги:
- **`--json`** — "stdout становится JSONL-потоком, ловишь каждый event, который Codex эмитит". Event-типы: `thread.started`, `turn.started`, `turn.completed`, `turn.failed`, `item.*` (`item.started`/`item.completed`), `error`. Item-типы: agent messages, reasoning, command executions, file changes, MCP tool calls, web searches, plan updates. `[src 14]`
- **`--output-schema <path>`** — заставить финальный ответ соответствовать JSON Schema. Для CI/CD со стабильными полями. `[src 14]`
- **`-o <path>` / `--output-last-message <path>`** — пишет **финальное сообщение** в файл (и всё равно печатает в stdout). `[src 14]`

**Важно — ответ на "спасёт ли `-o file` от stdout-стриминга?": НЕТ (частично).**
`-o` пишет в файл только **финальное сообщение**, а не весь JSONL-стрим event'ов. Если нужен полный поток событий — он всё равно только в stdout через `--json`. Значит `-o` не обходит проблему длинных промежуточных строк; он про финальный результат. `[src 14]`

**`--jsonl`, `--experimental-json`, `--output-format` — НЕ найдено** в офдоке non-interactive. Единственный стрим-режим = `--json` (который и есть JSONL). `[src 14]`

**Известный баг взаимодействия:** **Issue #15451** (CLOSED, codex-cli 0.116.0) — `--json` + `--output-schema` **тихо игнорируются, когда активны MCP-серверы/тулы**: вместо валидного JSON модель выдаёт YAML-подобные объекты без внешних скобок, без запятых, без кавычек у ключей, в markdown-обёртке. Подозрение репортера — `response_format: {strict:true}` дропается CLI или отклоняется бэкендом при наличии tools. **Критично для Orchestra**, т.к. воркеры гоняют Codex с MCP-серверами. `[src 15]`

**Confidence:** высокая (офдока напрямую + closed issue с версией).

---

## Вопрос 4 — Версионирование Codex CLI

### Findings `[tier: official changelog + GitHub releases]`

- **Latest stable: `0.144.5`** (2026-07-16). Changelog: "Improved dangerous-command detection, including more forced `rm` forms, clearer rejection reasons." Ключевой PR #33455 `fix(core) expand is_dangerous_command`. `[src 5, 6]`
- **Latest alpha: `0.145.0-alpha.16`** (2026-07-16). Release notes у alpha.9–16 пустые ("Release 0.145.0-alpha.X"), деталей нет. `[src 6]`
- Твоя гипотеза "stable 0.144.5, alpha 0.145.0-alpha.16" — **ПОДТВЕРЖДЕНА** (обе даты 2026-07-16). `[src 6]`

**Что менялось 0.144.3 → 0.144.5:** `[tier: official changelog]`
- `0.144.0` (2026-07-09) — крупный релиз: usage-limit reset credits, новые app-approval modes, улучшения MCP-аутентификации, перф.
- `0.144.1` (2026-07-09) — фиксы standalone-инсталлов, macOS package installs, code-mode fallback.
- `0.144.2` (2026-07-13) — откат prompting-регрессии Guardian auto-review (восстановлены policy/format/tool behavior).
- `0.144.3` (2026-07-13) — version-only, **нет merged PR** относительно 0.144.2.
- `0.144.4` (2026-07-14) — no user-facing changes (в одном источнике формулируется как восстановление Guardian auto-review — вероятная путаница с 0.144.2; changelog говорит "no user-facing changes").
- `0.144.5` (2026-07-16) — dangerous-command detection (см. выше).

**Что 0.145 alpha добавляет по JSON/exec: НЕ найдено.** Alpha-релизы без описаний; ни один changelog-энтри 0.144.x/0.145.0-alpha не упоминает `exec`, `--json`, JSONL, буфер или длинные строки. `[src 5, 6]`

**Каналы:** stable (`0.144.5`) + alpha (`0.145.0-alpha.*`) — оба на GitHub Releases, одновременно (обе от 2026-07-16). Beta/nightly отдельных каналов в источниках не видно; alpha = pre-release канал. `[src 6]`

**Confidence:** высокая на версии/даты; высокая на "нет JSON/exec-изменений в 0.144.x"; средняя на детали 0.144.4 (расхождение формулировок между источниками).

---

## Sources (только реально открытые URL)

**Official GitHub issues (openai/codex):**
1. https://github.com/openai/codex/issues/10141 — JSON output drops `command_execution` aggregated_output (CLOSED, 0.92.0)
2. https://github.com/openai/codex/issues/22004 — desktop `RangeError: Invalid string length` on rollout JSONL >512MB, base64 images inline (OPEN, 2026-05-10)
3. https://github.com/openai/codex/issues/23042 — упомянут в результатах поиска (oversized/control-char historical tool output, desktop) — *не фетчил напрямую, только из сниппета поиска*
4. github.com/openai/codex/issues/6426 — line-based tool output truncation 256 lines/10KiB — *из сниппета поиска, не фетчил напрямую*
5. https://github.com/openai/codex/issues/15451 — `--json`+`--output-schema` тихо игнорируются при активных MCP/tools, malformed output (CLOSED, 0.116.0) — фетчен

**Official docs (learn.chatgpt.com / developers.openai.com, 308-редирект):**
6. https://learn.chatgpt.com/docs/codex-sdk — Codex SDK (Python `openai-codex`, TS `@openai/codex-sdk`), JSON-RPC поверх app-server — фетчен
7. https://learn.chatgpt.com/docs/non-interactive-mode — `codex exec` флаги (`--json`, `--output-schema`, `-o/--output-last-message`), event-типы — фетчен
8. https://learn.chatgpt.com/docs/changelog — changelog 0.144.x — фетчен
9. https://github.com/openai/codex/releases — latest stable 0.144.5, alpha 0.145.0-alpha.16 (оба 2026-07-16) — фетчен

**Official PyPI:**
10. https://pypi.org/project/openai-codex/ — официальный OpenAI Python SDK, 0.1.0b3 (2026-06-03), Beta — фетчен
11. https://pypi.org/project/codex-sdk/ — Cleanlab (НЕ OpenAI), internal, 0.1.0a34 — фетчен

**Multiple sources (клиентский 64KB-лимит):**
12. https://github.com/MoonshotAI/kimi-cli/issues/831 — asyncio StreamReader LimitOverrunError на JSON-RPC >64KB (аналог, root cause один-в-один) — из сниппета поиска
13. CPython `Lib/asyncio/streams.py` (fossies.org / bugs.python.org issue20841) — дефолтный `limit=64KiB`, точный текст ошибки — из сниппетов поиска

**Нумерация в тексте выше** ссылается на порядок находок; канонические URL — этот список.

---

## Не найдено (честно)

- **Отдельного issue именно про краш `codex exec --json` из-за длинной строки в stdout** — НЕ найдено. Все подтверждённые краши от длинных JSONL-строк относятся к **desktop app** (session load, #22004/#23042), не к exec-стриму. Для exec 64KB-падение — это клиентский reader-лимит (asyncio), а не баг Codex.
- **Флага `codex exec` для ограничения длины JSON-строки / `--experimental-json` / `--jsonl` / `--output-format`** — НЕ найдено. Есть только `--json`, `--output-schema`, `-o/--output-last-message`.
- **Фикса long-line/buffer в 0.144.4 / 0.144.5 / 0.145.0-alpha** — НЕ найдено (changelog молчит про exec/json).
- **Точного текста ошибки "chunk longer than limit" внутри репозитория openai/codex** — НЕ найдено (это ошибка потребителя-читателя, не Codex).
- **Прямого фетча карточки `openai-codex-sdk` (tomasroda, third-party)** — НЕ делал; статус "mentioned in search", не подтверждён.
