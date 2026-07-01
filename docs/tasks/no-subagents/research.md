# Research — выпилить sub-agents (Task/Agent) у всех агентов

**Дата:** 2026-07-01
**⛔ ОТМЕНЕНО (юзер передумал):** бан субагентов НЕ делаем. Claude Code SDK/промпт зашит
их использовать — бан = деградация (агент натыкается на deny, костылит). Новое направление —
сделать субагентов ВИДИМЫМИ (см. `docs/tasks/subagent-visibility/`). Этот файл — история решения
(почему бан плох + что tasks-pm на субагентах построен). Реализация B откачена.

**Задача (была):** убрать встроенные Task/Agent tools не только у оркестраторов, но у всех (воркеров тоже).

---

## Как сейчас работает (backend_claude.py)

Два независимых механизма блокировки:

1. **`_ORCH_BLOCKED_TOOLS = {"AskUserQuestion", "Agent", "Monitor"}`** — через `can_use_tool` permission callback (`_make_auto_approve`). Только оркестраторы. Ловит `Agent`, но НЕ `Task`.
2. **`_ORCH_DISALLOWED_TOOLS = ["Task", "Agent"]`** — через CLI `disallowed_tools` (`_disallowed_tools`). Только оркестраторы. **Это правильный механизм** — комментарий (стр 37) объясняет: запуск субагента приходит как `TaskStartedMessage`, который permission callback НЕ видит. `disallowed_tools` физически убирает тул из набора.

Логика: `_disallowed_tools(is_orchestrator)` = `_ALWAYS_DISALLOWED` + (если оркестратор) `_ORCH_DISALLOWED_TOOLS`.
- `_ALWAYS_DISALLOWED = [ScheduleWakeup, Cron*, Workflow]` — у всех.
- Воркеры: Task/Agent ОСТАВЛЕНЫ (стр 61: «воркерам — оставляем»).

**is_orchestrator** = из манифеста пайплайна (`kind: orchestrator/worker`).

## Другие backends
- **backend_codex.py** — нет disallowed/subagent логики. Codex CLI не имеет Task/Agent. Ничего не трогать.
- **backend_opencode.py** — то же. Нет Task/Agent. Ничего не трогать.
→ Правка ТОЛЬКО в backend_claude.py.

## Тривиальный фикс (то что просил оркестратор)
Перенести `"Task", "Agent"` из `_ORCH_DISALLOWED_TOOLS` в `_ALWAYS_DISALLOWED`:
```python
_ALWAYS_DISALLOWED = ["Task", "Agent", "ScheduleWakeup", "CronCreate", "CronDelete", "CronList", "Workflow"]
_ORCH_DISALLOWED_TOOLS = []  # или удалить, слить логику
```
Плюс `_ORCH_BLOCKED_TOOLS` можно оставить (Agent там для двойной страховки на orchestrator, но disallowed уже покрывает всех).

---

## ⚠️ БЛОКЕР — конфликт с пайплайном `tasks-pm`

Задача предполагала «может где-то воркеру реально нужен Task — проверь». **ПРОВЕРИЛ. ДА, нужен — целый пайплайн на этом построен.**

`pipelines/tasks-pm/` — активный пайплайн (в гите, рядом с `default`). Его архитектура экономии контекста ЦЕЛИКОМ построена на субагентах:

| Файл | Что говорит |
|------|-------------|
| `roles/secretary.md:102,109` | secretary (**kind=worker**) — «Subagents через Task — можно», «прочитай 20 файлов → спавни субагента через Task tool, не пожирай контекст» |
| `roles/worker.md:3` | «Можешь использовать субагентов (Agent) для поиска/анализа» |
| `roles/analyst.md:2` | «нанимаешь воркеров-исследователей (они юзают субагентов)» |
| `roles/tester.md:2` | «чтение всех отчётов делаешь через воркеров/субагентов» |
| `roles/base-orchestrator.md:2` | «спавнишь воркера (он юзает субагентов)» |
| `_pipeline.md:12` | «нанимай воркера-секретаря (он юзает субагентов)» |

**Стратегия tasks-pm:** оркестратор (Opus, дорогой контекст) делегирует рутину секретарю/воркеру, а тот через Task-субагенты читает пачку файлов, НЕ раздувая контекст. Это осознанный дизайн, не случайность.

Если тупо перенести Task/Agent в `_ALWAYS_DISALLOWED` → **весь tasks-pm сломается**: секретарь и воркеры этого пайплайна потеряют инструмент, на который завязаны их промпты.

`default` пайплайн (наш, где я = full-cycle worker) — субагенты НЕ использует, для него бан безопасен и полезен (юзер словил зависание именно тут).

---

## Варианты решения (нужно решение оркестратора/юзера)

### A. Блок для всех БЕЗ исключений (как просил оркестратор буквально)
Перенести в `_ALWAYS_DISALLOWED`. Просто, но **ломает tasks-pm** (секретарь/воркеры теряют Task).
+ максимальная простота, детерминизм.
− tasks-pm пайплайн деградирует: его роли начнут жечь контекст оркестратора (то, от чего секретарь и спасал). Надо будет чистить 6 промптов tasks-pm.

### B. Блок для всех КРОМЕ ролей, которым субагенты нужны by design (per-role opt-in)
Роль в пайплайне может объявить `allow_subagents: true` (только secretary/worker в tasks-pm). Дефолт — запрещено.
+ не ломает tasks-pm, чистый бан для default.
− +1 механизм (поле в манифесте + проброс в backend). Против «минимум абстракций», но это 1 флаг, не абстракция.

### C. Блок по пайплайну: default → бан, tasks-pm → как есть
Читать из pipeline manifest флаг на уровне пайплайна.
− грубее B, тот же оверхед.

---

## Рекомендация

**Спросить оркестратора/юзера — это его territory-решение, не моё.** Причина: задача явно про «юзер словил зависание» в **default** пайплайне (full-cycle worker запустил Task на pytest). Проблема РЕАЛЬНА для default. Но tasks-pm СПЕЦИАЛЬНО построен на субагентах.

Мой технический совет: **Вариант B (per-role opt-in `allow_subagents`)** — 1 флаг в манифесте, дефолт `false` (бан у всех), tasks-pm secretary/worker ставят `true`. Это:
- чинит боль юзера (default воркеры без Task),
- не ломает рабочий tasks-pm,
- детерминистично и явно (роль ДЕКЛАРИРУЕТ что ей нужны субагенты).

Если юзер скажет «tasks-pm не нужен / выпиливаем субагентов ВЕЗДЕ жёстко» → Вариант A + чистка 6 промптов tasks-pm (убрать инструкции про Task, заменить на «читай сам через grep/Serena»).

**НЕ реализую пока — жду решения A/B/C.** Тривиальный перенос 2 строк оказался НЕ тривиальным из-за tasks-pm.

## Файлы под правку (по вариантам)
- **A:** `backend_claude.py` (перенос 2 строк) + `pipelines/tasks-pm/prompts/{secretary,worker,analyst,tester,base-orchestrator}.md` + `_pipeline.md` (убрать Task-инструкции).
- **B:** `backend_claude.py` (читать флаг) + `app/pipeline.py` (поле `allow_subagents` в ResolvedRole) + `app/manager.py` (проброс в backend) + `pipelines/tasks-pm/pipeline.yaml` (secretary/worker: allow_subagents=true).
- Общее: `pipelines/default/prompts/base.md:46` уже говорит «NEVER use built-in Agent» — оставить.
