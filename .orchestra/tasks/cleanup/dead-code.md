# Dead code cleanup — research + доказательства

**Дата:** 2026-07-01
**Задача:** удалить доказанно мёртвое. Territory: app/prompts/, models.py, tg_bridge.py, app.js, sessions.py, pipeline.py.

---

## ⛔ ГЛАВНАЯ НАХОДКА: `app/prompts/` — НЕ МЁРТВАЯ. НЕ УДАЛЯТЬ ЦЕЛИКОМ.

Разведка оркестратора ошибочна. `app/prompts/` активно читается через **`app/prompting.py`** — это **upstream-fallback путь сборки промптов**.

### Доказательство (grep + трассировка)
`app/prompting.py:13` → `_PROMPTS_DIR = Path(__file__).parent / "prompts"` = `app/prompts`. 12 функций читают её:
| Функция | Внешних вызовов | Читает app/prompts |
|---------|-----------------|--------------------|
| `is_orchestrator_role` | 15 | нет (чистая) |
| `role_can_spawn` | 11 | ✅ roles/*.md |
| `prompt_template_hash` | 5 | ✅ |
| `read_prompt` | 4 | ✅ base.md |
| `role_prompt_file` | 4 | ✅ roles/*.md |
| `safe_format_prompt` | 4 | нет |
| `inject_skills_to_worktree` | 3 | ✅ skills/*.md |
| `skills_catalog`/`get_role_icons`/`roles_catalog`/`_load_modules`/`parse_role_frontmatter` | 2 каждая | ✅ |

### Где именно живёт (manager.py:193-207)
```python
try:
    base = build_system_prompt(pipeline, role, scope)   # ПЕРВИЧНЫЙ: pipelines/<name>/prompts/
except (FileNotFoundError, KeyError):
    return _UPSTREAM_ROLE_SYSTEM_PROMPT(role, scope)     # FALLBACK: app/prompts/ (read_prompt+role_prompt_file)
```
`_UPSTREAM_ROLE_SYSTEM_PROMPT` (manager.py:123) читает `app/prompts/base.md` + `role_prompt_file` + `roles_catalog` + `skills_catalog` — ВСЁ из app/prompts.

**Fallback срабатывает когда:** нет манифеста пайплайна (FileNotFoundError) ИЛИ роль не в манифесте (KeyError). Для default-пайплайна с известной ролью — не срабатывает. НО:
- `sessions.py:147` `get_session_prompt` (дашборд «показать промпт») ВСЕГДА зовёт `read_prompt("base.md")` → app/prompts/base.md. Удаление → base="" → дифф-логика промпта в дашборде ломается.
- `system.py:283` `get_role_icons()` → читает app/prompts/roles/*.md для иконок ролей.
- `app/prompts/base.md` **ОТЛИЧАЕТСЯ** от pipelines/default/prompts/base.md (не дубль).

### Вердикт по app/prompts
**НЕЛЬЗЯ просто удалить.** Варианты:
- **A (безопасный, рекомендую):** оставить app/prompts как есть — это легитимный fallback + источник для дашборд-визуализации/иконок. НЕ мёртвый код. Пометить в pipeline.py что комменты «игнорируется» относятся к СБОРК� пайплайн-промптов, а не ко всему коду.
- **B (полное выпиливание, РИСК):** перенаправить `prompting.py._PROMPTS_DIR` на `pipelines/default/prompts/`, синхронизировать отсутствующие файлы (researcher/experimenter roles в app/prompts нет), проверить что get_session_prompt/get_role_icons не сломались. Большая правка, легко словить регресс. НЕ рекомендую без явного запроса.

→ **Оставляю app/prompts. Это research-вывод: папка НЕ мёртвая, разведка была неверной.** Жду решения оркестратора: оставить (A) или рисковый рефактор (B)?

---

## ✅ РЕАЛЬНО МЁРТВОЕ (доказано, безопасно удалить)

### 1. Модель opus-4-7 (deprecated, юзер: «нахуй»)
- `app/tg_bridge.py:573` — `'claude-opus-4-7[1m]': 'opus-4.7-1M'` (label). МЁРТВ.
- `app/static/js/app.js:1940, 2500, 2509` — `claude-opus-4-7[1m]` labels/colors. МЁРТВ.
- `models.py` — 4-7 УЖЕ нет (удалён ранее). ✅
- Удалить: строки-упоминания 4-7 в tg_bridge + app.js.

### 2. DeepSeek (enterprise-only, не место в public)
- `models.py:216-218` — `_SEMANTIC_PATTERNS`: `("deepseek","deepseek"), ("deepseek-flash",...), ("deepseek-pro",...)`. Удалить 3 строки.
- `models.py:103-105, 267` — комменты про deepseek/gemini роутинг. Обновить/убрать deepseek из примеров.
- app.js — проверить deepseek label (grep показал только 4.7, deepseek в app.js не нашёл — перепроверю при impl).

### 3. Мёртвые model-labels в app.js (opus-4-6/haiku-4-6/sonnet-4-6)
⚠️ ОСТОРОЖНО: это display-fallback для DB-записей со СТАРЫМИ именами, которые redirect-алиасы (models.py:50-56) мапят на 4-8/sonnet-5. Если удалить label — старые записи покажутся как raw id.
- `haiku-4-6` — такого redirect-алиаса НЕТ в models.py → метка реально мёртвая, удалить.
- `opus-4-6`/`sonnet-4-6` — есть redirect (50,56) → метки для истории DB. Оркестратор сказал «оставь только 4.8/sonnet-5/...», но это сломает отображение старых записей. **Уточнить:** удалять ли метки для redirect'нутых (риск «Sonnet» → «claude-sonnet-4-6» в старых логах)?

---

## НЕ ТРОГАЕМ (подтверждено)
- **redirect-алиасы models.py:50-56** (4-6→4-8, sonnet-4-6→5) — backward-compat DB. ОСТАВИТЬ.
- **tasks-pm пайплайн** — активный, субагенты нужны.
- **docs/archive/** — история.
- **app/prompts/** — НЕ мёртвая (см. выше).

---

## Осиротевшее после сегодняшних правок
- proxy_manager чистка (прошлые задачи) — уже без осиротевших импортов (проверял).
- Проверю при impl: не осталось ли `import` неиспользуемых после удаления 4.7/deepseek.

---

## План удаления (после approve)
1. tg_bridge.py:573 — убрать `claude-opus-4-7[1m]` label.
2. app.js — убрать opus-4-7 (1940, 2500, 2509) + haiku-4-6 (мёртв). opus-4-6/sonnet-4-6 — по решению.
3. models.py:216-218 — убрать deepseek из _SEMANTIC_PATTERNS. Комменты 103-105/267 — убрать deepseek-примеры.
4. app/prompts/ — НЕ трогать (или B по решению).
5. Проверить осиротевшие импорты. Тесты. Codex.

**ЖДУ РЕШЕНИЯ:**
1. app/prompts — оставить (A) или рисковый рефактор на pipeline (B)?
2. app.js метки opus-4-6/sonnet-4-6 (redirect'нутые) — удалять или оставить для старых DB-записей?
