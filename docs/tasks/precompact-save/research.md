# Pre-Compact Context Save — Research

**Дата:** 2026-06-01 · research-only · `app/session.py compact()`

## TL;DR
Текущий `compact()` УЖЕ генерирует summary в полном контексте (до reset). Лучший вариант — **C-гибрид с уклоном в A, но БЕЗ лишнего turn'а**: расширить существующий COMPACT_PROMPT так, чтобы агент СНАЧАЛА сохранил неструктурированное (решения → CLAUDE.md, research → docs/) файловыми тулами, ПОТОМ выдал summary — всё в ОДНОМ summary-turn'е. Server-side extraction (B) для tasks/bugs — **хрупкое** (логи хранят tool-вызовы как текст, не структуру), оставить как опциональный bonus, не основа. Только для оркестраторов/sub-orch (`is_orchestrator` — готовое поле). Effort: **~0.5-1 день** (промпт + гейт), B-часть +1 день если делать.

---

## 1. Текущий compact flow (факты, session.py:768)

```
compact():
  1. COMPACT_PROMPT → backend.send() → агент пишет handoff summary  ← ПОЛНЫЙ КОНТЕКСТ ещё здесь (805-812)
     (INTENT/DECISIONS/FILES/PENDING/RECENT/BUGS/IMPORTANT)
  2. summary собирается из text-событий
  3. backend.disconnect() → backend=None                            ← RESET (818-819)
  4. _ensure_backend(force_fresh=True) → новая сессия               ← fresh (840)
  5. PREAMBLE(summary) инжектится в новую сессию, "Acknowledge briefly" (841-842)
  6. ждёт ack (60s timeout)
```

**🔑 Критический инсайт:** summary пишется в ШАГЕ 1, когда агент ещё в полном контексте. Значит "сохранить контекст перед compact" — это НЕ обязательно +1 turn. Можно расширить COMPACT_PROMPT: "сначала сохрани в файлы через Edit/Write, потом выдай summary". Агент сделает file-saves + summary в ОДНОМ turn'е. Вариант A из задачи («+1-2 turn'а») переоценивает стоимость — отдельный turn не нужен.

## 2. Можно ли парсить логи для extraction (вариант B)?

**Схема `logs`** (db.py:66): `session_id, ts, type, content` — только текст, без структуры.
**Как логируется tool** (backend_claude.py:243-248): `inp = json.dumps(block.input)`, контент = `f"{block.name}: {inp}"`. То есть в логе: `type='tool'`, `content='task_create: {"title": "...", ...}'`.
- `metadata={"tool_name": ...}` ЕСТЬ в событии, но в БД-лог **не сохраняется** (схема не хранит metadata).

**Вывод по B:** extraction возможен, но через regex: `WHERE type='tool' AND content LIKE 'task_create:%'` → отрезать префикс → `json.loads` хвоста. **Хрупко**: завязано на текстовый формат `"{name}: {json}"`, который может смениться. Распарсит task_create/report_bug аргументы, но НЕ поймёт "ключевые решения" (они в свободном тексте ассистента, `type='text'`). Детерминистично для структурного, бесполезно для смыслового.

## 3. Стоимость доп-turn'а
- `max_tokens=200000`, compact обычно при ~80-90% → **~160-180k токенов контекста** на момент summary.
- Текущий summary-turn УЖЕ платит за этот контекст (агент читает всё, пишет summary). 
- **Расширение COMPACT_PROMPT (A-в-одном-turn'е): +0 turn'ов**, только +N токенов на file-writes (Edit/Write tool calls) в том же turn'е. Дёшево.
- **Отдельный pre-compact turn (наивный A): +1 полный turn** на ~170k контекста = дорого (повтор чтения всего контекста). Избегать.
- Напоминание: подписка Max 20x → токены виртуальные. Но лишний turn = время (latency) + риск затупа, это реальные минусы даже на подписке.

## 4. Только оркестраторы/sub-orch
`is_orchestrator` (session.py:178) — готовое property (`is_orchestrator_role(role)`). Гейт тривиален: `if self.is_orchestrator: <extended prompt>`. Воркерам — текущий обычный COMPACT_PROMPT (у них задача конкретная, контекст в docs/tasks/ уже пишется по пайплайну).

---

## 5. Рекомендация: Вариант C (гибрид), реализованный экономно

**Не наивный A (+turn) и не чистый B (хрупкий парсинг). Гибрид:**

### Часть 1 — LLM сохраняет неструктурированное (основа, дёшево)
Расширить COMPACT_PROMPT **только для оркестраторов**: перед выдачей summary агент сохраняет в файлы то, что не переживёт reset:
```
[добавка к COMPACT_PROMPT для is_orchestrator]
BEFORE writing the summary, persist anything that must survive the reset:
1. Key decisions / patterns discovered → append to CLAUDE.md (project root)
2. Active research/context not yet in docs/ → docs/tasks/<relevant>/ or docs/
3. (TODO.md / BUGS.md only if you have open items not already written)
Use Edit/Write. Then output the summary as specified below.
```
- Один turn (тот же summary-turn). LLM сама решает что важно (плюс варианта A).
- Файлы переживают reset (summary — нет, он только в preamble следующей сессии).

### Часть 2 — server-side bonus для structured (опционально, не блокер)
ПОСЛЕ summary, до reset, дёшево распарсить логи текущей сессии:
- `get_logs(session_id, type='tool')` → regex `^(task_create|task_update|report_bug):` → собрать список → НЕ перезаписывать файлы (LLM уже мог), а добавить в summary preamble строку "Structured this session: created tasks #X #Y, reported bug Z" как страховку.
- Это НЕ источник истины (хрупко), а резервная сводка в preamble. Если LLM забыл — хоть что-то.

**Почему C, а не чистый A:** A через расширение промпта — ядро C. B-парсинг — дешёвая страховка поверх. Чистый B нельзя как основу (не поймёт решения). Наивный A с +turn — дорого и лишнее, т.к. summary-turn уже в полном контексте.

---

## 6. План имплементации (НЕ выполнен)

**Файл: `app/session.py`, метод `compact()`**
1. Вынести добавку промпта в константу `_ORCH_PRECOMPACT_SAVE` (текст из Части 1).
2. В `compact()`: `prompt = COMPACT_PROMPT if not self.is_orchestrator else _ORCH_PRECOMPACT_SAVE + COMPACT_PROMPT`. Одна строка, один гейт.
3. (Опц. Часть 2) после сбора summary, до disconnect: вызвать helper `_extract_structured_from_logs(session_id)` → regex по `get_logs(type='tool')` → дописать в `summary` строку-сводку. ~30 строк, изолированный helper.

**Что НЕ трогать:**
- Reset/preamble механику (работает).
- Воркерский путь — обычный COMPACT_PROMPT.
- БД-схему logs — не добавлять metadata-колонку ради этого (overkill; regex по content достаточно для bonus).

**Риски/edge:**
- LLM при расширенном промпте может потратить turn на file-writes и НЕ дописать summary (timeout). Митигация: в промпте явно "Then output the summary" + summary остаётся обязательным; если пусто → текущий fallback "empty summary" сработает.
- File-writes идут в worktree оркестратора (его cwd) — CLAUDE.md в корне проекта оркестратора. Проверить, что cwd оркестратора = project root (не worktree воркера). 
- Гонок нет: всё в существующем `_lifecycle_lock`.

**Effort:**
- Часть 1 (промпт + гейт): **~0.5 дня**. Низкий риск (только промпт + 1 if).
- Часть 2 (server-side extraction bonus): **+~1 день**. Средний риск (regex-парсинг, тесты на формат лога).
- Рекомендую сделать СНАЧАЛА Часть 1 (даёт 80% ценности), Часть 2 — отдельным инкрементом если Часть 1 покажет, что LLM что-то стабильно забывает.

---

## Итог
- **Вариант: C-гибрид, но экономный** — A-расширение существующего summary-turn'а (ядро) + опциональный server-side bonus (страховка). НЕ наивный A с лишним turn'ом, НЕ чистый B.
- **Effort: 0.5 дня** (Часть 1, основная ценность) + 1 день (Часть 2, опционально).
- **Гейт: `is_orchestrator`** — готов, воркеров не трогаем.
- Главная экономия мысли: summary уже в полном контексте → сохранение файлов встраивается в тот же turn, а не отдельным.
