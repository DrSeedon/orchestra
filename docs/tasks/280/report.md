# #280 — TestCanSpawn after #36

## Decision

`test_whitelist_allows_listed` проверял ФОРМУ (временный frontmatter с ролью `boss`), не поведение whitelist. grok-51 уже снял его в #278 (`4f0c87aa` содержит комментарий REMOVED). Не восстанавливал.

Allow-путь живой:
- `tests/test_pipeline.py::TestValidateSpawn::test_allowed_child_passes` — `lead → coder`
- `tests/test_pipeline.py::TestValidateSpawn::test_wildcard_can_spawn_allows_any` — `boss → w` при `can_spawn: ['*']`
- `tests/test_default_pipeline.py::TestDefaultValidateSpawn::test_orchestrator_spawns_worker_ok` (+ full-cycle, v2.16, sub-orchestrator)
- `tests/test_manager.py::TestValidateSpawnIntegration::test_allowed_spawn_passes` — `create_session` `pm-glava → secretary`

## Finding: `test_unknown_parent_fails_open` был вакуумным относительно #36

Имя обещало fail-open неизвестного родителя. После #36 неизвестная **роль** родителя — всегда `ValueError` (`app/pipeline.py:710-713`), независимо от `validation: fail-open`.

Что тест делал на самом деле: `parent_name="ghost-parent"` без сессии → `_resolve_role` возвращает `None` (`app/manager.py:1538-1543`) → `validate_spawn(..., None, "worker")` видит **корень** (`if not parent_role: return`) и пускает.

Мутации прода `app/pipeline.py` (якорь `grep -c` = 1, `cp`/`mv`/`touch`, зелёный повтор):

| Мутация | `test_unknown_parent_fails_open` | Контроль |
|---|---|---|
| `if parent is None: raise` → `return` (откат #36) | **зелёный** | три #36-теста красные (`DID NOT RAISE`) |
| `if not parent_role: return` → `raise MUTATION_ROOT_DENIED` | красный | `test_root_empty_parent_allowed` и `test_root_spawn_allowed` тоже красные |

Вывод: тест не мог покраснеть от инверсии #36. Краснел только от поломки root-allow, уже покрытой в `test_pipeline` / `test_default_pipeline`.

## Что сделано

Снят вакуумный тест. На том же шве `create_session` — `test_unknown_parent_role_denied`: в БД сессия с `role="phantom"`, спавн ребёнка ждёт `ValueError: unknown parent role 'phantom'`.

Мутация «#36 raise → return» валит новый тест (`DID NOT RAISE`). После отката + `touch` — зелёный.

Прод не менялся.
