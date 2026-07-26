---
name: codex-debate
description: "Cross-LLM adversarial review через Codex (GPT-5.5) — MCP tool codex_review. Персистентные сессии, multi-round debate до консенсуса, Conventional Comments. Триггеры: 'спроси кодекса', 'кодекс ревью', 'ревьюй через кодекса', 'второе мнение', 'cross-review', 'adversarial review', 'переспроси кодекса', 'уточни у кодекса', 'продолжи с кодексом', '/codex', '/codex-debate'. НЕ юзать на тривиальных задачах."
---

# Codex Debate — cross-LLM adversarial review через GPT-5.5

Review плана/кода/решения второй моделью (Codex, GPT-5.5) через MCP tool `codex_review`. Тул сам управляет процессом Codex, сессиями и записью результата — ты только вызываешь его и работаешь с findings.

## Главный принцип — ВТОРОЕ МНЕНИЕ, НЕ ИСТИНА
Codex — другая модель с другими bias'ами. Часто прав, но **не всегда**:
- **Прислушивайся** к каждому замечанию
- **Проверяй** blocking-замечания через код (`grep`/`cat`/read) **перед** тем как принять
- **Спорь** если не согласен — resume сессии с контраргументами из кода (не молча игнорь)
- **Эскалируй юзеру** если Codex просит удалить функционал или сменить архитектуру
- **Не соглашайся слепо** — это обесценивает review

При расхождении для юзера: "Codex говорит X. Я проверил — [согласен / не согласен потому что Y]. Вступить в дебаты?"

## When to use
- "спроси кодекса", "кодекс ревью", "второе мнение", "cross-review", "adversarial review"
- "переспроси/уточни/продолжи с кодексом" → **resume, НЕ новый вызов**
- `/codex` или `/codex-debate`
- Сам предлагаешь review для спорных решений — но **только с явного "да" юзера**

## When NOT to use
- Мелкие/тривиальные правки — трата токенов

## MCP tool: codex_review

```
codex_review(target, output, mode, context, resume)
```
- `target` — файл для review (для `mode="exec"`). Пусто → git diff (`mode="review"`)
- `output` — путь для результата, всегда под `docs/tasks/<id>/`
- `mode` — `"review"` (git diff) или `"exec"` (review конкретного файла)
- `context` — промпт для Codex: задача + PROJECT CONTEXT (см. ниже). ВСЕГДА передавай
- `resume` — `true` → продолжить debate в той же сессии (ключ = тот же `output`). Для follow-up раундов

Тул сам держит persistent-сессию по `output`-файлу, делает resume, пишет результат. Никакого ручного управления UUID/proxy/timeout.

**Review реализации (diff):**
```
codex_review(mode="review", output="docs/tasks/<id>/codex-review-impl.md",
             context="Review the staged git diff for bugs, security, breaking changes, race conditions. <PROJECT CONTEXT>")
```

**Review плана/файла:**
```
codex_review(target="docs/tasks/<id>/plan.md", mode="exec", output="docs/tasks/<id>/codex-review-plan.md",
             context="Review this plan: scope creep, wrong file/function refs, contradictions, security. Max 10 findings. <PROJECT CONTEXT>")
```

**Debate / re-review (тот же output, resume):**
```
codex_review(output="docs/tasks/<id>/codex-review-impl.md", resume=True,
             context="I fixed X and Y. Re-review: for each prior blocking → FIXED / STILL BROKEN / NEW BUG. Append ## Round N.")
```

## Правила вызова
- **`mode="review"` смотрит рабочее дерево.** Если работа уже закоммичена: `git diff <merge-base> HEAD > /tmp/<name>.diff`, затем `codex_review(mode="exec", target="/tmp/<name>.diff", ...)`; иначе получишь `no changes to review` и потеряешь раунд
- **`context` ОБЯЗАТЕЛЕН** — задача + PROJECT CONTEXT. Без него Codex мискалибрует severity
- **Ограничивай ПЕРВЫЙ вызов, не второй.** В `context` сразу: точные файлы/хунки (или несущие утверждения для ресёрча), запрет уходить в logs/BUGS.md/TODO.md/git history, потолок находок. Неограниченный вызов срывается на транспорте → его приходится перезапускать
- **Ревью плана судит ТОЛЬКО текст плана.** Явно пиши: код ещё не написан, не оценивай его по текущему рантайму
- **Не заявляй "Codex прошёл/одобрил" не прочитав `output`-файл.** Не галлюцинируй результат — не видел findings, значит review не состоялся
- **resume для follow-up, НЕ новый вызов** — новый вызов теряет контекст прошлых раундов
- Прочитал `output` → работай с findings (ниже)

## Conventional Comments
Формат замечания: `<prefix>: file:line — проблема → предложение`

| Prefix | Значение |
|---|---|
| `blocking:` | must fix, мерж невозможен. Баги, security, data loss |
| `suggestion:` | рекомендация, не блокирует |
| `question:` | нужен ответ автора |
| `thought:` | мысль вслух, без действия |
| `nit:` | мелочь, можно скипнуть |

## Session concept
- Один review-поток = один `output`-файл. Codex дописывает раунды (`## Round N`) в него, не перезаписывает
- Persistent-сессию (thread) тул хранит сам, привязывая к `output`. Продолжение = `resume=True` с тем же `output`
- Новая тема = новый `output`-файл. НЕ переиспользуй `output` от несвязанного review

## Auto-Iteration to Consensus
После первого раунда — итерируй БЕЗ дёрганья юзера:
1. Прочитай `output`-файл, разбери findings
2. Каждое **blocking** → проверь через код (grep/cat/read). Решение: ACK / DISAGREE / PARTIAL
3. **Эскалируй юзеру** если Codex хочет: удалить функционал / существенно менять архитектуру рабочих компонентов / что-то с неясными последствиями
4. Почини ACK'нутые (Edit)
5. `codex_review(..., resume=True, context="фиксы: <changelog>, re-review")`
6. Codex дописывает Round N
7. Луп пока: Codex пишет "APPROVED"/"no blockers" → готово; сработала эскалация → стоп, спроси юзера

**Потолок 3 раунда.** Раунды 4-5 в истории дали только дубликаты. Раунд 2 обязателен на shared-runtime коде; на прозе — только если есть что перезапустить (иначе он пустой). Дальше решай сам и покажи юзеру.

**Тул падает ≠ вердикт.** Три подряд ИНФРАСТРУКТУРНЫХ падения (таймаут, транспорт, "chunk exceed" — не содержательный ответ) → прекрати долбить. Запиши в `output`-файл честно: вердикта нет, столько-то попыток. Сделай adversarial self-review вместо него. Один повтор разрешён только на существенно другом финальном артефакте.

**Спор, а не молчание.** Не согласен с blocking после проверки кода → resume с контраргументом (факты из кода), итерируй до консенсуса. Recorded-and-ignored blocking = провал.

## Show Result to User
```
Codex review done (rounds: N)
Verdict: <APPROVED / needs work / reject>
Findings: blocking X (Y fixed, Z rejected + причина) · suggestion M (K accepted) · nit skipped
Full: docs/tasks/<id>/codex-review-*.md
Next: OK → continue/push · ещё дебаты → "переспроси кодекса про <X>"
```

## Prompt Templates (для `context`)
**Plan/Spec review:** "Review this plan. Проверь ссылки (файлы, функции, сигнатуры) против кода, scope creep, противоречия, security/race conditions. Max 10 findings, конкретика. Format: ## Summary, ## Findings (Conventional Comments), ## Verdict."

**Code review (diff):** "Review the git diff. Найди баги, security, breaking changes, race conditions. Прочитай изменённые файлы. Не рефакторь рабочий код. Нет замечаний → 'ACK'."

**Debate (не согласен):** "Не согласен с <ID-список>. Аргументы (факты из кода): <...>. Для каждого: ACK / контраргумент с фактами / частично. Append ## Round N."

**Re-review after fix:** "Применены фиксы: <changelog>. Для каждого прошлого замечания: FIXED / STILL BROKEN / NEW BUG. Все blocking закрыты и нет новых → APPROVED. Append ## Round N."

## PROJECT CONTEXT (вставляй в `context`)
```
PROJECT CONTEXT (calibrate severity):
- Stack: Python 3.12+, FastAPI, SQLite, claude-agent-sdk
- Stage: MVP, small team, ~10 users NOT millions
- Philosophy: simple, flat, minimal abstractions. 3 lines > premature abstraction
- "blocking" = crash/corrupt/security. "suggestion" = real improvement. "nit" = skip
```

## What NOT to Do
- НЕ создавай новый вызов на follow-up — используй `resume=True`
- НЕ соглашайся слепо с blocking — проверь через код
- НЕ игнорируй blocking молча — resolve (fix/debate) или эскалируй
- НЕ заявляй "одобрено" не прочитав output-файл
- НЕ дёргай юзера каждый раунд — итерируй до консенсуса (эскалация только на удаление/архитектуру)
- НЕ переиспользуй `output` несвязанного review
