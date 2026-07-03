# app/prompts/ рефактор — план (Вариант B, полное выпиливание)

**Дата:** 2026-07-01
**Решение:** юзер — «полностью на дефолт пайплайн, никакой обратной совместимости, полуживой код хуже мёртвого». Убрать app/prompts, всё на pipelines/default/prompts.

---

## ✅ Ключевая находка — рефактор ПРОЩЕ чем казалось

`pipelines/default/prompts/` — **строгий superset** app/prompts (проверено):
- **base.md**: pipeline-версия ПОЛНЕЕ (fuller background-jobs). app/prompts НЕ имеет уникального контента. → миграция base.md НЕ нужна, pipeline лучше.
- **modules/**: pipeline имеет ВСЕ модули app/prompts + `self-improvement.md`. Superset.
- **skills/**: идентичны (codex-debate, html-artifacts, vps-deploy).
- **roles/**: pipeline имеет 6 ролей (+ researcher, experimenter), app/prompts — 4. Superset.

→ **Ничего переносить не надо.** Просто перенаправить чтения на pipeline.

Все 12 функций prompting.py ХАРДКОДЯТ `_PROMPTS_DIR = app/prompts`. Ни одна не pipeline-aware. Значит правка ТОЧЕЧНАЯ: сменить 3 константы.

---

## Изменения

### 1. `app/prompting.py` — перенаправить константы (3 строки)
```python
# БЫЛО:
_PROMPTS_DIR = Path(__file__).parent / "prompts"           # app/prompts
# СТАЛО:
_PROMPTS_DIR = Path(__file__).parent.parent / "pipelines" / "default" / "prompts"
_MODULES_DIR = _PROMPTS_DIR / "modules"   # автоматом
_SKILLS_DIR = _PROMPTS_DIR / "skills"     # автоматом
```
Все 12 функций (read_prompt, role_prompt_file, role_can_spawn, skills_catalog, roles_catalog, get_role_icons, inject_skills_to_worktree, _load_modules, prompt_template_hash) теперь читают pipeline. Никаких других правок в prompting.py — они уже используют константы.

⚠️ Нюанс: `_PROMPTS_DIR.parent.parent` считается от `app/prompting.py` → `app/` → repo root → `pipelines/default/prompts`. Совпадает с `pipeline.PIPELINES_DIR`. Можно импортнуть PIPELINES_DIR из pipeline.py для DRY, НО это создаёт циклический риск (pipeline не импортит prompting сейчас). Проверю — если чисто, импортну; иначе локальная константа (3 строки > циклический импорт).

### 2. `manager.py:207` — fallback → FAIL LOUD
Сейчас:
```python
try:
    base = build_system_prompt(pipeline, role, scope)
except (FileNotFoundError, KeyError):
    return _UPSTREAM_ROLE_SYSTEM_PROMPT(role, scope)   # ← легаси fallback
```
Проблема: `_UPSTREAM_ROLE_SYSTEM_PROMPT` (manager.py:123) — легаси-сборка через read_prompt/role_prompt_file. Юзер хочет fail loud.

**Решение:** убрать `_UPSTREAM_ROLE_SYSTEM_PROMPT` целиком + fallback. При FileNotFoundError/KeyError — не молчать:
```python
base = build_system_prompt(pipeline, role, scope)  # падает если pipeline/роль нет
```
Но: `build_system_prompt` кидает FileNotFoundError если манифеста нет. Есть ли сценарии без манифеста? default всегда есть. tasks-pm есть. Кастомный scope без пайплайна → сейчас fallback спасал. После — упадёт.
- ⚠️ ПРОВЕРИТЬ: все ли live-сессии на пайплайне с манифестом? Если да — fallback мёртв, убираем смело.
- Если есть сессии без пайплайна → они сломаются. Нужно: либо гарантировать pipeline=default всегда, либо fail loud с понятной ошибкой.
- **Безопасный fail-loud**: если build_system_prompt кинул → лог ERROR + raise (не молчаливый worker.md). Оркестратор увидит что роль/пайплайн не настроен.

⚠️ Это САМАЯ рисковая часть. Проверю _UPSTREAM использование: только manager.py:207? Если да — удаляю функцию + fallback, build_system_prompt напрямую.

### 3. `sessions.py:147` get_session_prompt — read_prompt("base.md")
После правки #1 `read_prompt` читает pipeline base.md. Дашборд «показать промпт» продолжит работать (base из pipeline). Правка НЕ нужна — прозрачно через prompting.py.
- ⚠️ НО: base_len дифф-логика (sp[:base_len]==base) сравнивает с pipeline base.md. Если сессия собрана на pipeline base.md — совпадёт. Проверю на живой сессии.

### 4. `system.py:283` get_role_icons — прозрачно
После #1 читает pipeline roles/*.md frontmatter (icon поля). Правка НЕ нужна.
- ⚠️ Проверить: у pipeline roles/*.md есть `icon:` в frontmatter? Если нет — иконки пропадут. ПРОВЕРЮ.

### 5. `pipeline.py:5` коммент — обновить
«app/prompts/ игнорируется» → «app/prompts/ удалён, единственный источник = pipelines/<name>/prompts/». Также строки 385, 399.

### 6. Удалить `app/prompts/` (trash) — ПОСЛЕДНИМ, после проверок.

---

## Порядок (fail-safe)
1. Проверить: pipeline roles/*.md имеют `icon:` frontmatter (иначе иконки сломаются).
2. Проверить: `_UPSTREAM_ROLE_SYSTEM_PROMPT` юзается ТОЛЬКО в manager.py:207.
3. Проверить: все live-сессии на пайплайне с манифестом (fallback реально мёртв?).
4. Правка #1 (перенаправить _PROMPTS_DIR).
5. Правка #2 (убрать fallback → fail loud) — если проверка #3 ок.
6. Правки #5 (комменты).
7. Тесты + дашборд (показать промпт, иконки) + спавн воркера/оркестратора.
8. ТОЛЬКО потом удалить app/prompts (trash).
9. grep app/prompts по app/*.py → ПУСТО.
10. Codex review (осиротевшие чтения app/prompts).

## Риски
1. **get_role_icons** — pipeline roles могут не иметь `icon:` → иконки пропадут. Проверить ПЕРВЫМ.
2. **fallback removal** — сессия без пайплайна сломается. Проверить что все на манифесте.
3. **base_len дифф** в дашборде — если сессия на старом app/prompts base.md, а теперь читаем pipeline base.md (другой) → дифф-логика неточная для СТАРЫХ сессий. Новые — ок. Приемлемо (косметика дашборда).
4. **prompt_template_hash** меняется (base.md другой) → template-hash всех ролей сменится. Это влияет на что? Проверю (может триггерить «промпт изменился» индикатор).

## ✅ ПРЕ-ЧЕКИ ВЫПОЛНЕНЫ

1. **Иконки — НЕ проблема.** app/prompts roles имеют icon только у sub-orchestrator (🎯). Frontend (app.js:1402) ХАРДКОДИТ дефолты для всех ролей (orchestrator👑 worker⚙️ full-cycle🔄 sub-orchestrator🎯) и лишь мёржит API поверх. get_role_icons()→{} (pipeline без icon) → фронт-дефолты покрывают. Визуально НЕ сломается. ✅
   - Опционально: добавить `icon:` в pipeline roles frontmatter если хотим кастомные. Не критично.

2. **`_UPSTREAM_ROLE_SYSTEM_PROMPT` — тестируется!** test_manager.py (5 тестов: 678-749) + test_default_equals_upstream.py характеризуют этот fallback. Удаление fallback → **эти тесты надо удалить/переписать** (они проверяют легаси-поведение которое мы убираем). Это не «3 строки» — надо тронуть тесты.
   - Используется ТОЛЬКО в manager.py:207 (+ тесты). Прод-код чист.

3. **Циклический импорт — нет.** pipeline.py не импортит prompting → можно `from app.pipeline import PIPELINES_DIR` в prompting.py чисто. Но DEFAULT_PIPELINE hardcode "default" — ок.

## Финальные вопросы оркестратору
1. **fallback removal → тесты.** Удаление _UPSTREAM_ROLE_SYSTEM_PROMPT ломает test_manager.py (5) + test_default_equals_upstream.py. Их тоже удалить (они проверяют легаси которое убираем)? Или оставить функцию но перенаправить на pipeline (мягче)?
2. **fail loud vs soft**: при роли не в манифесте — raise (fail loud, юзер-стиль) ИЛИ default worker.md из pipeline (мягкий)? Юзер сказал fail loud, подтверждаешь что тесты под это переписать?
3. Всё остальное безопасно (иконки ок, base.md pipeline полнее, structure superset).

## Уточнённая оценка
- prompting.py: 3 строки (константы). ✅ просто.
- manager.py: убрать _UPSTREAM (~15 строк) + fallback try/except. ⚠️ ломает тесты.
- Тесты: удалить/переписать 5+ тестов про upstream-fallback.
- Комменты pipeline.py: 3 места.
- Удалить app/prompts (trash).
- **Итого: не тривиально из-за тестов. ~1 час аккуратной работы + Codex.**
