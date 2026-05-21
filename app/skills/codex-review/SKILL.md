---
name: codex-review
description: "Cross-LLM ревью через Codex CLI (GPT-5.5). Codex ревьюит план/код/diff, запускает тесты, пишет результат в CODEX_REVIEW_*.md. Персистентные сессии для debate. Триггеры: 'спроси кодекса', 'кодекс ревью', 'ревьюй через кодекса', 'второе мнение', 'cross-review', 'переспроси кодекса', 'уточни у кодекса', '/codex'. НЕ юзать на тривиальных задачах."
roles: [all]
integrations: []
---

# Codex Review — cross-LLM ревью через GPT-5.5

## Purpose
Adversarial review плана/кода/решения через Codex CLI. Codex исследует код, запускает тесты, пишет результат в `CODEX_REVIEW_*.md` — юзер читает сам.

## Главный принцип — ВТОРОЕ МНЕНИЕ, НЕ ИСТИНА

Codex — другая модель с другими bias'ами. Он **часто прав** (100% accuracy на тестах 24.04), но **не всегда**. Claude Code должен:
- **Прислушиваться** к каждому замечанию
- **Проверять** blocking-замечания через код (`ls`, `grep`, `cat`, Serena) перед тем как принять
- **Спорить** если не согласен — через resume сессии с контраргументами
- **Показывать юзеру** и свою позицию, и позицию Codex'а при расхождении
- **Не соглашаться слепо** — это обесценивает весь cross-LLM review

При несогласии формат: "Codex говорит X. Я проверил — [согласен/не согласен потому что Y]. Хочешь чтобы я вступил в дебаты с ним?"

## When to Invoke
- "спроси кодекса", "кодекс ревью", "ревьюй через кодекса"
- "второе мнение", "cross-review", "adversarial review"
- "переспроси кодекса", "уточни у кодекса" → resume сессии
- `/codex`
- **АВТОМАТИЧЕСКИ после каждого фикса/изменения кода** — не пушить без хотя бы одного раунда Codex. Исключение: тривиальные правки (1-2 строки конфиг/docs). Workflow: код → тесты → Codex review → фикс замечаний → push.

## Главные правила

1. **OUTPUT В ПАПКУ ФИЧИ** — Codex пишет в `docs/<feature-slug>/CODEX_REVIEW.md` (рядом с PLAN.md). Все раунды в одном файле (append секции `## Round N`). Если фичи-папки нет — создать. **НЕ в корень cwd**, НЕ россыпью в docs/.
2. **ТЕСТЫ ПО СИТУАЦИИ** — если проект Python с pytest → запустить. Если план/ТЗ без кода или не-Python → пропустить и написать "тесты не применимы"
3. **CONVENTIONAL COMMENTS** — формат замечаний
4. **RESUME НЕ НОВАЯ СЕССИЯ** — follow-up через `codex exec resume`

## Формат замечаний (Conventional Comments)

- **`blocking:`** — must fix, мерж невозможен. Баги, security, data loss.
- **`suggestion:`** — рекомендация. Не блокирует мерж.
- **`question:`** — нужен ответ автора.
- **`thought:`** — мысль вслух, не требует действия.
- **`nit:`** — мелочь, опциональна.

## Process Flow

### Pre-Flight
1. `command -v codex >/dev/null 2>&1` — если нет → стоп
2. `mkdir -p /tmp/codex-sessions`
3. Определить slug: sanitize к `[a-zA-Z0-9._-]`, max 50 chars
4. **Папка фичи**: `docs/<feature-slug>/` — создать если нет. Plan тоже должен лежать тут (`PLAN.md`).
5. Output файл: `docs/<feature-slug>/CODEX_REVIEW.md`
6. JSONL лог: `/tmp/codex-sessions/<slug>.jsonl` (slug-specific, не глобальный)
7. **ОДИН SLUG НА ВСЮ СЕССИЮ** — slug определяется ОДИН раз в Pre-Flight и используется **везде**: JSONL, `.session`, resume, debate. НЕ придумывать новое имя при resume/debate. Slug = имя папки фичи в `docs/`. Если `docs/seo-full-review/` → slug = `seo-full-review` ВЕЗДЕ: `/tmp/codex-sessions/seo-full-review.jsonl`, `/tmp/codex-sessions/seo-full-review.session`. Ошибка "session not found" при resume на 99% — использовал другой slug чем при создании.

### Структура docs/
```
docs/
  <feature-slug>/     ← 1 фича = 1 папка
    PLAN.md           ← план/ТЗ
    CODEX_REVIEW.md   ← ревью (все раунды)
  archive/            ← завершённые/устаревшие фичи
  <живые справочники>.md  ← VICTORIA_MASTER.md, QA, bridge-setup и т.п.
```
При завершении фичи (merged + deployed) → `mv docs/<slug>/ docs/archive/`

### Новая сессия

Prompt передавать через heredoc (безопасный quoting):
```bash
cd <проект>
codex exec -s workspace-write --json - <<'CODEX_PROMPT' 2>&1 | tee /tmp/codex-sessions/<slug>.jsonl
<промпт здесь>
CODEX_PROMPT
```

Модель и reasoning берутся из `~/.codex/config.toml`. Если нужно override:
```bash
codex exec -s workspace-write -m gpt-5.5 -c model_reasoning_effort="high" --json - <<'CODEX_PROMPT'
```

Сохранить session_id (robust parsing):
```bash
SESSION_ID=$(jq -r 'select(.type=="thread.started") | .thread_id' /tmp/codex-sessions/<slug>.jsonl 2>/dev/null | head -1)
if [ -z "$SESSION_ID" ]; then
  SESSION_ID=$(grep -oP '"thread_id":"\K[^"]+' /tmp/codex-sessions/<slug>.jsonl | head -1)
fi
test -n "$SESSION_ID" && echo "$SESSION_ID" > /tmp/codex-sessions/<slug>.session
```

### Resume сессии

```bash
SESSION_ID=$(cat /tmp/codex-sessions/<slug>.session)
codex exec resume "$SESSION_ID" --skip-git-repo-check --json - <<'CODEX_PROMPT' 2>&1 | tee -a /tmp/codex-sessions/<slug>.jsonl
<follow-up промпт>
CODEX_PROMPT
```

`-s` у resume НЕ работает — sandbox наследуется. Prompt через stdin (`-`).

### После завершения — АВТОМАТИЧЕСКАЯ ИТЕРАЦИЯ ДО КОНСЕНСУСА

**НЕ спрашивать юзера "спорить или принять?" — ДУМАТЬ СВОЕЙ ГОЛОВОЙ и итерировать.**

1. Прочитать ревью, **проверить каждое замечание** через код
2. По каждому пункту САМОСТОЯТЕЛЬНО решить: ACK / DISAGREE / PARTIAL — с аргументами из кода
3. Обновить план/код по принятым замечаниям
4. Resume сессию Codex с изменениями — показать что исправлено, спросить APPROVED/NOT YET
5. **Повторять шаги 1-4 пока Codex не скажет APPROVED** или 5+ раундов без прогресса
6. Только после консенсуса — показать юзеру финальный результат

**Принцип:** Claude Code = инженер, не секретарь. Сам принимает решения по замечаниям, сам спорит где не согласен, сам итерирует. Юзера не дёргать на каждый раунд — показать готовый согласованный результат.

## Язык

**Codex пишет ревью на языке юзера.** Если юзер общается на русском — в промпте Codex добавляй: "Напиши ревью на русском языке." Если на английском — не добавляй (дефолт английский). Codex может думать на любом языке, но output = язык юзера.

## ВСЕГДА В ФОНЕ

**Codex ВСЕГДА запускается в background** (`run_in_background: true` в Bash). Пока Codex работает — продолжай другие задачи. Когда завершится — придёт уведомление, тогда читай результат и итерируй. НЕ блокировать основной поток ожиданием Codex.

## Workflow после ревью ПЛАНА

**После получения ревью плана — НЕ показывать юзеру и ждать. Действовать:**
1. Прочитать ревью, проверить каждый blocking через код
2. **Обновить план** по принятым замечаниям — Edit файл плана
3. **Resume Codex** с обновлённым планом — "I fixed N issues, re-review the plan"
4. Повторять пока Codex не скажет "план рабочий" / APPROVED
5. Только после консенсуса — показать юзеру финальный план

**Для ревью кода** — то же: фиксить → resume → re-review → консенсус.

## Project Context — ОБЯЗАТЕЛЬНО добавлять в каждый промпт Codex

Codex не знает масштаб проекта и ревьюит как enterprise. Чтобы не приколупывался к мелочам — **ВСЕГДА** добавлять блок контекста в начало промпта:

```
PROJECT CONTEXT (calibrate your review severity accordingly):
- Scale: 1 client (Александр), 1 developer (Максим), MVP stage
- Users: ~10 active, NOT millions. No horizontal scaling needed
- Stack: {стек проекта}
- Philosophy: "Pit of Success" — simple, flat, minimal abstractions. 3 lines > premature abstraction
- What matters: correctness, security, data integrity
- What does NOT matter: enterprise patterns, scalability to 1M users, 100% test coverage, perfect error messages, logging best practices
- Do NOT suggest: dependency injection frameworks, message queues (unless already used), caching layers for <1000 QPS, complex error hierarchies, monitoring/alerting infrastructure
- Severity calibration: "blocking" = will crash/corrupt data/security hole. "suggestion" = real improvement. "nit" = skip entirely, we don't care about style/naming/comments
```

**Зачем:** без этого Codex на ревью 200 строк MVP-фикса выдаёт 15 suggestions про "добавьте retry policy", "нужен circuit breaker", "логирование недостаточно structured" — всё верно для Netflix, бесполезно для нас.

**Адаптировать под проект:** parsing-hub (FastAPI+Redis), seo-platform (FastAPI+PostgreSQL), ai-assistants (FastAPI+SQLite+Asterisk), zahoron-laravel (Laravel 10+MySQL).

## Промпты

### Review плана/ТЗ
```
Ты adversarial code reviewer. В cwd — <проект> (<стек>).

Шаг 1: Прочитай <файл>.
Шаг 2: Исследуй живой код через ls/grep/cat — проверь все ссылки из плана.
Шаг 3: Определи есть ли тесты (ls tests/ или ls test/). Если есть и проект Python — запусти. Если нет или не Python — напиши "тесты не применимы".
Шаг 4: Напиши ревью в <OUTPUT_FILE>.

Формат файла:
## Tests
Результат тестов или "не применимо".

## Summary
3-5 предложений.

## Замечания
`blocking:` / `suggestion:` / `question:` / `thought:` / `nit:` — file:line + проблема + фикс.

## Вердикт
Одна фраза: план рабочий / требует доработки / выкинуть.

Ищи:
1. Scope creep
2. Неверные ссылки на код (проверяй ls/grep, не угадывай)
3. Внутренние противоречия
4. Security / архитектурные проблемы
5. Нарушения бизнес-правил (прочитай CLAUDE.md если есть)

До 10 замечаний. Конкретика. Без воды.
```

### Review кода (diff / uncommitted)
```
Ты adversarial code reviewer. В cwd — <проект>.

Шаг 1: Определи test runner: ищи pyproject.toml/package.json/Makefile. Запусти если найдёшь.
Шаг 2: Посмотри diff: `git diff` или `git diff <base>...HEAD`.
Шаг 3: Прочитай новые/изменённые файлы.
Шаг 4: Найди баги, security, breaking changes, race conditions, null safety.
Шаг 5: Напиши ревью в <OUTPUT_FILE>.

Формат: ## Tests, ## Summary, ## Замечания (blocking/suggestion/question/nit), ## Вердикт (ACK / требует фиксов).
Не предлагай рефакторинг если старый код работает.
```

### Debate (при несогласии Claude)
```
Claude Code не согласен с твоими замечаниями. Вот его аргументы:

<аргументы Claude>

Проверь каждый пункт:
- ACK — принимаю, Claude прав
- Контраргумент — не согласен, вот почему (с фактами из кода, не "мне кажется")
- Частично — что принято, что нет

Допиши в <OUTPUT_FILE> секцию ## Debate Round N.
```

## Fix → Re-review Loop

Когда Codex находит баги и Claude фиксит:

1. **Пофиксить** все blocking/suggestion замечания
2. **Resume сессию** — НЕ новая, чтобы Codex помнил контекст:
```bash
SESSION_ID=$(cat /tmp/codex-sessions/<slug>.session)
codex exec resume "$SESSION_ID" --skip-git-repo-check --json - <<'CODEX_PROMPT'
I fixed your N findings. For each say FIXED or STILL BROKEN.
Then list any NEW bugs introduced by the fixes.

Changes: <краткий список что поменял>
CODEX_PROMPT
```
3. **Проверить ответ**: FIXED/BROKEN по каждому пункту
4. **Если BROKEN или NEW bugs** → фиксить → повторить шаг 2
5. **Если все FIXED + no new blockers** → консенсус, мерж

### Когда остановиться
- Codex сказал "merge-ready" / "no remaining blockers" — консенсус
- 7+ раундов без прогресса — diminishing returns, решай сам
- Остались только `nit:` / `thought:` — можно мержить

### Важно
- Каждый раунд фиксов может **создать новые баги** — Codex это ловит
- Не соглашаться на всё — если Codex неправ, спорить с аргументами
- Показывать юзеру scorecard: "Round N: X fixed, Y still broken, Z new"

## Error Handling

- **codex не найден** → "Codex CLI не установлен"
- **rate limit** → показать ошибку, стоп, не ретраить
- **файл не создался** → показать последние 20 строк `/tmp/codex-sessions/<slug>.jsonl`
- **resume упал на протухшей сессии** → удалить `.session` файл, начать заново
- **tee: No such file or directory** → slug в `tee` не совпадает со slug из Pre-Flight. ВСЕГДА проверять: имя файла в `tee /tmp/codex-sessions/XXX.jsonl` == slug из шага 3. Если ошибся → JSONL ушёл в stdout, session_id потерян, resume невозможен. Перезапустить с правильным slug.
- **таймаут** → в Claude Code Bash tool ставить `timeout: 300000` (это параметр Claude Code, не codex CLI)

## Технические детали

- **Модель и reasoning:** из `~/.codex/config.toml` (сейчас `gpt-5.5`, `high`)
- **Sandbox:** `workspace-write` (чтобы мог писать файл ревью)
- **Approval:** `codex exec` = автономно (`--ask-for-approval=never` дефолт)
- **Sessions:** `/tmp/codex-sessions/<slug>.session` → thread_id, `.jsonl` → полный лог
- **Serena MCP:** подключена к Codex — может юзать LSP-навигацию
- **Лимиты Plus:** 30-150 локальных / 5 часов
- **Security:** при `workspace-write` Codex может читать файлы в cwd. НЕ запускать в директориях с `.env`, credentials, SSH-ключами. Если нужно — предварительно проверить `ls -a` на наличие секретов

## Что НЕ делать

- ❌ Не показывать сырой JSONL — только путь к файлу + краткий пересказ
- ❌ Не создавать новую сессию на follow-up — resume
- ❌ Не забывать "напиши в файл" в промпте
- ❌ Не соглашаться слепо — проверять blocking-замечания через код
- ❌ Не использовать `danger-full-access`
- ❌ Не запускать в директориях с секретами при workspace-write
