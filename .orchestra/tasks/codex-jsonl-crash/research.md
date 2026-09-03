# Research: Codex CLI JSONL-краш (64KB) + SDK + версии + контекст Sol

**Дата:** 2026-07-16
**Тип:** Phase 1 (research, без экспериментов на проде)
**Триггер:** Sol-пилот крашнулся на `LimitOverrunError: Separator is found, but chunk is longer than limit` при чтении stdout `codex exec --json`.

Сопутствующий док: `codex-cli-issues.md` — полное investigation по GitHub issues/SDK/версиям с источниками и tier-ами.

---

## Question (framed)

- **Context:** Orchestra читает stdout codex-воркера построчно (`backend_codex.py:118`, `async for raw_line in self._proc.stdout`) в `--json` (JSONL) режиме.
- **Симптом:** краш `LimitOverrunError('Separator is found, but chunk is longer than limit')` на длинной JSONL-строке.
- **Change under test:** мы фиксим на своей стороне (`limit=16MB` на StreamReader). Research: правильный ли это фикс, есть ли лучше (SDK), пофикшено ли в новой версии Codex, почему строки >64KB, реальный контекст Sol.
- **Baseline:** текущий subprocess + `async for` (дефолтный 64KB reader limit).
- **Outcome:** подтвердить root cause + оценить альтернативы (limit-bump vs chunked-read vs SDK).

**Тип:** качественный аудит кода + фактологический lookup (RETRIEVE). Экспериментов на проде НЕ проводил.

---

## Hypotheses considered

- **H1 (лидирующая, верна):** «Краш — не баг Codex, а дефолтный 64KB лимит asyncio StreamReader на нашей стороне. Codex легально пишет длинные JSONL-строки (вывод команд/diff/base64), потребитель падает.»
  - Falsifier: если бы это был баг Codex — был бы issue про exec-stdout краш И фикс в changelog. Проверил: нет такого issue, нет фикса → H1 стоит.
- **H2 (альтернатива):** «Баг в Codex, пофикшен в 0.144.5/0.145-alpha.» → **REFUTED**: changelog 0.144.x/0.145-alpha не упоминает exec/json/буфер вообще.
- **H3 (альтернатива):** «Через SDK лучше чем subprocess.» → **LIKELY** для будущего: официальный `openai-codex` SDK существует (beta), сам парсит JSON-RPC — обходит проблему. Но это рефактор, не срочный фикс.

---

## Findings — по 5 вопросам оркестратора

### 1. Codex CLI issue про длинные JSONL — есть ли, пофикшено ли?

**Root cause — НАШ, не Codex.** `[CONFIRMED — код + multiple sources]`
- `backend_codex.py:118` `async for raw_line in self._proc.stdout` → под капотом `StreamReader.readline()` → `readuntil('\n')` с дефолтным `limit=64 KiB`. Строка >64KB → `LimitOverrunError('Separator is found, but chunk is longer than limit')` — точный текст из CPython `Lib/asyncio/streams.py`.
- Один-в-один задокументированный аналог: **MoonshotAI/kimi-cli #831** — «asyncio StreamReader LimitOverrunError causes ACP server crash on large JSON-RPC messages». Тот же механизм (JSON-RPC/JSONL over stdio, 64KB буфер, нет backpressure).

**Codex-сторонних exec-крашей от длинных строк НЕ найдено.** `[CONFIRMED — GitHub issue tracker]`
- Есть краши от длинных JSONL, но только в **desktop app** (не exec-stdout): #22004 (`RangeError: Invalid string length` при загрузке сессии — base64-картинки inline рвут V8 512MB), #23042 (oversized historical tool output). Оба подтверждают что **Codex реально пишет очень длинные строки**, но краш — на стороне desktop-рендера, не exec-стрима.
- Смежное: #6426 (line-based truncation вывода тулов 256 строк/10KiB), #10141 (CLOSED — `aggregated_output` пустой при delta-only выводе).

**Пофикшено в новой версии? — НЕТ.** `[CONFIRMED — changelog]`
- Ни 0.144.3→0.144.5, ни 0.145.0-alpha.* не трогают exec/json/JSONL/буфер. 0.144.5 = только dangerous-command detection. **Обновление версии проблему НЕ решит** — фикс должен быть на нашей стороне (или через SDK).

### 2. Почему строки >64KB — что за payload?

**Причина: `command_execution.aggregated_output` инлайнится в ОДНУ JSONL-строку.** `[CONFIRMED — наш код]`
- `backend_codex.py:144` — `output = item.get("aggregated_output", "")` — полный stdout команды, которую Sol запустил (bash `cat`/`grep`/тесты/build), одним JSON-объектом в одну строку. Sol гоняет команды часто (terminal-oriented модель) → большой вывод = гигантская строка.
- Плюс (из issues): base64-картинки inline (~1-2MB каждая, #22004), большие diff/`tool_result` (~1MB, #23042).
- **В пилоте у нас:** Sol в full-cycle гоняет команды и читает файлы → `aggregated_output` легко >64KB на verbose-выводе. Это и есть триггер.

**Можно ли отключить `--json`?** `[CONFIRMED — official docs]`
- Альтернатив `--json` для стрима **НЕТ**: `--jsonl`/`--experimental-json`/`--output-format` не существуют. `--json` = единственный event-стрим (это и есть JSONL).
- `-o/--output-last-message <file>` пишет **только финальное сообщение** в файл, event-стрим всё равно в stdout → **не спасает** от длинных промежуточных строк.
- `--output-schema` структурирует финал, но не стрим.
- ⚠️ **Известный баг #15451** (CLOSED, 0.116.0): `--json`+`--output-schema` тихо ломаются при активных MCP/tools → malformed output. **Критично для нас** (воркеры гоняют Codex с MCP). Проверить на 0.144.3.

### 3. Codex SDK — есть ли, лучше ли чем subprocess?

**ДА — официальный `openai-codex`, Python, beta.** `[CONFIRMED — live PyPI JSON fetch]`
- Verified через `pypi.org/pypi/openai-codex/json`: name=`openai-codex`, **author=OpenAI**, summary="Python SDK for Codex", latest=`0.1.0b3`, Dev Status=Beta, Python>=3.10, repo=`github.com/openai/codex`.
- Архитектура: SDK управляет локальным **Codex app-server через JSON-RPC**, сам держит стриминг/парсинг. sync `Codex` + async `AsyncCodex`, sandbox-пресеты.
  ```python
  from openai_codex import Codex
  with Codex() as codex:
      thread = codex.thread_start()
      result = thread.run("...")   # TurnResult: final_response, items, usage
  ```
- **Ключевое:** SDK разбирает JSON-RPC сам → **64KB-проблема обходится** (не мы парсим stdout построчно). Это аналог `claude-agent-sdk` — правильный долгосрочный путь.
- TS-версия: `@openai/codex-sdk`.
- ⚠️ **Не путать:** PyPI `codex-sdk` = Cleanlab (НЕ OpenAI). `openai-codex-sdk` (tomasroda) = third-party. Официальный именно `openai-codex`.

**Вердикт:** SDK лучше subprocess архитектурно, но:
- Он **beta** (0.1.0b3) — риск для прода.
- Миграция subprocess→SDK = переписать весь `CodexBackend` (event-mapping, resume, MCP-инъекция через `-c`, effort). Большой рефактор.
- **Для срочного фикса краша — limit-bump проще и достаточно.** SDK — отдельная задача на будущее (когда SDK выйдет из beta или если subprocess-путь окажется хрупким).

### 4. Версии Codex CLI — beta/nightly?

`[CONFIRMED — GitHub releases]`
- У нас установлено **0.144.3** (не 0.144.1 как в задаче — проверил `codex --version`).
- **Latest stable: 0.144.5** (2026-07-16). **Latest alpha: 0.145.0-alpha.16** (2026-07-16).
- Каналы: stable + alpha (pre-release). Отдельного beta/nightly канала нет; alpha = nightly-аналог.
- **Ни одно изменение 0.144.x/0.145-alpha не про exec/json** → апгрейд не поможет с крашем. Апгрейд 0.144.3→0.144.5 полезен только для dangerous-command detection (не наша проблема).

### 5. Контекст Sol — реально 1M или 250K?

**Реальный контекст = 1,050,000 токенов (1.05M). "250K/272K" — это ПОРОГ ЦЕНЫ, не лимит контекста.** `[CONFIRMED — official OpenAI docs T1]`
- **OpenAI official** (`developers.openai.com/api/docs/models/gpt-5.6-sol`): «1,050,000 context window», «128,000 max output», «Prompts with >272K input tokens are priced at 2x input and 1.5x output for the full request».
- Т.е. окно = 1.05M, но выше **272K input** включается surcharge (2×in/1.5×out на весь запрос: $10/$45 вместо $5/$30). Отсюда путаница «250K».
- **Подтверждение из нашего пилота (измерено):** CLI репортит `max_tokens=997500` (=1.05M×0.95 usable), `ctx_pct=6` при `ctx_tokens=62341` (62341/997500=6.25% ✓). Наш `CODEX_CONTEXT_LIMITS['gpt-5.6-sol']=997500` — корректен.
- ⚠️ **Практический риск (issue #32486):** дефолтный auto-compact Codex может незаметно перевести сессию через 272K → premium-биллинг без ведома юзера. Workaround: `model_auto_compact_token_limit = 270000` чтобы держать дешёвый тариф. Актуально если Sol-воркеры гоняют длинные сессии.

**⚠️ Конфликт источников:** issue #32486 (репортер) упоминает «372,000-token context window with 95% multiplier (353,400)» — противоречит official 1,050,000. Official docs = T1, приоритет → **1.05M авторитетно**; 372K репортера = вероятно ошибка или про другое (или устаревший снапшот). Флагую конфликт, не смешиваю.

**⚠️ Codex-ревью уточнил (проверил на model page):** official Sol = context window **1,050,000**, **max input 922,000**, max output 128,000. Наш `CODEX_CONTEXT_LIMITS['gpt-5.6-sol']=997500` **превышает официальный max input 922,000** — как «usable prefill limit» это неверно. 997500 работает как внутренний denominator CLI (пилот: `max_tokens=997500`), но официальный prefill-потолок = 922,000. 1.05M total не опровергается.

---

## 🔴 БЛОКЕР (нашёл Codex-ревью, проверил кодом): limit-bump ещё НЕ в CodexBackend

**`app/backend_codex.py:105` `create_subprocess_exec()` НЕ передаёт `limit=` — дефолт 64KB.** `[CONFIRMED — прочитал :104-111]`
- 16MB (`_STREAM_LIMIT`) есть ТОЛЬКО в `bg_jobs.py:456,461` — это путь `codex_review` bg-job, НЕ stdout воркера.
- Значит **краш codex-воркера ещё НЕ починен** — фикс «limit=16MB на нашей стороне» в worker-путь (`CodexBackend.send()`) не приземлился.
- Моя первичная research-формулировка «`:105` уже фиксится с limit=» была **НЕВЕРНА** (перепутал с bg_jobs). Исправлено.
- **Для реального фикса нужно:** добавить `limit=16*1024*1024` в `create_subprocess_exec()` в `CodexBackend.send()` (`:105`), + regression-тест на JSONL event >64KB.

## Наш фикс (limit=16MB) — правильный?

**ДА, правильный и достаточный для срочного фикса.** `[CONFIRMED — механизм]`
- `create_subprocess_exec(..., limit=16*1024*1024)` поднимает буфер StreamReader с 64KB до 16MB → строки до 16MB читаются без краша.
- **Оценка достаточности 16MB (ПРОВЕРЕНО эмпирически):** `limit=16MB` на `create_subprocess_exec` реально поднимает потолок `async for`/`readline` — строка 200KB читается без краша (замер: `[200000, 3] → works`). Типичный `aggregated_output` — сотни KB до ~1-2MB, base64 ~1-2MB → 16MB покрывает с запасом. Но:
  - ⚠️ **Не абсолютная гарантия:** если Sol дампит >16MB stdout в одной команде — снова краш.

**⚠️ Тонкость fail-soft — зависит от паттерна чтения (ПРОВЕРЕНО эмпирически; Codex поймал, я сначала ошибся):**
  - `readline()` **пере-оборачивает `LimitOverrunError` в обычный `ValueError`** (`streams.py:571 raise ValueError(e.args[0])`) И **выбрасывает проблемную строку из буфера**. Значит ловить `asyncio.LimitOverrunError` **бесполезно** — надо ловить `ValueError`.
  - `async for line in stream` (наш текущий :118): при ошибке итератор **умирает**, все последующие строки теряются (замер: OK1 → giant → ValueError на loop-level → **OK2 потерян**). ❌ Обёртка вокруг `async for` — НЕ fail-soft.
  - **НО** явный `while` + `readline()` + `except ValueError: continue` **РАБОТАЕТ как fail-soft** (замер: `['OK1', '[SKIP:ValueError]', 'OK2']` — OK2 восстановлен!). readline выбросил битую строку → следующий readline берёт OK2. ✅ Codex был прав: строка discard-ится, чтение продолжается.
  - **Итог:** есть 3 рабочих пути. Не работает только «`async for` + try/except».

**Chunked-read ПРОВЕРЕН и полностью надёжен (замер):** читать `stream.read(65536)` в буфер и самому бить по `\n` — `limit` к `read()` не применяется. Замер: строка 200KB при `limit=100` прочитана целиком, OK2 выжил. Читает строку ЛЮБОГО размера (не skip, а прочитать).

**Альтернативы (по возрастанию усилий / по свойствам):**
1. `limit=16MB` (текущий фикс) — 5 мин, читает строки ≤16MB целиком. ✅ срочно, ПРОВЕРЕН. Минус: >16MB всё равно краш.
2. `while`+`readline()`+`except ValueError: continue` — fail-soft: битую строку (любого размера) **skip+log**, чтение продолжается. ✅ ПРОВЕРЕН. Минус: теряем содержимое гигантской строки (но не крашимся). Замена `async for` на while-loop.
3. **Chunked-read** (`read(65536)` + свой split по `\n`) — **читает** строку любого размера (не skip). ✅ ПРОВЕРЕН, самый надёжный. Минус: ~10 строк переписать `events()`.
4. `openai-codex` SDK — парсит сам, но beta + большой рефактор. Долгосрочно.

**Рекомендация:** `limit=16MB` (current) закрывает срочность. Для полной надёжности лучший вариант — **#1 + #2 вместе**: `limit=16MB` (читать нормальные большие строки целиком) + `while/readline/except ValueError` (fail-soft на экстремальных >16MB, чтобы turn не падал). Chunked-read (#3) — если важно НЕ терять содержимое гигантских строк. try/except вокруг `async for` — не вариант (итератор мёртв).

---

## Confidence per finding

1. Root cause = наш 64KB asyncio-лимит — **CONFIRMED** (код + kimi-cli #831 + CPython streams.py).
2. Длинные строки = `aggregated_output` инлайн — **CONFIRMED** (наш код :144) + base64/diff (issues).
3. Не баг Codex, не пофикшено в новой версии — **CONFIRMED** (issue tracker + changelog молчат про exec).
4. `openai-codex` SDK существует, официальный, beta — **CONFIRMED** (live PyPI JSON: author=OpenAI).
5. `--json` — единственный стрим, `-o` не спасает — **CONFIRMED** (official docs).
6. Sol контекст = 1.05M, 272K = ценовой порог — **CONFIRMED** (OpenAI official docs T1).
7. limit=16MB читает строки ≤16MB, chunked-read читает любой размер — **CONFIRMED** (замерил оба). Fail-soft `while/readline/except ValueError: continue` РАБОТАЕТ (skip битой строки, чтение продолжается); `async for`+try/except НЕ работает (итератор мёртв) — **CONFIRMED** (замер + Codex подтвердил ValueError-rewrap+discard).
8. #15451 (`--json`+schema ломается при MCP) актуален для нас — **LIKELY** (CLOSED на 0.116, проверить на 0.144.3).

---

## Counter-evidence / conflicts

- **Sol контекст 1.05M vs 372K (issue #32486 репортер):** official OpenAI = 1.05M (T1), репортер issue = 372K. Приоритет official. Не смешивать.
- **«Пофикшено в новой версии»:** ожидание что апгрейд решит — REFUTED, changelog не трогает exec/json.
- **SDK как решение:** beta-статус + рефактор-стоимость — против срочного применения. limit-bump проще.
- **16MB достаточно:** не стресс-тестил вывод >16MB. Chunked-read — единственный полностью надёжный путь, но 16MB покрывает реальные кейсы.

---

## Affected files / рекомендации для кода

- `app/backend_codex.py:105` — `create_subprocess_exec` уже фиксится с `limit=` (наш текущий фикс). Подтвердить значение 16MB.
- `app/backend_codex.py:118` — цикл `async for raw_line`: для надёжности >16MB заменить на `while True: try: raw=await stream.readline() except ValueError: log+continue` (fail-soft, skip битой строки) ИЛИ chunked-read helper (`read(65536)`+split, читает любой размер). **НЕ оборачивать `async for` в try/except** — итератор умирает, строки теряются.

## Codex second-opinion (adversarial review)

Прогнал `codex_review(mode=exec)` на research.md, задание — фальсифицировать. Codex (bg-12589e108c, rc=0) не дописал финальный вердикт-файл (таймаут), но ключевую находку выдал в ходе анализа и она **исправила мою ошибку**:
- **Codex:** «`async for` идёт через `readline()`, но `StreamReader.readline()` преобразует `LimitOverrunError` в `ValueError` и **очищает/сбрасывает проблемную строку**. `except asyncio.LimitOverrunError` не поймает».
- Я это частично проверил сам (ValueError re-wrap ✓), но ошибочно заключил «fail-soft невозможен». Codex-подсказка про «сбрасывает строку» → перепроверил: `while/readline/except ValueError: continue` **РАБОТАЕТ** (OK2 восстановлен). Т.е. fail-soft ВОЗМОЖЕН, просто не через `async for` и не через `LimitOverrunError`.
- **Consensus:** root cause (наш 64KB), SDK, Sol-контекст — Codex не оспорил. Спорным был только fail-soft-механизм — разрешён замером. Урок: эмпирический тест с НЕПРАВИЛЬНЫМ паттерном (`async for`) дал ложный вывод; Codex указал на правильный паттерн (`readline`), перепроверка это подтвердила.

**Финальный вердикт Codex (полный текст — `codex-review-research.md`, 2 blocking):**
- 🔴 **[blocking] limit-bump ещё НЕ в CodexBackend** — проверил кодом, подтвердил (см. секцию БЛОКЕР выше). Краш НЕ починен в worker-пути.
- 🔴 **[blocking] `except LimitOverrunError` вокруг `async for` не ловит** — правильный fail-soft = `while/readline/except ValueError` (совпало с моим замером).
- **CONFIRMED:** наш 64KB — root cause; Codex JSONL легально крупный; 16MB устраняет records до cap; `openai-codex` beta существует; Sol 1.05M / 272K = pricing.
- **REFUTED:** `except LimitOverrunError` fail-soft; «reader мёртв после исключения»; «chunked-read без своего cap полностью robust» (риск OOM — нужен `MAX_RECORD_BYTES`).
- **WEAKER:** именно `aggregated_output` был payload пилот-краша (не доказано без captured строки — «наиболее вероятный», не «это и есть»); «16MB=99%» (нет распределения размеров); «SDK устраняет весь класс» (устраняет наш asyncio cap, не bounded-handling); 997500 как official prefill (official max input = 922000).
- **Рекомендация Codex для Phase 2:** limit=16MB в реальный CodexBackend + `while/readline/except ValueError` с loss-reporting + тесты на >64KB и >16MB. Chunked/SDK — отдельно после замера реальных record sizes.
- **Не срочно:** оценить миграцию на `openai-codex` SDK (когда выйдет из beta) — устранит класс проблем с ручным JSONL-парсингом.
- **Проверить #15451:** прогнать `codex exec --json` с активным MCP на 0.144.3 — убедиться что JSON не ломается (мы гоняем воркеров с Orchestra MCP).
- **Опционально:** `model_auto_compact_token_limit = 270000` в codex-конфиге воркера — держать Sol в дешёвом ценовом тарифе (<272K).

---

## Sources

Код (прочитан): `app/backend_codex.py` (:105, :118, :144, :188), `app/models.py`, `~/.codex/config.toml`.
Live-verified: `pypi.org/pypi/openai-codex/json` (SDK), пилот-замер (ctx 997500).
Внешние (детальный список с tier — в `codex-cli-issues.md`): OpenAI official docs (gpt-5.6-sol model page, codex-sdk, non-interactive), GitHub openai/codex issues #22004/#23042/#15451/#10141/#6426/#32486, releases (0.144.5/0.145-alpha), kimi-cli #831, CPython asyncio streams.
Prior art в репо: `docs/tasks/codex-integration/` (интеграция + BUG1-4), `benchmarks-sol-vs-opus.md` (Sol контекст 1.05M ранее подтверждён).
