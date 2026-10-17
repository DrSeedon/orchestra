# Context for item-09

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 9a23a554d..c15c82cad 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -1,27 +1,56 @@
 # Changelog
 
 > **Слияние двух контуров, 04.08.2026.** До этой даты ноутбук и VPS вели CHANGELOG
 > независимо, поэтому номера версий 2.31.0-2.33.0 использованы ДВАЖДЫ для разного
 > содержания: ниже сперва блок VPS, затем блок ноутбука. Формат чинится задачей #52.
 
 
+## v2.35.6 — 2026-08-04 — задачи 142, 143, 146, 63, 65, 70, 71, 72, 73, 74, 75, 80
+
+<!-- tasks: 142, 143, 146, 63, 65, 70, 71, 72, 73, 74, 75, 80 -->
+
+- **#63** (2026-08-04) — бэкфилл RAG сходится: долг к нулю за 4 прохода вместо «никогда», индексация больше не берёт файлы под `.gitignore`
+  - подробности: `docs/tasks/63/report.md`
+- **#65** (2026-08-04) — `/api/sessions`: 54.3 КБ → 4.5 КБ по проводу
+  - подробности: `docs/tasks/65/report.md`
+- **#70** (2026-08-04) — GET, который не дошёл, повторяется; исчерпанные попытки видны юзеру
+  - подробности: `docs/tasks/70/report.md`
+- **#71** (2026-08-04) — `/api/orchestrators` похудел с 21.3 КБ до 1.5 КБ по проводу
+  - подробности: `docs/tasks/71/report.md`
+- **#72** (2026-08-04) — два последних крупных ответа: 145.5 КБ → 1.2 КБ и 27.5 КБ → порции по ~8 КБ
+  - подробности: `docs/tasks/72/report.md`
+- **#73** (2026-08-04) — переиндексация CHANGELOG подешевела с 1190 до 21 секунды: эмбеддинги неизменившихся чанков переиспользуются
+  - подробности: `docs/tasks/73/report.md`
+- **#74** (2026-08-04) — жирная строка больше не едет полмегабайта, а обрезка видна и разворачивается
+  - подробности: `docs/tasks/74/report.md`
+- **#75** (2026-08-04) — `_API_TIMEOUT_MS` 3.5 → 2 с
+  - подробности: `docs/tasks/75/report.md`
+- **#80** (2026-08-04) — у блокирующей операции появился выход, вторичный провал перестал её создавать
+  - подробности: `docs/tasks/80/report.md`
+- **#142** (2026-08-04) — где теряется время на orchestra.seedon.ru
+  - подробности: `docs/tasks/142/report.md`
+- **#143** (2026-08-04) — почему рвётся отдача с orchestra.seedon.ru: механизм
+  - подробности: `docs/tasks/143/report.md`
+- **#146** (2026-08-04) — зеркало orc.seedon.ru: обход обрыва 16 КБ
+  - подробности: `docs/tasks/146/report.md`
+
 <!-- ниже — велось вручную до 04.08.2026 -->
 <!-- tasks: 100, 103, 104, 108, 109, 111, 113, 114, 115, 12, 120, 126, 13, 131, 139, 141, 15, 16, 17, 18, 19, 2, 20, 21, 22, 27, 28, 29, 30, 31, 32, 33, 34, 37, 38, 4, 40, 42, 44, 45, 47, 49, 5, 50, 52, 53, 54, 55, 56, 58, 59, 61, 62, 64, 66, 67, 68, 69, 8, 88, 89, 9, 90, 91, 92, 93, 95, 97, 98-grok-runtime-audit, 98-limit-wake, 99, adhoc-231036, arch-audit, claude-md-cleanup, codex-cache-research, codex-cwd, codex-sessions, codex-sleep, codex-worker-parity, context-engineering, cost-tokens, fix-worktree-gitignore, git-safety, guards, pipeline-rebase, polish-tg, proxy-fix, rag-orchestra, rag-vps-deploy, refactor-ecs, self-analysis, sol-runtime-fixes, subagent-telemetry, tg-bridge-3bugs, tg-message-delivery, usage-analytics, visibility, worker-spawning, wt-cleanup -->
 
 > Всё, что ниже, писали руками до перехода на сборку из отчётов (#52).
 > Новые записи добавляет `scripts/build-changelog.py` — ВЫШЕ этой границы.
 
 ## v2.35.5 — 2026-08-04 — #69 миграция больше не путает scope с репозиторием
 
 ### Fixed
 - 🧭 **`migrate_agent.py` спрашивает репозиторий воркера у git, а не выводит из scope** (`worker_repo`, `target_worktree`, `slugify_repo`). `--from-scope/--to-scope` работали одновременно как каталог проекта и как git-репозиторий: бандл собирался из корневого репо, а слаг каталога считался от scope — при этом платформа строит его от **repo root** (`create_worktree`). Для проекта с вложенными репозиториями это давало бандл без нужной ветки и путь, куда платформа никогда не заглянет.
   - Репозиторий берётся так же, как это делает сама платформа: `cd <worktree> && cd "$(git rev-parse --git-common-dir)/.." && pwd`. Не прочитали — фолбэк на scope, но с явным предупреждением, что для вложенных репозиториев он неверен.
   - Целевой путь считается **один раз на воркера** (`target_worktree`) и переиспользуется транскриптом, worktree и строкой БД — расходящиеся копии этой формулы и были причиной.
   - Отсутствие целевого репозитория на приёмнике теперь падает громко: перенос воркера в чужой репозиторий молча выдал бы ему чужую историю.
   - **Triggered case**: у seedon внутри проекта живут `site/` и `infra/` — независимые репозитории со своими origin, оба в `.gitignore` родителя. В #67 я объявил их сессии невосстановимыми именно потому, что искал репозитории соседями по имени вместо `rev-parse --show-toplevel`.
   - Проверено сквозняком: воркер вложенного репозитория переносится в СВОЙ репозиторий (в копии лежит `site.txt`, а не файлы корневого репо) и делает коммит. Мутация «репозиторий снова из scope» роняет этот тест.
 - 🌿 **`base_branch_strategy=parent` через границу репозитория больше не блокирует спавн** (`app/manager.py::_resolve_base_branch`, `_crosses_repo_boundary`, `app/workspace.py::repo_root`). Родитель в корневом репо на фиче, ребёнок в `site/` → ветки родителя там нет. Раньше — `ValueError` с текстом «local base branch does not exist», по которому причину не угадать. Теперь: если репозитории РАЗНЫЕ (сравнение через git, а не по префиксу пути), база берётся из mainline репозитория ребёнка с WARNING, называющим оба репозитория; если репозиторий ТОТ ЖЕ — ошибка летит наверх без изменений, потому что там отсутствие ветки настоящая ошибка. Не смогли определить репозитории — считаем, что границы нет: исходная ошибка честнее выдуманного объяснения.
 
 ### Known tradeoff
 - ⚠️ **Сквозной тест миграции вложенного репо требует беспарольного sudo** (маркер `needs_two_users` из #55, пропуск громкий). Без него остаются юнит-тесты формулы пути.
 - ⚠️ Молчаливой подмены базы нет, но WARNING виден только в логах — воркер узнает о смене базы не из своего промпта. Для `strategy=parent` в чужой репозиторий это осознанный компромисс: альтернатива — отказ в спавне.


## Later history of the touched files on main (after this commit)

279 later commits touch these paths; the first 40 (oldest first):
971399f08 2026-07-26 fix: worktree naming by repo root; drop auto-commit of user WIP on spawn
c866e5463 2026-07-27 compact summary: не форвардить в TG, флаг LOG_COMPACT_SUMMARY
df909ae6b 2026-07-27 docs: #90 T3 в CHANGELOG/TODO
789b8d9e5 2026-07-27 models: выпилить Opus 4.6/4.8, старые id ремапить на Opus 5
a5f0ef925 2026-07-27 docs(95): research — Grok Build as third Orchestra runtime
fd31abe9f 2026-07-27 fix(95): T2 — isolate worker MCP from the user's servers
95672ac70 2026-07-27 fix(95): T3 — session resume, and a race that silently disabled MCP isolation
61d688d1b 2026-07-27 test(95): T4 — lock down usage, cost and the context denominator
5cf67ecbb 2026-07-27 fix(95): T5 — tool approval, error paths, and a deterministic atomicity test
66604dcd1 2026-07-28 #95: WIP #95: T6 — grok provider bucketing, cache policy, orchestrator subagents flag
aa274a5df 2026-07-28 fix: send_file — таймаут 180с под flood control + класс исключения в ошибке
69475f5ba 2026-07-28 docs(95): T7 — Grok field guide, failure map and unverified registry
3330038d7 2026-07-28 test: убрать wall-clock флейк в тестах TG-моста + перенумеровать CHANGELOG
23ea33d85 2026-07-28 #98: #98: skip task numbers whose docs/tasks/<id>/ already exists
0e15dcd31 2026-07-31 #108: #108: план правок по результатам аудита (фаза 2)
273e13db7 2026-08-03 #130: WIP: спасено оркестратором при исчерпании квоты Codex
20acdab55 2026-08-03 #12: #12: спавн не пишет поверх отслеживаемых файлов и не оставляет untracked мусор
b41f617ce 2026-08-03 #13, #9, #19: #13: CHANGELOG v2.31.0 и Known tradeoff отдельной секцией в отчёте
3b2e4c9e6 2026-08-03 #28: #28: reindex ставит задачу в очередь и отвечает сразу; сессионный прогон режется срезами
d95109b13 2026-08-04 #130: #130: актуализировать CHANGELOG и README
c65fe53e0 2026-08-04 #21: #21: /api/sessions не сканирует таблицу логов на каждый запрос
427d92712 2026-08-04 #34: #34: фаза 1 — права на спавн решает манифест, фронтматтер-фолбэк мёртв
8d80c0525 2026-08-04 #28, #37: #28: заглушки backfill в test_api приведены к сигнатуре с session_name
96d60a261 2026-08-04 #49: #49: chart.js со своего домена, defer, ноль внешних зависимостей
b49c1acc1 2026-08-04 #53: #53: плашка «Новые bug reports» удалена целиком
f1220edf7 2026-08-04 #53: #53: осиротевший GET /api/report_bug/status удалён
00fd272a2 2026-08-04 #55: #55: фаза 1 — маска ошибок git уже закрыта в main; root-владение живо и шире, чем в репорте
c7eb88e52 2026-08-04 merge: контур VPS + контур ноутбука
ef9c8057b 2026-08-04 #62: #62: фаза 1 — рабочие копии сносит pytest в главном чекауте, воспроизведено
7a6f0ab75 2026-08-04 #69: #69: репозиторий воркера от git, слаг от repo root; strategy=parent через границу репо
84d58f6a0 2026-08-04 #52: #52: исследование — N-1 конфликт по построению, правило не выполняется 0 из 8, материал уже есть в отчётах
5e60cd090 2026-08-04 changelog: сборка v2.35.6 из отчётов задач (12 записей, скриптом)
1cb218913 2026-08-04 Revert "changelog: сборка v2.35.6 из отчётов задач (12 записей, скриптом)"
2a5782d49 2026-08-04 revert #52: убрал автосборку CHANGELOG из отчётов задач
81caddb41 2026-08-06 changelog v2.36.0: миграция промптов под Opus 5, перепись скилла артефактов, вставка в каретку; правило про сырой источник доки
afc99e2de 2026-08-10 #173: #173: fix prompt P0 defects
ad423c58f 2026-08-11 #185: #185: add chat event timeline navigation
05e9a8062 2026-08-11 #174: #174: import DB history into Claude
2815c1683 2026-08-11 #174: #174: import DB history into Codex
8b0735950 2026-08-12 #212: #212: restore truncated Read images from full log

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 971399f08 fix: worktree naming by repo root; drop auto-commit of user WIP on spawn

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 2b1d6926f..8c6667379 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -1,7 +1,22 @@
 # Changelog
 
+## v2.24.2 — 2026-07-26
+
+### Removed
+- 🗑 **`_auto_commit_if_dirty` — спавн больше не коммитит незакоммиченную работу юзера** (`app/manager.py`). Функция делала `git add -A` + `git commit` в рабочем чекауте перед созданием worktree, обосновывая это тем, что «worktree наследует unstaged junk».
+  - **Обоснование было ложным** — проверено экспериментом на чистом репо: `git worktree add <path> HEAD` строит дерево из коммита, unstaged-правки и untracked-файлы источника в него не попадают вообще. Вызывалась функция только при `use_worktree and repo_path`, то есть ровно в единственном случае, где не нужна.
+  - **Triggered case**: оркестратор inscryption-ai обнаружил, что Orchestra закоммитила в `main` чужую папку `.serena/` перед спавном воркера. Это происходило при каждом спавне с dirty-репо, начиная с `1e39c47`.
+  - Убраны 2 мока в `tests/test_manager.py` (функцию саму никто не тестировал).
+
+### Fixed
+- 📁 **Директория и ветка worktree именуются по repo root, а не по `scope` сессии** (`app/workspace.py:285-294`). Было: `wt_dir = WORKTREE_ROOT / _slugify(scope)`, репозиторий при этом брался из `repo_path` — два независимых источника, никем не сверяемых.
+  - **Симптом**: воркеры `impl-deck-search`, `impl-inscryption`, `feat-inscryption-ai` лежали в `worktrees/home-maxim-cursor-cog-second-brain/`, хотя `git-common-dir` = `/mnt/data/Projects/Python/inscryption-ai/.git`. Проявляется, когда родитель живёт в одном проекте, а спавнит воркера в другой. Ветки при этом получали имена вида `feat/home-maxim-cursor-cog-second-brain/<name>` в чужом репо.
+  - **Почему важно**: это источник серии ложных баг-репортов «`repo_path` игнорируется» — оркестраторы читали путь вместо `git-common-dir` и делали вывод о промахе. Расследование `fix-repo-path` тогда сняло обвинение с `repo_path`, но настоящую причину не нашло.
+  - Параметр `scope` удалён из `create_worktree` — после фикса он не использовался. Существующие worktree не затронуты (их пути записаны в БД).
+  - **Tests**: `test_repo_namespaced_path`, `test_branch_namespaced_by_repo`, `test_worktree_belongs_to_requested_repo`, `test_different_repos_no_collision` (заменил `test_different_scopes_no_collision` — свойство «разные scope → разные пути» перестало существовать). 152 зелёных.
+
 ## v2.24.1 — 2026-07-01
 
 ### Added
 - 🔀 **`POST /api/proxy/set-env` — сменить прокси кнопкой без ручной правки .env** — фронт шлёт `{"id": "contabo-de"}`, endpoint находит прокси в `PROXY_LIST` и переписывает ТОЛЬКО строки `HTTPS_PROXY`/`HTTP_PROXY` в `.env` (line-surgery через `(?m)^KEY=.*$`, токены TG/YouGile нетронуты). `url=="direct"` → пустое значение (прямой выход). Ответ `{"ok": true, "wrote": <url>, "need_restart": true}`.
   - **НЕ hot-switch**: `os.environ` НЕ трогается, DB НЕ трогается. `.env` остаётся источником истины, применяется юзером через рестарт. Возврат старого `select_proxy` (мутировал env на лету → рассинхрон) исключён by design.
### c866e5463 compact summary: не форвардить в TG, флаг LOG_COMPACT_SUMMARY

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 8c6667379..f1a4197a5 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -1,7 +1,15 @@
 # Changelog
 
+## v2.24.3 — 2026-07-27
+
+### Changed
+- 🔇 **Compact summary больше не улетает в TG** (`app/session.py:1201`). Полный текст саммари логировался типом `text`, а `text` в мосте = речь агента → мгновенный форвард в топик простынёй на несколько килобайт с @mention юзера.
+  - Вернуть старое поведение: `LOG_COMPACT_SUMMARY=1` в `.env` (по умолчанию `0`, задокументировано в `.env.example`).
+  - Саммари не теряется: живёт в `session.last_summary`, в preamble нового контекста (лог `user_message`) и в ответе `compact_worker`. В чат теперь идёт одна строка `compact done: X% → Y% (summary N chars)`.
+  - **Triggered case**: юзер получил в TG стену текста после компактификации оркестратора и попросил флаг, а не правку поведения намертво.
+
 ## v2.24.2 — 2026-07-26
 
 ### Removed
 - 🗑 **`_auto_commit_if_dirty` — спавн больше не коммитит незакоммиченную работу юзера** (`app/manager.py`). Функция делала `git add -A` + `git commit` в рабочем чекауте перед созданием worktree, обосновывая это тем, что «worktree наследует unstaged junk».
   - **Обоснование было ложным** — проверено экспериментом на чистом репо: `git worktree add <path> HEAD` строит дерево из коммита, unstaged-правки и untracked-файлы источника в него не попадают вообще. Вызывалась функция только при `use_worktree and repo_path`, то есть ровно в единственном случае, где не нужна.
### df909ae6b docs: #90 T3 в CHANGELOG/TODO

diff --git a/CHANGELOG.md b/CHANGELOG.md
index f1a4197a5..8dafa9fcb 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -1,7 +1,28 @@
 # Changelog
 
+## v2.25.0 — 2026-07-27 — #90 lifecycle T1–T3
+
+Аудит жизненного цикла worktree/merge (`docs/tasks/90/audit.md`, 12 подтверждённых дефектов, 19 экспериментов). Реализация идёт вертикальными срезами T1→T7; T4–T7 заморожены до сброса недельной квоты Codex (2 августа).
+
+### Added
+- 🌿 **Persisted base-branch contract** (T1; `app/db.py`, `app/session.py`, `app/workspace.py`, `app/routes/sessions.py`, `app/mcp_stdio.py`). Колонки `base_branch TEXT DEFAULT ''` и `needs_switch INTEGER DEFAULT 0`; база спавна резолвится ОДИН раз (explicit → symbolic remote HEAD → единственная local `main`/`master`) и хранится в сессии. `merge`/`switch`/`wip`/`kill` читают её вместо литерала `main`.
+  - **Почему не «угадать по HEAD»**: после `checkout feature/x` symbolic HEAD равен feature-ветке — mainline задним числом не восстановить. Неоднозначная legacy-строка теперь fails loud до любой Git-операции, а не мержит в случайную ветку.
+  - **Triggered case**: главная ветка ≠ `main` — Aperant живёт на `develop`, VPN-Service держит и `main`, и `master`.
+
+### Changed
+- 🔒 **Merge идёт в checkout-владельца target и отклоняет грязный target** (T2; `app/workspace.py`). Слияние в ветку, вычекаченную в родительском worktree, выполняется там же; auto-stash из merge-пути удалён — незакоммиченные правки возвращаются юзеру списком путей, ни target, ни ветка воркера не трогаются. Prunable worktree metadata больше не даёт 500 (найдено Codex-ревью).
+
+### Fixed
+- ♻️ **Squash-коммит атомарен: отказ хука откатывает target** (T3; `app/workspace.py`). Провал `git commit` (pre-commit hook, related и unrelated пути) теперь возвращает HEAD/index/worktree на исходный `old_head` и верифицирует откат; ветка воркера не меняется. Раньше падение оставляло cherry-pick'нутые коммиты в target и рапортовало ошибку — состояние «наполовину смержено».
+- 🔗 **`merge_worker` больше не печатает `FAILED — unknown` при успешной линковке** (T3; `app/tm.py`, `app/routes/sessions.py`, `app/mcp_stdio.py`). `link_commits_to_task()` возвращал task-row или `None`, а MCP читал тот же объект как `{ok, added, error}` — успех без ключа `ok` рисовался безымянной ошибкой. Теперь функция отдаёт стабильный DTO `{ok, added, task_id | error}`, неизвестная задача даёт явный текст.
+  - **Triggered case**: два мержа подряд отрапортовали провал при реально успешном слиянии; статус задачи ставился руками.
+  - **Tests**: `test_related_commit_failure_rolls_back_target_and_preserves_worker`, `test_unrelated_commit_failure_rolls_back_target_and_preserves_worker`, `test_merge_links_commits_with_normalized_sqlite_results`, `test_merge_worker_formats_normalized_and_legacy_link_results`.
+
+### Known tradeoff
+- До рестарта Orchestra живой FastAPI держит старый код `app/routes/`, а MCP-процессы стартуют заново и берут свежий → `FAILED — unknown` и `target branch '' does not exist` ещё воспроизводятся. Обход: `merge_worker(name, target="main")` явно.
+
 ## v2.24.3 — 2026-07-27
 
 ### Changed
 - 🔇 **Compact summary больше не улетает в TG** (`app/session.py:1201`). Полный текст саммари логировался типом `text`, а `text` в мосте = речь агента → мгновенный форвард в топик простынёй на несколько килобайт с @mention юзера.
   - Вернуть старое поведение: `LOG_COMPACT_SUMMARY=1` в `.env` (по умолчанию `0`, задокументировано в `.env.example`).
### 789b8d9e5 models: выпилить Opus 4.6/4.8, старые id ремапить на Opus 5

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 8dafa9fcb..64ae417ab 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -1,7 +1,15 @@
 # Changelog
 
+## v2.25.1 — 2026-07-27
+
+### Removed
+- 🗑 **Opus 4.6 и 4.8 выпилены из реестра моделей** (`app/models.py`, `app/tg_bridge.py`, `app/static/js/app.js`). Убраны из `MODELS`, `CONTEXT_LIMITS`, `BACKENDS`, `TOKEN_PRICES`, семантических алиасов, короткиx имён TG и палитры дашборда — в выпадашке остаются только актуальные модели.
+  - Старые id (`claude-opus-4-8[1m]`, `claude-opus-4-6`, с суффиксом и без) **ремапятся на `claude-opus-5[1m]`** — тем же приёмом, что `claude-sonnet-4-6` → Sonnet 5. Сессия со старой моделью в БД поднимется на Opus 5, а не упадёт.
+  - Заодно удалён мёртвый auto-bump `effort low/medium → high` для 4.8 в `backend_claude.py` (auto-downgrade `xhigh → high` для Claude остаётся — он про API-ограничение, не про модель).
+  - Живых сессий на 4.6/4.8 в БД не было ни одной (замер по `sessions.model`); единственный воркер на 4.8 переведён на Opus 5 до правки.
+
 ## v2.25.0 — 2026-07-27 — #90 lifecycle T1–T3
 
 Аудит жизненного цикла worktree/merge (`docs/tasks/90/audit.md`, 12 подтверждённых дефектов, 19 экспериментов). Реализация идёт вертикальными срезами T1→T7; T4–T7 заморожены до сброса недельной квоты Codex (2 августа).
 
 ### Added
### a5f0ef925 docs(95): research — Grok Build as third Orchestra runtime

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 64ae417ab..dc56b652c 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -1,7 +1,28 @@
 # Changelog
 
+## v2.26.0 — 2026-07-27 — #95 Grok Build runtime (T1)
+
+Четвёртый рантайм наравне с `claude`/`codex`/`opencode` (`docs/tasks/95/research.md`, `plan.md`). Мотив — отдельный пул квоты SuperGrok: сам этот research не получил cross-review, потому что пул Codex кончился до 2 августа. Пока **registry-only**: рантайм выбирается явно, дефолты `pipeline.yaml` не тронуты.
+
+### Added
+- 🤖 **`GrokBackend` — ACP (Agent Client Protocol) поверх `grok agent stdio`** (`app/backend_grok.py`). Долгоживущий процесс + JSON-RPC 2.0 по stdio, аналог `codex app-server`. Резюм сессии через `session/load`, прерывание через `session/cancel` (проверено: срабатывает мгновенно, `stopReason=cancelled`, стрим встаёт). Модель `grok-4.5`, контекст **500 000** (значение рантайма; статьи про «256K» опровергнуты).
+- 🧩 **Регистрация рантайма и модели** (`app/runtime_registry.py`, `app/models.py`). `_infer_backend()` отправлял всё, что не `gpt-*`/`claude-*`, в **`opencode`** — незарегистрированный `grok-4.5` молча уехал бы на чужой рантайм. Добавлено правило `grok-*` → `grok` + провайдер `x-ai`; провайдер-квалифицированные id вроде `x-ai/grok-4` намеренно остаются на `opencode`.
+
+### Reasoning
+- **Отдельный бэкенд, не общий слой с Codex.** Замер по строкам: из 1105 строк методов `backend_codex.py` лишь **220 (20%)** — общий JSON-RPC транспорт, а **826 (75%)** — собственный словарь событий Codex (`item/started`, `item/completed`, `collabAgentToolCall`), которого у Grok нет вовсе. Расхождение ~80% при пороге 30%. Прецедент: `backend_opencode.py` тоже не импортирует из `backend_codex.py` ничего — общий слой один, 16-строчный `BackendLike`.
+- **Системный промпт идёт ТОЛЬКО через `--agent-profile`** (временный `.md` с YAML-frontmatter, удаляется на `disconnect`). ACP-поля `systemPrompt`/`_meta.systemPrompt`/`instructions` принимаются и **молча игнорируются** — воркер работал бы вообще без промпта. Проверено канарейкой до написания кода.
+- **`mid_turn_inject=False`.** Prompt, посланный во время хода, не рулит им, а попадает в нативную очередь и исполняется ОТДЕЛЬНЫМ ходом → N посылок = N `turn_end`. Цикл событий завершается по опустевшей очереди, а не по первому `prompt_complete`, иначе ход из очереди стримится в никуда.
+- **Стоимость берётся из рантайма.** `costUsdTicks` = **1e-10 USD** (не 1e-9 — первая версия research ошиблась в единицах и была ретрактирована). Сходится в ноль на 4 замеренных ходах с формулой `((in−cached)·$2 + cached·$0.30 + out·$6)/1e6`. Реальная ставка кэша **$0.30/M**, а не $0.50 из всех статей. Цены живут в `backend_grok.py`, а не в `TOKEN_PRICES` — там нет тира `cached`.
+
+### Known issue
+- **Форма терминального исчерпания квоты неизвестна** — исчерпать SuperGrok не удалось. `_classify_error` не угадывает паттерн: неопознанная ошибка остаётся `error` и падает громко (`report_bug`, без тихого ретрая). Классификация появится после первого реального упора в лимит.
+- **Чужие MCP-серверы пока не подавлены** (T2). Grok сам подхватывает серверы из `~/.claude.json`/`.mcp.json` и транслирует их env — во время research так утёк живой `OPENROUTER_API_KEY`. Фабрика уже собирает набор явно из наших источников, но подавление неявного discovery — отдельный тикет.
+
+### Tests
+`tests/test_backend_grok.py` (33): маппинг событий на реальном дампе, идемпотентность `turn_end` при двух сигналах завершения, `x-ai/grok-4` не перехватывается, трансляция MCP в ACP-форму (env — список пар, не словарь), три замеренных хода как фикстуры стоимости. Плюс `grok` добавлен в контрактный `test_backend_classes_satisfy_structural_contract`.
+
 ## v2.25.1 — 2026-07-27
 
 ### Removed
 - 🗑 **Opus 4.6 и 4.8 выпилены из реестра моделей** (`app/models.py`, `app/tg_bridge.py`, `app/static/js/app.js`). Убраны из `MODELS`, `CONTEXT_LIMITS`, `BACKENDS`, `TOKEN_PRICES`, семантических алиасов, короткиx имён TG и палитры дашборда — в выпадашке остаются только актуальные модели.
   - Старые id (`claude-opus-4-8[1m]`, `claude-opus-4-6`, с суффиксом и без) **ремапятся на `claude-opus-5[1m]`** — тем же приёмом, что `claude-sonnet-4-6` → Sonnet 5. Сессия со старой моделью в БД поднимется на Opus 5, а не упадёт.
### fd31abe9f fix(95): T2 — isolate worker MCP from the user's servers

diff --git a/CHANGELOG.md b/CHANGELOG.md
index dc56b652c..488757314 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -1,7 +1,30 @@
 # Changelog
 
+## v2.26.1 — 2026-07-27 — #95 Grok T2: изоляция MCP
+
+Закрытие канала утечки, а не гигиена: в артефакте T1 оказался живой ключ стороннего сервиса, потому что Grok сам поднимает чужие MCP-серверы и транслирует их env.
+
+### Fixed
+- 🔒 **Грок-воркер поднимается РОВНО с нашим набором MCP-серверов** (`app/backend_grok.py`). Два слоя: Orchestra-владеемый `GROK_HOME` (`data/grok-home`, в `.gitignore`) с `[compat.claude] mcps = false` — и проверка фактического состава на коннекте. Чужой сервер → `GrokMcpIsolationError`, воркер **не стартует** со списком нарушителей в тексте ошибки.
+  - `auth.json` — симлинк на пользовательский, чтобы обновление токена не протухало в приватной копии. Каталог стабильный, а не временный: там же лежит session store, от него зависит резюм (T3).
+- ⚙️ **`GROK_BIN` из окружения бьёт автопоиск в PATH** (`app/backend_grok.py`). Раньше `shutil.which()` шёл первым, и посторонний `grok` в PATH молча выигрывал у явной настройки.
+
+### Reasoning
+Замеры, определившие конструкцию (docs/tasks/95):
+- **`session/new.mcpServers` МЕРДЖИТСЯ с обнаруженным, а не замещает его.** Передал только `orchestra` — получил `{orchestra, websearch, mcp-pandoc}`. Передал пустой список — всё равно два чужих сервера.
+- **Единственный рабочий тумблер `[compat.claude] mcps = false` читается ТОЛЬКО из user-конфига.** Тот же ключ в проектном `.grok/config.toml` игнорируется (`on (default)` против `OFF (config)`). Правкой `~/.grok/config.toml` чинить нельзя — это личный файл юзера, сломало бы ему интерактивный grok. Отсюда собственный `GROK_HOME`.
+- **`GROK_HOME` в плане был отклонён как ломающий авторизацию — замер это опроверг:** песочница с симлинком на `auth.json` логинится штатно (`logged in with grok.com`).
+- **Источники discovery (точный список):** `~/.claude.json` (top-level + 47 per-project записей), `.mcp.json` в проекте, `~/.grok/config.toml`, проектные `.grok/config.toml` вверх до корня репо, плагины.
+- **`.mcp.json` подавляется не тумблером, а folder-trust:** появление этого файла само снимает доверие с каталога, и в headless сервер не стартует. На это не полагаемся — рантайм-проверка ловит его независимо.
+
+### Known tradeoff
+Проверка на коннекте сначала опиралась на `_x.ai/mcp/server_status`, и это давало **ложное «чисто»**: наш `orchestra` рапортует `ready` уже ПОСЛЕ первого хода, а `mcp_initialized` приходит раньше — набор на момент проверки был пуст. Теперь состав берётся из `_x.ai/mcp/servers_updated` (приходит рано и сам является каналом утечки — именно он транслировал ключ), `server_status` остаётся дополнительным сигналом.
+
+### Tests
+`tests/test_backend_grok.py` (43): отказ коннекта при чужом сервере, состав только из наших источников, roster из `servers_updated` (регрессия на ложное «чисто»), `GROK_HOME` с отключённым claude-compat и симлинком, fail loud без кредов, инжект `GROK_HOME` поверх унаследованного, приоритет `GROK_BIN`. Живьём: с песочницей утечки нет, при обходе изоляции коннект отклонён.
+
 ## v2.26.0 — 2026-07-27 — #95 Grok Build runtime (T1)
 
 Четвёртый рантайм наравне с `claude`/`codex`/`opencode` (`docs/tasks/95/research.md`, `plan.md`). Мотив — отдельный пул квоты SuperGrok: сам этот research не получил cross-review, потому что пул Codex кончился до 2 августа. Пока **registry-only**: рантайм выбирается явно, дефолты `pipeline.yaml` не тронуты.
 
 ### Added
### 95672ac70 fix(95): T3 — session resume, and a race that silently disabled MCP isolation

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 488757314..7c2d2d665 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -1,7 +1,28 @@
 # Changelog
 
+## v2.26.2 — 2026-07-27 — #95 Grok T3: резюм сессии
+
+### Fixed
+- 🔥 **Гонка на `config.toml` общего `GROK_HOME` (изоляция MCP могла отключаться сама)** (`app/backend_grok.py`). `ensure_grok_home()` перезаписывал файл на КАЖДОМ коннекте обычным `write_text` — это truncate + write. Воркер, стартующий в этом окне, читал **пустой** конфиг: без `mcps = false` изоляция T2 выключена, чужие MCP-серверы поднимаются со своими секретами.
+  - **Замер:** 4 писателя + 4 читателя, 3 секунды → **57.9% чтений видели пустой файл** (17 626 из 30 466). После фикса на том же замере — **0%**.
+  - Фикс: запись через уникальный tmp + атомарный `rename`, плюс пропуск записи если содержимое совпадает. Тот же приём, что в `workspace.sync_agents_md`, и по той же причине.
+- 🔁 **Протухший `sessionId` больше не блокирует воркера навсегда** (`app/backend_grok.py`). Ключ store — пара `(cwd, sessionId)`, поэтому перенесённый или подчищенный worktree делал `session/load` вечно провальным, а коннект — невозможным. Теперь падение `session/load` → новая сессия + **громкое** предупреждение о том, что история недоступна. Тихо историю не теряем.
+- 📁 **Понятная ошибка при исчезнувшем worktree** — раньше был голый `FileNotFoundError` от спавна процесса, который называл путь, но не причину.
+
+### Known tradeoff
+Предупреждение о неудачном резюме сначала **не долетало до юзера**: оно несло старый `sessionId`, а `events()` отбрасывает нотификации с чужим id — сообщение о потерянной истории отфильтровывалось само собой. Ключ переименован в `staleSessionId`. Поймано живым тестом, который требовал появления предупреждения, а не только успешного коннекта.
+
+### Reasoning
+Замеры на живом CLI (риски, поставленные PM):
+- **Общий `GROK_HOME` для всех воркеров безопасен для сессий.** Два воркера, одновременный коннект, разные cwd → разные id, ходы не пересекаются (`ALPHA`/`BETA`). Session store разложен по URL-кодированному cwd, так что пересечений нет by design. Опасность была только в общем `config.toml` — см. выше.
+- **Резюм ПЕРЕЖИВАЕТ смену ветки в том же worktree.** `main` → `feature/x`, `session/load` вернул тот же id и вспомнил кодовое слово. Сессия привязана к пути, не к ветке — контракт «переживает рестарт» держится и при переключении ветки после мержа.
+- **Чужой cwd** с тем же id → `Path not found` → фолбэк в новую сессию (проверено: id другой, история честно недоступна).
+
+### Tests
+`tests/test_backend_grok.py` (48): атомарность записи конфига под конкурентным читателем, перезапись при дрейфе содержимого и отсутствие tmp-мусора, предупреждение о резюме не отфильтровывается маршрутизацией, отказ коннекта при отсутствующем worktree.
+
 ## v2.26.1 — 2026-07-27 — #95 Grok T2: изоляция MCP
 
 Закрытие канала утечки, а не гигиена: в артефакте T1 оказался живой ключ стороннего сервиса, потому что Grok сам поднимает чужие MCP-серверы и транслирует их env.
 
 ### Fixed
### 61d688d1b test(95): T4 — lock down usage, cost and the context denominator

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 7c2d2d665..c8e51e4ff 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -1,7 +1,24 @@
 # Changelog
 
+## v2.26.3 — 2026-07-27 — #95 Grok T4: usage/cost под замком тестов
+
+Кода почти нет — почти всё уже работало с T1. Ценность среза в том, что каждое допущение проверено, а не принято на веру: неверная стоимость не падает, она годами врёт в дашборде.
+
+### Verified (замерами на живом CLI, зафиксировано тестами)
+- 📏 **Знаменатель `context_pct` берётся из РАНТАЙМА, а не из нашей константы.** Проверено подменой `GROK_CONTEXT_LIMITS["grok-4.5"]` на заведомо неверные 12 345 → после коннекта окно стало 500 000, `context_pct` считается от него. Совпадение константы и рантайма (оба 500 000) прятало бы поломку механизма — тесты специально разводят эти значения. Это ровно та авария, что была с Opus, когда `CONTEXT_LIMITS` врал знаменателем и агент компактился не вовремя.
+- 🧮 **`turn_completed.usage` — ПОХОДОВЫЙ, не кумулятивный.** Ключевое отличие от Codex, где он накоплен за тред и требует вычисления дельты. Замер трёх ходов в одной сессии: `outputTokens` 49 / 22 / 23 (кумулятив дал бы 49 / 71 / 94), вход почти целиком уходит в кэш. Значит payload потребляется как есть, `cost_is_delta=True` корректен, машинерия дельт не нужна. Раньше это было моим НЕПРОВЕРЕННЫМ допущением.
+- 🧠 **`reasoningTokens` не биллятся поверх output** — тест сравнивает ход с ними и без них при равном `outputTokens`, стоимость обязана совпасть.
+- 💵 **Валюта уже корректна, правок не потребовалось**: `MODEL_COST_CURRENCY = '$'` (`app/static/js/utils.js`) используется для `cost_usd` и прайсинга моделей, `data-currency` (рубли задач и платежей) в этот путь не заходит. Grok идёт тем же маршрутом, что Claude/Codex.
+
+### Known issue
+- ⚠️ **Цены Grok намеренно НЕ регистрируются в общем `TOKEN_PRICES`.** `routes/system.py:_cost_cached_for()` пересчитывает историю для любой модели из этого словаря по claude-эвристике кэша (cache_read = 10% от input). У Grok кэш стоит $0.30 против $2.00 input, то есть 15%, — на реальном замеренном ходе эвристика завышает стоимость на **+27.6%**. Пока модель отсутствует в словаре, функция отдаёт сохранённое значение, посчитанное из `costUsdTicks`. Тест это прибивает: попытка «заодно зарегистрировать цены как у Claude» будет поймана.
+- Следствие: в выпадашке моделей у Grok не показываются `price_input`/`price_output` — как и у всех Codex-моделей по той же причине. Осознанный компромисс, не дефект.
+
+### Tests
+`tests/test_backend_grok.py` (58): окно из рантайма перебивает константу (и из `initialize._meta`, и из `session/new`), чужая модель в списке игнорируется, `context_pct` от рантайм-окна, cached-тир реально дешевле fresh, `cached > input` не даёт отрицательных токенов, неизвестная модель стоит 0 вместо догадки, reasoning не удваивается, usage не накапливается между ходами, Grok отсутствует в `TOKEN_PRICES` с проверкой размера ущерба.
+
 ## v2.26.2 — 2026-07-27 — #95 Grok T3: резюм сессии
 
 ### Fixed
 - 🔥 **Гонка на `config.toml` общего `GROK_HOME` (изоляция MCP могла отключаться сама)** (`app/backend_grok.py`). `ensure_grok_home()` перезаписывал файл на КАЖДОМ коннекте обычным `write_text` — это truncate + write. Воркер, стартующий в этом окне, читал **пустой** конфиг: без `mcps = false` изоляция T2 выключена, чужие MCP-серверы поднимаются со своими секретами.
   - **Замер:** 4 писателя + 4 читателя, 3 секунды → **57.9% чтений видели пустой файл** (17 626 из 30 466). После фикса на том же замере — **0%**.