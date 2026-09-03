## Summary

План в целом хорошо разделяет route policy, runtime readiness и quota semantics, а admission расположен до создания `AgentSession`, worktree и DB row. Hot-template и legacy-normalization направления реализуемы.

Однако один blocking-пробел не позволяет readiness-проверке гарантировать фактическую исполняемость Claude-модели для профильных сессий.

## Findings

[blocking] `app/spawn_readiness.py`: передавайте resolved `profile` и проверяйте Claude auth в том же `CLAUDE_CONFIG_DIR`, который использует backend.

Заявленная сигнатура coordinator получает `pipeline`, `role`, model/runtime и override, но не `profile`. Сейчас `_create_session_locked()` разрешает и наследует профиль до admission, а `_claude_factory()` получает его через `BackendBuildContext`, загружает `profiles.config_dir`; `ClaudeBackend` затем устанавливает этот путь в `CLAUDE_CONFIG_DIR`.

Простой `claude auth status` проверит окружение процесса, а не credentials выбранного или унаследованного профиля. Admission сможет разрешить spawn, который затем не стартует с реальной backend-конфигурацией. Добавьте `profile`/resolved credential context в readiness contract и тесты для явного и унаследованного профиля.

[suggestion] `app/backend_grok.py`: определите безопасный owner подготовки managed `GROK_HOME`.

План требует запускать catalog probe с тем же managed home, что и backend, но текущий `ensure_grok_home()` — не read-only probe: он создаёт каталог/config, удаляет неподходящий `auth.json` и создаёт symlink в общем для всех Grok-сессий home. Уточните, что coordinator вызывает один общий helper подготовки home, что операция сериализована либо доказанно безопасна при параллельном backend startup, и что тест admission проверяет отсутствие повреждённого промежуточного состояния. Иначе «pre-side-effect admission» будет иметь скрытый shared-runtime side effect.

[suggestion] `scripts/normalize_prompt_overlays.py`: закрепите транзакционную последовательность как `BEGIN IMMEDIATE → повторная проверка set/hash/status → UPDATE → COMMIT`.

Фраза «одной транзакцией ставит» не гарантирует, что повторная проверка и записи находятся под одним write lock. Остановка сервиса — основной предохранитель, но AC обещает atomic zero writes при drift. Это следует проверить тестом с изменением строки между snapshot и apply; backup должен создаваться до write-транзакции через SQLite backup API, а любое исключение — делать явный rollback.

## Verdict

CHANGES REQUESTED — один blocker: readiness не учитывает фактический Claude profile credential context.

Подтверждающая цитата из плана:

> “Full override (`NULL`) не меняется и не пересобирается от template hash;”

## Round 2 (final)

### Re-review status

- **FIXED — Claude profile credential context.** Coordinator now runs after both profile inheritance paths and shares one credential-context resolver with `_claude_factory`; the AC covers explicit, explicit-parent, and auto-found-parent profiles so process-global auth cannot mask a dead selected profile.
- **FIXED — Grok managed-home ownership.** The existing `app/backend_grok.py` helper is the sole preflight/backend owner, its complete config/symlink mutation is serialized, and the plan requires a parallel-call integrity regression.
- **FIXED — SQLite normalization atomicity.** The protocol is now backup first, then `BEGIN IMMEDIATE`, fresh set/hash/status reread, comparison, exact update, and commit; drift or exception explicitly rolls back with zero writes, including between-snapshot-and-apply drift coverage.

### New findings

No new blocking contract failures found in the edited plan.

### Verdict

**APPROVED.**

Evidence quote from the current plan:

> “Root restore и уже существующие session resume этим gate не переопределяются.”

## Round (2026-08-13T07:56:45Z)

## Re-review status

- **FIXED — Claude profile context.** Coordinator receives the resolved profile after both inheritance paths and shares credential resolution with `_claude_factory`.
- **FIXED — Grok managed home.** One serialized helper owns preflight/backend preparation, with parallel integrity coverage.
- **FIXED — SQLite atomicity.** Backup precedes `BEGIN IMMEDIATE`; reread, comparison, update, commit, and rollback semantics are explicit.

## New findings

No new blocking contract failures.

## Verdict

**APPROVED.**

> “Root restore и уже существующие session resume этим gate не переопределяются.”

Round 2 appended to [codex-review-plan.md](/home/kesha/orchestra/worktrees/home-kesha-orchestra/prompt-engineer/docs/tasks/247/codex-review-plan.md).
