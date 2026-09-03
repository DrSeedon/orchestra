# Plan: R1 (prompt-split spawn vs built-in) + R2 (orphan-guard)

**Scope:** только R1 + R2 (одобрено оркестратором). R3-R5 отложены.
**База:** research.md (Phase 1), правки после Codex учтены.

---

## R1 — промпт-развод: spawn_worker vs built-in Agent (full-cycle.md)

**Проблема (research R1):** у full-cycle воркера ДВА пути параллелизма — `spawn_worker` (MCP, CLI-процесс + worktree, виден на дашборде) и built-in `Agent`/`Task` (in-process субагент, эфемерный, невидим). Промпт про это молчит → нарушение Agent Determinism «1 задача = 1 workflow». Реальный кейс: `global-job-researcher` заспавнил 3 CLI-воркера для research-fan-out, хотя built-in `Agent` подошёл бы (дешевле по процессам, эфемерно).

**Что делаю:** добавляю в `full-cycle.md` короткий блок с decision-tree. НЕ переписываю пайплайн, хирургически добавляю секцию.

**Где:** после `<code-quality>` блока (конец файла), новый блок `<parallelism>`.

**Содержание (decision-tree, детерминированный, без «реши сам»):**
- **Эфемерный fan-out** (параллельный поиск по N источникам, быстрый сбор данных, разведка кода, verify-прогоны — результат нужен СЕЙЧАС и сворачивается назад) → **built-in `Agent`/`Task`**. Дешевле (общий repo, результат summary наверх), эфемерно, авто-cleanup. Уже используется в Phase 1 (Explore/general-purpose субагенты).
- **Долгоживущая видимая работа по тикетам** (имплементация модуля часами, нужен дашборд/resume/TG/отдельный worktree, работа должна пережить твой compact) → **`spawn_worker`**. Виден в DB/на дашборде, персистентен, изолирован worktree.
- **Правило по умолчанию:** сомневаешься → built-in `Agent` (дешевле, проще). `spawn_worker` — только когда явно нужна видимость/персистентность/worktree-изоляция.
- **Не смешивай на одной подзадаче.** Одна подзадача = один механизм.

**AC:** блок присутствует в full-cycle.md, содержит оба пути с чёткими триггерами, правило-по-умолчанию, запрет смешивания. НЕ трогает остальной промпт.

**Что НЕ делаю:** не трогаю worker.md (обычный worker и так не спавнит — research F2; и оркестратор просил только full-cycle). Не меняю pipeline.yaml.

---

## R2 — orphan-guard: kill родителя с живыми детьми → block

**Проблема (research R2/F6.2):** `delete_session` не проверяет живых детей. Убьёшь родителя → дети-сироты (parent_name на archived-строку, живут до ручного kill). Асимметрия: `change_orchestrator_scope` (manager.py:642) БЛОКИРУЕТ при живых воркерах, kill — нет.

**Что делаю:** зеркалю гейт из `change_scope`. Новый хелпер `_live_children(parent_name, scope)` в manager.py (по образцу `_live_workers_in_scope`), вызов в `delete_session` route внутри `if not force:`.

**Файлы:**
1. `app/manager.py` — новый метод `_live_children(self, parent_name, scope) -> list[str]`:
   - Скан in-memory `self.sessions` + DB `get_all_sessions(scope)`, dedup по id.
   - Фильтр: `parent_name == parent` И статус в `("idle","running","waiting")`.
   - Возврат sorted списка имён. (1:1 структура `_live_workers_in_scope`, только критерий parent вместо not-orchestrator.)
2. `app/routes/sessions.py` — в `delete_session`, в блоке `if not force:`, ПЕРЕД git-проверками (быстрая проверка in-memory/DB дешевле git-subprocess):
   ```python
   children = manager._live_children(name, scope)
   if children:
       return JSONResponse({"error": f"worker has {len(children)} live child worker(s): {', '.join(children)}. Kill or merge them first (or force=true)"}, status_code=400)
   ```

**Поведение:**
- `force=True` → пропускает (как и остальные kill-гейты). Оркестратор/юзер может форсить.
- Дети с parent_name=этот воркер и статусом idle/running/waiting → block с именами.
- Archived/error/starting дети → НЕ блокируют (не «живые»).

**AC:**
- kill воркера с живым (idle/running) ребёнком без force → HTTP 400 с именами детей.
- kill того же воркера с `force=true` → проходит (204/ok).
- kill воркера без детей → как раньше (проходит через git-гейты).
- kill воркера, у которого дети только archived → проходит (не блокирует).
- `_live_children` ловит и unloaded-but-active детей из DB (как `_live_workers_in_scope`).

**Что НЕ делаю (surgical):** НЕ cascade-kill (оркестратор сказал «block», не cascade). НЕ трогаю change_scope. НЕ трогаю MCP kill_worker (force уже плюмбится). НЕ добавляю depth-limit (R3, отложено).

---

## Tickets

### T1 — R2 orphan-guard (manager helper + kill route)
- Files: `app/manager.py` (+ `_live_children`), `app/routes/sessions.py` (guard в delete_session)
- AC:
  - kill воркера с idle/running ребёнком без force → 400 + имена детей
  - kill с force=true → проходит
  - kill без детей / только archived дети → проходит
  - тест: pytest на guard (block + force-override + no-children)
- blocked-by: none

### T2 — R1 prompt-split (full-cycle.md)
- Files: `pipelines/default/prompts/roles/full-cycle.md` (+ `<parallelism>` блок)
- AC: блок с decision-tree (built-in Agent для fan-out / spawn_worker для видимого-персистентного / default=built-in / не смешивать), не трогает остальной промпт
- blocked-by: none (независим от T1)

Порядок: T1 (код+тест) → T2 (промпт). Оба независимы, но T1 первым (несёт тест).

---

## Риски / adversarial self-review
- **R2-a:** `_live_children` может не поймать ребёнка в статусе `starting` (спавнится прямо сейчас) → TOCTOU. Но `change_scope` имеет ту же дыру (комментарий manager.py:654 «Full closure needs a scope-level spawn lock»). Принимаю тот же уровень — не хуже существующего гейта. Статус `starting` кратковременный; force остаётся аварийным выходом.
- **R2-b:** ребёнок в другом scope (родитель сменил scope?) — `_live_children(name, scope)` фильтрует по scope kill-запроса. Дети всегда в том же scope что родитель (research F3.1, scope наследуется). ОК.
- **R2-c:** имя-коллизия parent_name (два воркера с одним именем в разных scope) — фильтр по scope разводит. ОК.
- **R1-a:** промпт может раздуть контекст full-cycle. Держу блок коротким (~12 строк), в стиле существующих `<rules>`.
