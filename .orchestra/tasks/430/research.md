# #430 — переезд project-local состояния Orchestra в `.orchestra/`

Дата исследования: 2026-09-01. Исследован checkout `9b202bcb`; код не менялся.

## Question

- **Context.** Один процесс Orchestra обслуживает несколько project scopes. Общий pipeline собирает
  обязательный memory-gate для агентов всех проектов, а project-local знания, задачи и память
  воркеров живут в Git-репозиториях самих проектов.
- **Change under test.** Перенести принадлежащие Orchestra каталоги текущего репозитория из
  `docs/{kb,tasks,workers,archive}` и `pipelines/` в единый `.orchestra/`, обновить каждого живого
  consumer и определить безопасный rollout того же соглашения для остальных проектов.
- **Baseline.** Текущие hard-coded roots, обязательный prompt с `docs/kb`, 18 уже materialized
  project knowledge roots по входному замеру постановщика, без переходного механизма.
- **Outcome.** Переезд считается спроектированным безопасно, только если: (1) найден каждый
  live referrer; (2) ни один проект на любой стадии rollout не получает mandatory path в пустоту;
  (3) personal memory и task-number guard не теряют старое состояние; (4) Git evidence продолжает
  разрешаться как `git_commit:path -> git_blob -> source_sha256`; (5) `.orchestra/` трекается;
  (6) до/после сравниваются множества failed node ids одной и той же pytest-команды.

## Hypotheses considered

### H1 — одного атомарного cutover в репозитории Orchestra достаточно

Гипотеза: все consumers принадлежат этому checkout, поэтому `git mv` плюс одна правка prompt
закрывают задачу.

Фальсификатор: общий prompt или общий loader обслуживает project root, который ещё не содержит
`.orchestra/`.

**REFUTED.** Постановщик передал замер: 21 scope, 18 репозиториев с `docs/kb`, от 2 до 12 788
файлов. `memory-search.md` — обязательный общий модуль [L1], а `load_worker_memory()` читает
project/repository path каждого воркера [L2]. Значит, single-repo switch ломает не только поиск,
но и personal memory чужих проектов.

### H2 — миграция на backend connect безопасно решает fleet rollout

Гипотеза: существующий seam перед `candidate.connect()` может выполнить переезд, как уже делает
синхронизацию `AGENTS.md` и skills [L3].

Фальсификатор: seam работает в worker worktree либо вынужден менять tracked paths и оставляет
checkout dirty.

**REFUTED как автоматическая мутация.** Для воркера `project_path = worktree_path`, то есть один
и тот же project может мигрироваться независимо в нескольких ветках [L3]. Платформа прямо
запрещает перезаписывать tracked paths: это навсегда пачкает worktree и блокирует merge [L4].
Автоматический `git mv` нарушит этот invariant; автоматический commit дополнительно станет
несанкционированной записью в чужой репозиторий. Seam пригоден для read-only preflight/выбора
уже существующего root, но не для самой миграции.

### H3 — временный per-project resolver сохраняет работоспособность до общего cutover

Гипотеза: общий код/собранный prompt выбирает ровно один существующий root на проект — новый,
если он materialized и прошёл preflight, иначе старый. После миграции всех проектов fallback
удаляется, поэтому final state не содержит compatibility.

Фальсификатор: один project одновременно читается/пишется в оба root; новый root выбирается до
наличия `kb/README.md`, worker memory и task root; prompt и Python loader выбирают разные roots;
existing worker worktree остался на pre-migration base; либо receipt не называет конкретный scope.

**LIKELY, не утверждено архитектурно.** Existing prompt assembly уже получает scope для
оркестраторских ролей, но `build_system_prompt(..., scope)` сейчас не использует scope, а worker
formatting знает repository/worktree только позже [L5]. Реализация возможна, но затрагивает shared
prompt/runtime contract и требует решения пользователя до Phase 2. Важное уточнение: fallback
должен выбирать один root, а не искать/писать в оба. Global switch допустим только после receipt
для каждого scope и каждого живого/resumable worktree, а не после одного canary.

### H4 — оставить чужие проекты на старом соглашении навсегда

Гипотеза: переехать только в этом репозитории и поддерживать два постоянных соглашения.

Фальсификатор: пользователь требует `.orchestra/` в каждом проекте каждого оркестратора.

**REFUTED решением пользователя.** Этот вариант годится только как временная стадия rollout;
постоянное расхождение не соответствует поставленной цели.

### H5 — 12 788 файлов упираются в shell `ARG_MAX`

Гипотеза: массовый `git mv` нельзя выполнить одной командой.

Фальсификатор: Git принимает directory source как один argv и сам перечисляет tracked children.

**REFUTED измерением.** `ARG_MAX=2 097 152`, environment занимает 5 732 bytes, NUL-список всех
tracked paths под knowledge root — 855 689 bytes. Главное: `git mv --dry-run docs/kb .orchestra`
завершился `RC=0` и перечислил все 12 788 tracked entries внутри Git. Безопасный способ — создать
destination directory и передать `git mv` сами каталоги, не раскрывать файловый glob и не строить
`$(find ...)`.

## Findings

### F1. Cross-project blast radius больше локального rename

**CONFIRMED — primary code + supplied fleet measurement.** Общий mandatory module дословно требует
прочитать `docs/kb/README.md` до первого code scan [L1]. Тот же pipeline получают агенты разных
projects. Входной fleet measurement постановщика: 21 scope, 18 existing knowledge roots; orchestra
12 788 files, COG-second-brain 5 112, comfy 1 747, seedon 323, media 2. Эти числа приняты как
supplied evidence и в чужих repositories не перепроверялись по прямому запрету постановщика.

Следствие: prompt нельзя hard-switch до того, как выбранный rollout докажет существование нового
root в конкретном project. То же относится к Python loader personal memory [L2] и task-number
directory guard [L6], а не только к `memory-search.md`.

### F2. Исчерпывающий literal inventory существенно больше списка из карточки

**CONFIRMED — direct `git grep` measurement.** По актуальному `main=f5dad75d`:

| literal | unique files | occurrences |
|---|---:|---:|
| `docs/kb` | 318 | 14 657 |
| `docs/tasks` | 11 858 | 22 032 |
| `docs/workers` | 1 255 | 2 937 |
| `docs/archive` | 400 | 503 |
| `pipelines/` | 472 | 1 549 |

Union exact literals содержит 13 818 files. Разбиение union: 12 531 `docs/kb/**`, 1 142 `docs/tasks/**`,
43 tests (включая separated path construction), 30 worker-memory files, 25 app files с exact
или split reference, 13 pipeline files, 9 scripts, 8 `docs/artifacts` files и меньшие группы.

Literal grep дополнен AST/path-component pass. Он нашёл ссылки, которых нет в contiguous literals:
`app/ia/knowledge.py` (`("docs", "tasks")`, `("docs", "kb")`, archive tuple),
`scripts/repair_task_par_collisions.py` (`Path(scope) / "docs" / "tasks"`) и split-path tests.
Воспроизводимый generator и полный inventory сохранены в `reference_inventory.py` и
`reference-inventory.tsv`: 26 202 aggregated rows / 13 827 files, из них 26 143 exact и 59
split-AST rows; TSV SHA-256 `22a1f953030a2251463c65c9b699427c116988fee4e60462917ed4bcb839dd7b`.
Колонки: path, line, kind, occurrences, literal, referrer class, owner status.
Round 2 обнаружил self-inclusion после будущего commit. Generator теперь динамически исключает
собственную task-artifact directory и до, и после её move; direct control дал
`SELF_EXCLUSION_OK old_root=1 new_root=1`, повторная генерация сохранила тот же SHA.
Эти числа/SHA относятся к Phase-1 commit `b187dd61`. После обязательных main sync и final RED
Phase-2 working inventory пересобран тем же generator: 26 196 rows / 13 832 files, SHA-256
`4cd26253ac6f855fac702ba98ff6ce9b2d7b9e813e4c9c9eb1104845790da42a`; старый вывод остаётся
доступен в Git history, второй duplicate-файл не хранится.

#### Полный app referrer set для будущего плана

Behavior roots/contracts:

- `app/pipeline.py`
- `app/prompting.py`
- `app/ia/cutover.py`
- `app/ia/knowledge.py`
- `app/ia/project_distribution.py`
- `app/ia/project_knowledge.py`
- `app/tm.py` — **вне выданного владения, но behavior-critical**

Agent-facing diagnostics, comments and evidence links, которые тоже становятся неверными после
переезда:

- `app/backend_claude.py`
- `app/backend_codex.py`
- `app/backend_grok.py`
- `app/charts.py`
- `app/fdstore.py`
- `app/harness/mcp.py`
- `app/main.py`
- `app/manager.py`
- `app/mcp_stdio.py`
- `app/rag_service.py`
- `app/routes/sessions.py`
- `app/routes/system.py`
- `app/session.py`
- `app/session_turns.py`
- `app/templates/dashboard.html`
- `app/workspace.py`
- `app/static/js/app.js` — **явно запрещённое владение**
- `app/static/js/chat.js` — **явно запрещённое владение**

`app/models.py` old-path references не содержит. Любой plan, который обещает zero live references,
обязан либо получить координацию с владельцами `app/tm.py`/`app/static/**`, либо явно вынести их в
отдельный dependent ticket. Молча пропустить их нельзя.

#### Scripts

`scripts/activate_project_knowledge.py`, `check_kb_contract.py`,
`check_pipeline_manifest.py`, `grill-spec.sh`, `kb_extract_report.py`,
`kb_promote_facts.py`, `migrate_agent.py`, `rehearse-seamless-restart.py`,
`repair_task_par_collisions.py`.

#### Tests

43 files с literal или split path:

`test_backend_claude.py`, `test_backend_grok.py`, `test_bg_jobs.py`, `test_charts.py`,
`test_cross_repo_warning.py`, `test_default_pipeline.py`, `test_fan_barrier.py`,
`test_fan_enable.py`, `test_fd_adopt.py`, `test_grok_usage_frontend.py`, `test_hot_apply.py`,
`test_instant_restart.py`, `test_kb_markdown_contract.py`,
`test_kb_promote_facts_script_409.py`, `test_knowledge_import_linking_409.py`,
`test_knowledge_resource_preservation_409.py`, `test_knowledge_runtime_evidence_link_409.py`,
`test_manager.py`, `test_mcp_codex_review.py`, `test_mcp_config_isolation.py`,
`test_merge_reason_preservation_416.py`, `test_model_catalog_frontend.py`,
`test_native_history_import.py`, `test_openrouter_retry.py`, `test_pipeline.py`,
`test_project_distribution_dirty_412.py`, `test_project_distribution_review_412.py`,
`test_project_knowledge_distribution_412.py`, `test_project_knowledge_t3_review_412.py`,
`test_prompting.py`, `test_quota_admission_e2e.py`, `test_rag.py`, `test_runtime_registry.py`,
`test_scaffold.py`, `test_seamless_restart.py`, `test_search_deadline.py`, `test_session.py`,
`test_startup_bridge.py`, `test_task_repair_completion_422.py`, `test_tasks_pm_pipeline.py`,
`test_tg_bot_api_unit.py`, `test_tm.py`, `test_validate_spawn_unknown_role.py`.

### F3. `.gitignore` сейчас действительно теряет будущую personal memory

**CONFIRMED — direct Git ignore probe.** `.gitignore:9-10` содержит пару `workers/` и
`!docs/workers/`. `git check-ignore -v --no-index .orchestra/workers/new-agent.md` указывает
на line 9: новый personal-memory file ignored. Старое negation относится только к прежнему root.

Обе строки должны измениться одним ticket. Наиболее узкий final-state contract — anchor runtime
directory к repository root (`/workers/`) и удалить старое negation; альтернативно требуется
явное `!.orchestra/workers/`. Точное решение — Phase 2, но AC обязан проверять и positive tracked
new memory, и negative root runtime `workers/`.

### F4. Evidence содержит два разных класса путей; blanket replacement повреждает provenance

**CONFIRMED — structured JSON count + primary runtime.** `docs/kb/records` содержит 12 759 JSON
records. Поле `source_path` распределено так:

- 10 678 `docs/tasks/**`;
- 1 121 `docs/workers/**`;
- 352 `docs/archive/**`;
- 168 `docs/kb/**`;
- 424 other paths, включая 184 `pipelines/**`, research/reviews/guides;
- 16 root `CLAUDE.md`/`TODO.md`.

12 503 records имеют один из old-path literals. Эти `source_path` — **historical address inside
the pinned `git_commit`**, не current filesystem address: runtime проверяет exact
`git_commit:source_path == git_blob`, затем SHA bytes [L7]. Массовая замена `source_path` на новый
current path при сохранении old commit немедленно даёт `evidence Git path/blob binding changed`.

Три случайно выбранных records проверены до переезда как human-readable positive control:

- `225f7fed-ad3b-5487-9e44-c1cd42f49ef6` — path/blob MATCH, SHA MATCH;
- `966820e5-cb8f-547f-8caf-ec583ece66fc` — path/blob MATCH, SHA MATCH;
- `ad0fbcdd-2f4e-502c-bbf5-bc8c34dd857f` — path/blob MATCH, SHA MATCH.

Их old `source_path` должен остаться историческим. После `git mv` Git object сохраняется, поэтому
те же проверки остаются валидны без repin.

Минимум трёх из карточки недостаточен как loss gate. Полный детерминированный проход сгруппировал
12 759 records по 8 commits, проверил все 12 759 `git_commit:source_path -> git_blob`, затем одним
`git cat-file --batch` проверил 1 636 unique blobs и все 12 759 SHA. Результат до move:
`ALL_EVIDENCE_OK ... path_ok=12759 sha_ok=12759 seconds=0.919`. Эту же полную команду нужно
повторить после move; три sampled IDs остаются только читаемым контролем.

Другой класс — 12 759 `manifest.json.records[].destination_relative_path`: все сейчас начинаются
с `docs/kb/`. Это **current materialization address**, его читает distribution writer [L8], поэтому
manifest нужно пересобрать с `.orchestra/kb/...`. `records_sha256` хеширует payload records и от
изменения destination address не меняется.

Дополнительный риск: project-local query сейчас читает current working-tree file через historical
`source_path` [L9]. После move source text перестанет находиться, хотя pinned Git evidence остаётся
валидным. Нужно отдельное AC: query на migrated repo находит body по Git blob либо по явно
разделённому current path; молчаливый `source_text=""` нельзя принять как успех.

Новый import имеет отдельный blocker: `_cold_source_path()` сейчас разрешает только
`docs/{tasks,kb,archive}` и отвергает `.orchestra/**` [L15]. Во время fleet transition validator
должен принимать current root, выбранный для конкретного project, и old root unmigrated projects;
после fleet completion old current-import branch удаляется. Pinned historical records продолжат
разрешаться через [L7] и не требуют переписывания `source_path`.

### F5. Acceptance «raw rg = zero» в буквальном виде невыполнимо и опасно

**CONFIRMED — contradiction with evidence contract.** Historical evidence records обязаны хранить
old `source_path`; сама эта research file обязана назвать legacy literals; code may also keep
negative guards that detect forbidden legacy directives (`app/ia/cutover.py:31-38`). Поэтому
repository-wide `rg` без классификации останется непустым даже при идеальном cutover.

Механическая приёмка должна разделять:

1. **live owner set** — app, scripts, current prompts, tests, `.gitignore`, `CLAUDE.md`, README,
   manifest destination paths: old paths forbidden;
2. **immutable historical set** — evidence `source_path`, task/research/archive/changelog text:
   old paths разрешены и проверяются path/blob/SHA, а не удаляются;
3. **negative tests/guards** — legacy literals разрешены только как специально маркированные
   rejection fixtures.

Иначе «обнуление rg» заставит переписать provenance или спрятать предмет исследования.

### F6. Pipeline move локален платформенному repo, personal memory/task roots — нет

**CONFIRMED — primary code.** `PIPELINES_DIR` и `_PROMPTS_DIR` принадлежат checkout Orchestra
[L10]; их можно атомарно перенести вместе с code constants. Но `load_worker_memory()` выбирает
`repository_path or scope` [L2], `app/tm.py` выбирает `Path(scope)` [L6], а project knowledge router
получает roots всех зарегистрированных projects. Поэтому один и тот же commit одновременно меняет
behavior для ещё не migrated repositories.

`Dockerfile:24` также копирует `pipelines/`, но Dockerfile вне выданной territory. Без отдельного
разрешения/владельца container build после move потеряет prompts. `deploy/orchestra.service` имеет
только историческую ссылку на task evidence; `CHANGELOG.md` разрешён как history. `TODO.md` содержит
live task-artifact references, но также вне выданной territory — требуется решение владельца.

### F7. Safe rollout должен менять prompt последним и иметь canary evidence

**CONFIRMED как invariant; конкретная архитектура ещё не выбрана.** Минимальная последовательность
для любой допустимой ветки:

1. Заморозить fleet manifest: каждый scope, repository HEAD, live/resumable session и фактический
   worktree/base commit; current prompt receipt `(runtime, role)` без scope для этого недостаточен [L16].
2. Проверить per-project `.gitignore`, tracked state, absence of simultaneous old/new roots;
3. materialize и commit `.orchestra/` владельцем project, не backend-connect side effect;
4. существующие worktrees rebase/recreate либо оставить на old resolver до их завершения; main commit
   сам не добавляет new root в старую worker branch, а hot refresh читает `worktree_path` [L17].
5. проверить file parity, полный 12 759-record evidence gate и current-import validator;
6. для **каждого scope** свежим реальным agent contour выполнить memory gate в новом root и загрузить
   personal memory; receipt называет scope, repo/worktree HEAD, runtime, role и observed path;
7. только после полного fleet receipt переключить mandatory global prompt;
8. после migration всех repositories удалить transition resolver и old-path support.

Это следует из project rule «prompt меняется последним» и из измеренного incident 25.08,
переданного постановщиком. Unit test или наличие directory не заменяют live call.

### F8. `pipelines/` и `CLAUDE.md` — движущиеся owners, directory rename сам по себе не сохраняет свежесть

**CONFIRMED — direct branch/main comparison.** После начала Phase 1 main продвинулся с
`9b202bcb` до `f5dad75d`. В territory появились изменения `CLAUDE.md` и
`pipelines/default/prompts/roles/orchestrator.md`; новый `<artifact-reading>` имеет count 2 на main
и count 0 в текущей ветке. Если выполнить move от старой базы, Git корректно перенесёт старые bytes,
а новая policy исчезнет без runtime error.

Следствие для acceptance:

1. до первого move синхронизировать branch с текущим main: `git rev-list --count HEAD..main` равно
   0, а diff `$(git merge-base HEAD main)..main` по `CLAUDE.md`/`docs/**`/`pipelines/**` пуст;
2. снять per-file manifest `old path -> new path, mode, newline count, byte count, SHA-256`;
3. после move сравнить все mapped rows, а не только file count;
4. отдельный positive control:
   `grep -c artifact-reading .orchestra/pipelines/default/prompts/roles/orchestrator.md` → `2`;
5. перед handoff снова проверить новые main commits по живым owners и перенести их на new paths.

Текущий pytest baseline также привязан к `9b202bcb`; после branch sync его нельзя использовать как
единственную before-side, baseline надо перезаморозить до первой production mutation.

## Rollout options and price

| Option | Плюсы | Цена / falsifier | Статус |
|---|---|---|---|
| Backend-connect делает `git mv` | seam уже существует | мутирует tracked foreign worktree, worker branches расходятся, merge блокируется; противоречит [L4] | REFUTED |
| Static prompt временно понимает оба path | не требует fleet-wide atomic commit | модель может искать/писать в оба root; та же fallback-логика дублируется в десятках инструкций | UNCERTAIN, только с deterministic one-root resolver |
| Scope-aware resolver в code + prompt placeholder | один root на project/worktree; позволяет prompt-last | shared runtime/API change, workers и orchestrators собираются разными seams; нужен per-scope/worktree receipt; временная compatibility до fleet completion | LIKELY, требует архитектурного решения пользователя |
| Только Orchestra переезжает, остальные навсегда старые | минимальный local diff | постоянное расхождение conventions, противоречит расширенному решению пользователя | REFUTED как final state |
| Одновременные manual commits во всех 18 repo, затем global prompt | final code без fallback | нет atomic transaction между repos; ранние migrated projects ломаются до prompt switch, нужен fleet freeze/координация | UNCERTAIN и операционно дорогой |

## What moves and what stays under `docs/`

Карточка велит спорные случаи перечислить, а не решить молча.

### Однозначно move

- `docs/kb/` → `.orchestra/kb/` (12 788 tracked files, 56 MiB)
- `docs/tasks/` → `.orchestra/tasks/` (3 343 tracked files, 86 MiB)
- `docs/workers/` → `.orchestra/workers/` (152 tracked files)
- `docs/archive/` → `.orchestra/archive/` (45 tracked files)
- `pipelines/` → `.orchestra/pipelines/` (24 tracked files)
- `docs/artifacts/`, `docs/experiments/`, `docs/research/`, `docs/reviews/`, `docs/tg-media/`:
  generated task/research/review artifacts, not human repository manual.
- `docs/codex-full-review.md`, `docs/codex-subscription-usage-research-2026-07.md`,
  `docs/fork-analysis.md`, `docs/proxy-speed-benchmark.md`, `docs/research-context-bug.md`,
  `docs/research-context-full.md`, `docs/research-deepgram.md`, `docs/research-multiproject.md`:
  one-off research/review history.
- `docs/HANDOFF-from-laptop.md`, `docs/measuring.md`, `docs/team-structure.md`:
  injected/linked operator or agent memory, not public product documentation.
- `docs/architecture.png`, `docs/fleet-looping.png`: generated infographics, unreferenced by README.

### Однозначно stay in human `docs/`

- `docs/banner.png`, `docs/dashboard.png`: directly embedded by `README.md`.
- `docs/portfolio/`: human portfolio/resume documentation.
- `docs/tg-local-api-setup.md`, `docs/telegram-bot-api.service.template`: operator setup manual/template.
- `docs/orchestrator-vps-onboarding.md`: human onboarding manual; it may need internal links updated,
  but remains documentation of the repository/product for a person.

### Спорные, решение нужно до Phase 2

- `docs/codex-field-guide.md`, `docs/grok-field-guide.md`: одновременно human runtime manuals и
  canonical operational knowledge referenced from `CLAUDE.md`; choice is `docs/` versus
  `.orchestra/guides/`.
- `docs/research/` content is clearly research artifact, but naming a final destination
  (`.orchestra/research/` versus `.orchestra/archive/research/`) is taxonomy/architecture, not rename.
- `docs/artifacts/` self-contained HTML may be user-facing, but its provenance is task output;
  whether public docs should link it determines `.orchestra/artifacts/` versus `docs/artifacts/`.

## Baseline test protocol

Предрегистрированная команда для обеих сторон:

```bash
uv run python -m pytest -vv --tb=short
```

Диагностический full run на `9b202bcb` получил `RC=137` после 2 835 passed / 46 failed / 12 skipped / 3 xfailed;
последний завершённый node —
`tests/test_sessions_conditional.py::test_unchanged_state_costs_no_body` на 82%. Чтобы не объявлять
неисполненный хвост зелёным, отдельный shard от `test_sessions_conditional.py` до
`test_workspace.py` завершился `RC=1`: 618 passed / 4 failed / 7 skipped. Объединённый set содержит
50 observed failed node ids и записан дословно в `baseline-failures.txt` со статусом
`INCOMPLETE_DIAGNOSTIC_DO_NOT_USE_AS_PHASE3_ORACLE`.

До/после сравниваются set difference `after - before` и `before - after`, а не числа. Вход
пользователя «47 failures, abort at 82%» не воспроизвёлся как полное множество на старом checkout:
основной прогон увидел только 46 до kill, tail добавил ещё 4. Это не доказательство изменения базы,
потому что branch уже отстал от main. `--collect-only` даёт 3 593 selected nodes, тогда как два
diagnostic runs дали максимум 3 523 status rows до учёта overlap — минимум 70 nodes не имеют
сопоставимого результата. Поэтому union 50 нельзя использовать как Phase-3 before oracle.

После синхронизации с main до move нужен новый воспроизводимый protocol:

1. сохранить exact `--collect-only -q` node-id manifest и 199 tracked test-file paths;
2. по count collected nodes разложить files в шесть детерминированных balanced shards и сохранить
   exact file list каждого shard;
3. каждый shard выполнить той же `pytest -vv --tb=short` командой до summary; `RC=137`, timeout или
   отсутствие status для любого collected node означает `incomplete`, не baseline;
4. доказать, что union shard statuses равен collection manifest;
5. после move повторить те же six file manifests и сравнить exact failed-node sets;
6. запускать в disposable clean worktree и проверять status до/после, потому что diagnostic run уже
   менял tracked PNG.

Оба baseline runs имели filesystem side effect: при чистом status до запуска изменились tracked
`docs/tasks/356/usage-bar-provider-grid-{1280,1920}.png` (19 059→20 443 и 19 914→22 025 bytes).
Файлы восстановлены побайтно из `HEAD`; это наши test-generated изменения, не user work. Следующий
baseline обязан снимать `git status` до/после и отказывать при любой неожиданной mutation. Raw
pytest logs (552 KiB) удалены как воспроизводимый вывод после извлечения exact node-id set;
`baseline-failures.txt` — сохранённый невосстановимый результат сравнения.

## Counter-evidence and unresolved gaps

- User card требует no compatibility и одновременно cross-project prompt-last rollout. Без fleet-wide
  atomic transaction эти требования несовместимы в промежуточном состоянии; нужен выбор rollout.
- Raw zero-`rg` acceptance конфликтует с immutable `source_path` evidence. Перепривязать 12 503
  records к move commit технически возможно, но меняет provenance date/commit и не требуется для
  blob survival; evidence contract [L7] говорит против этого.
- Foreign `.gitignore` и dirty/dual-root state не исследованы по прямому запрету не ходить в чужие
  repos. Они должны стать per-project preflight владельцев.
- Supplied follow-up 2026-09-01 дал comfy=1 747, а более старая строка `CLAUDE.md` содержит 1 745;
  определение/дату старого счётчика сверить нельзя. Research сохраняет свежий user-supplied 1 747,
  но rollout parity всегда считает каждый repo заново одной командой.
- `app/tm.py`, `app/static/**`, Dockerfile и TODO находятся вне выданного владения, хотя ссылки
  найдены. Phase 2 нельзя обещать complete cutover без coordination receipt: approved plan обязан
  дословно назвать responsible task/owner, каждый path, named check и завершённый result; иначе #430
  остаётся blocked-by этим dependent ticket. `app/models.py` referrer не имеет.
- Baseline `9b202bcb` завершён составным full+tail протоколом, но устареет при обязательной
  синхронизации с main; Phase 2 должен заморозить новый set до move.

## Affected files and risks

High-risk consumers: shared prompt/session delivery, project-local persistence paths, Git evidence,
task identity guard. Это включает behavior files F2, 13 pipeline files, 9 scripts, 43 tests,
`.gitignore`, `CLAUDE.md`, `README.md`, 4.1-MiB knowledge manifest и directory moves.

Основные failure modes:

- обязательный memory gate указывает в пустоту без ошибки platform logs;
- `load_worker_memory()` возвращает пустую строку и тихо стирает personal memory block;
- task-number allocator перестаёт видеть orphan task directory и переиспользует номер;
- manifest продолжает materialize `docs/kb` после cutover;
- historical evidence переписывается как current path и перестаёт разрешаться;
- generic `workers/` ignore глотает `.orchestra/workers`;
- Docker/container image стартует без pipeline prompts;
- одинаковое число pytest failures скрывает другой failed-node set.
- baseline test сам меняет tracked screenshot artifacts и может загрязнить preservation manifest.
- existing/resumable worker worktree не получает new root от commit в project main.
- `_cold_source_path()` отвергает новые `.orchestra/**` evidence imports.

## Mechanical commands and observed outputs

1. `git ls-files` counts: knowledge 12 788; tasks 3 343; workers 152; archive 45;
   pipelines 24.
2. Sizes: 56 MiB; 86 MiB; 964 KiB; 936 KiB; 244 KiB respectively.
3. `git mv --dry-run docs/kb .orchestra` → RC 0; Git enumerated every tracked child;
   `git status --short` remained empty.
4. `git check-ignore -v --no-index .orchestra/workers/new-agent.md` → `.gitignore:9:workers/`.
5. Structured records count → 12 759; old `source_path` fields → 12 503; manifest old
   destinations → 12 759.
6. Three sampled evidence records → path/blob MATCH and SHA MATCH for all 3.
7. Baseline tests on `9b202bcb` → full `RC=137` at 82% with 46 named failures; completed tail
   `RC=1` with 4 failures; union 50 exact node ids in `baseline-failures.txt`.
8. Moving-target probe → `main=f5dad75d`, branch `9b202bcb`; `artifact-reading` count main/branch
   = 2/0; changed live owners are `CLAUDE.md` and `pipelines/default/prompts/roles/orchestrator.md`.
9. Baseline side-effect probe → 2 tracked PNG changed after tests and were restored from known-clean
   `HEAD`; final `git status` contains only Phase-1 artifacts.
10. Full evidence gate → 12 759/12 759 path/blob and 12 759/12 759 SHA matches across 8 commits and
    1 636 unique blobs in 0.919 s.
11. Reference inventory → 26 202 rows / 13 827 files; 59 split-AST rows; TSV SHA-256
    `22a1f953030a2251463c65c9b699427c116988fee4e60462917ed4bcb839dd7b`.
12. Pytest collection control → 3 593 selected / 3 deselected of 3 596 collected; diagnostic status
    rows cannot cover at least 70 selected nodes.
13. Inventory self-exclusion control → old task root и future `.orchestra/tasks/430` root исключили
    research/generator/output; output SHA остался
    `22a1f953030a2251463c65c9b699427c116988fee4e60462917ed4bcb839dd7b`.

## Review outcome

Luna Round 1 (`codex-review-research.md`) нашёл 5 blocking, 2 suggestions и 1 question. Проверка:

- B1 existing worktrees — **ACK с уточнением**: initial spawn часто читает project root, но hot
  refresh/recovery передаёт `worktree_path`; добавлен per-worktree gate [L17].
- B2 scope-less receipt — **ACK**; добавлен receipt на каждый scope/worktree [L16].
- B3 evidence import validator — **ACK**; добавлен transitional per-project validator [L15].
- B4 three samples — **ACK**; прямой полный gate дал 12 759/12 759 для path/blob и SHA.
- B5 pytest union — **ACK**; старый set помечен incomplete, задан collection manifest + six shards.
- S6 comfy count — **DISAGREE по source priority**: reviewer прочитал старые 1 745, direct follow-up
  постановщика дал 1 747; конфликт теперь явный, rollout пересчитывает fresh.
- S7 inventory — **ACK**; добавлены generator + 3.0-MiB TSV.
- Q8 external owners — **ACK**; определён обязательный coordination receipt/dependent ticket.

Luna Round 2 закрыл B1–B5/S6/Q8, но оставил S7 blocking из-за self-inclusion generator после
будущего commit. Finding проверен и **ACK**: `tracked_files(root, excluded_prefix)` теперь исключает
текущую artifact directory, direct old/new-root control зелёный, TSV SHA стабилен. Проза исчерпала
потолок 2 rounds, поэтому третьего review не было. Последний reviewer verdict остаётся
`НЕ APPROVED` на pre-fix artifact; post-review blocker закрыт механическим доказательством, но
называть результат reviewer-approved запрещено.

## Sources

- [L1] `pipelines/default/prompts/modules/memory-search.md:4-24` — mandatory file-first protocol.
- [L2] `app/prompting.py:59-81` — project/repository-scoped personal memory loader.
- [L3] `app/session.py:1909-1921` — backend-connect seam and project path.
- [L4] `app/workspace.py:405-468` — tracked-file ownership/dirty-tree invariant.
- [L5] `app/pipeline.py:568-595`; `app/manager.py:337,882-891` — prompt assembly and later worker formatting.
- [L6] `app/tm.py:165-179` — task-number directory guard.
- [L7] `app/ia/runtime.py:901-920,964-1007` — pinned evidence path/blob/SHA resolution.
- [L8] `app/ia/project_distribution.py:425-475,490-550` — current manifest/destination owner.
- [L9] `app/ia/project_knowledge.py:294-316` — current-file source text lookup.
- [L10] `app/pipeline.py:25-26`; `app/prompting.py:18-23` — platform pipeline roots.
- [L11] `.gitignore:9-10` — current `workers/` ignore + old negation.
- [L12] Task card #430 and follow-up from Orchestra-orchestrator, 2026-09-01 — user decision,
  ownership boundaries, supplied fleet measurement, no-foreign-repo constraint.
- [L13] `docs/kb/{data-locality,knowledge-base-architecture,task-storage-architecture,prompt-delivery,repo-ops,agent-memory-architecture,test-oracles,prime-agent}.md`, sections
  `Установлено`/`Отвергнуто` — promoted project memory read before code scan.
- [L14] `git rev-list HEAD..main`, merge-base→main owner diff and `git show {HEAD,main}:pipelines/default/prompts/roles/orchestrator.md`,
  2026-09-01 — moving-owner drift and `<artifact-reading>` 0/2 control.
- [L15] `app/ia/knowledge.py:676-689` — current evidence-import path allowlist.
- [L16] `app/ia/cutover.py:296-320`; `app/manager.py:741-753,1773-1775` — scope-less receipt/worker prompt seams.
- [L17] `app/session.py:1301-1341`; `app/manager.py:574-590` — hot memory refresh reads worktree path.
- [L18] `docs/tasks/430/codex-review-research.md` — Luna completeness/adversarial review Rounds 1–2.
