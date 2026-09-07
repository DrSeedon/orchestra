# #524 — инвентаризация `.orchestra/`

Замер: 2026-09-06, дерево `/mnt/data/Projects/Python/orchestra` на `main` = `2b9235bc`.
Сырьё: `raw/tree-scan.txt`, `raw/records-analysis.txt`, `raw/records-duplication.txt`,
`raw/tasks-heavy-files.txt` (скрипты замера — `raw/records.py`, `raw/rec2.py`).
Ничего не удалено: задача даёт таблицу и список, удаляет владелец.

## Поправки к снимку в задании

- **Тем в KB не 16, а 40** (`ls .orchestra/kb/*.md | wc -l` = 41 вместе с README;
  `grep -c '^- \[' README.md` = 41). Переписанная база живёт на **несмерженной** ветке
  `task-525/kb-rewrite` (`401f5f3a` «40 тем в 16»); `git branch --merged main` её не показывает.
  Машинный ключ `` `fact:` `` в main по-прежнему в голове строки
  (`.orchestra/kb/token-efficiency.md:155`). Инвентаризация ниже — по main, а не по той ветке.
- `.orchestra/infra` в git **нет**: `git check-ignore -v` → `.gitignore:25:.orchestra/infra/`.
  Поэтому в worktree'ах его не существует, а в снимке задания он был.
- Реальный размер `kb/records` — **7.6 МБ JSON**, 51 МБ на диске: 12 759 файлов по ~600 Б,
  каждый занимает блок 4 КiB. Оверхед файловой системы — 43 МБ из 51.

## Таблица

| путь | размер | файлов | кто ПИШЕТ (file:line живого кода или «никто») | кто ЧИТАЕТ (file:line или «никто») | последняя запись (mtime) | вердикт |
|---|---|---|---|---|---|---|
| `.orchestra/kb/records/` | 51 МБ на диске / 7.6 МБ JSON | 12 759 | **никто.** Единственный писатель — `app/ia/project_knowledge.py:258` `write_record`; вызовов из `app/` нет, только `tests/test_project_knowledge_*.py`. Наполнено разово скриптом раздачи, 8 прогонов подряд | `app/ia/project_knowledge.py:305` `query_records` ← `app/ia/runtime.py:1722` ← `app/ia/runtime.py:2004` ← `app/routes/memory.py:42` ← MCP `search_memory` (`app/mcp_stdio.py:3518`). Плюс `tests/test_orchestra_layout_430.py:417` и `scripts/check_orchestra_paths.py:141` | 2026-08-28 07:25 — **все 12 759 одной пачкой**, за 9 суток ни одной новой записи | **удалить** |
| `.orchestra/kb/manifest.json` | 4.1 МБ | 1 | никто в `app/`; пишется упаковщиком `scripts/ia_pack.py:347` | `scripts/activate_project_knowledge.py:150` — только в момент разовой активации | 2026-08-28 | **удалить** (вместе с `records/`) |
| `.orchestra/kb/*.md` (темы + README) | 676 КБ | 41 | агенты руками; контракт — `scripts/check_kb_contract.py` | `app/kb_index.py:60` `kb_index_block` ← `app/manager.py:371` → **в системный промпт каждого агента на старте**; `scripts/check_instruction_contract.py:26` | 2026-09-06 | **живое** |
| `.orchestra/tasks/` | 108 МБ | 4508 | агенты; `app/review_coverage.py:200` пишет `review-attestation.json` | `app/tm.py:190` — существование `tasks/<n>/` запрещает переиспользовать номер задачи; `app/review_coverage.py:200` — гейт мержа; `tests/test_orchestra_layout_430.py` читает `tasks/430/evidence-bindings-frozen.json` | 2026-09-06 09:38 (`tasks/522/result.md`) | **живое** — каталоги задач не трогать |
| └ сырые прогоны в `tasks/` >300 КБ | 42.3 МБ | 47 | агенты (разовые выгрузки) | никто из кода, кроме `tasks/430/evidence-bindings-frozen.json` | 2026-08…09 | **архив** — список в `raw/tasks-heavy-files.txt` |
| `.orchestra/workers/` | 1.2 МБ | 189 | агенты (личная память) | `app/prompting.py:95` → системный промпт при каждой сборке; `app/manager.py:773` | 2026-09-06 09:38 | **живое** |
| `.orchestra/pipelines/` | 252 КБ | 27 | владелец | `app/pipeline.py:26` `PIPELINES_DIR` — единственный источник промптов и ролей | 2026-09-06 17:00 | **живое** |
| `.orchestra/guides/` | 92 КБ | 5 | агенты | никто из кода; адресные ссылки из корневых правил и KB | 2026-09-06 09:38 | **живое** |
| `.orchestra/layout.json` | 4 КБ | 1 | `app/orchestra_layout.py` (миграция) | `app/orchestra_layout.py:30`, `app/prompting.py:73` — без него спавн падает `ORCHESTRA_LAYOUT_MISSING` | 2026-09-03 | **живое** |
| `.orchestra/knowledge-pipeline.json` | 4 КБ | 1 | владелец | `app/knowledge_pipeline.py:19` | 2026-09-03 | **живое** |
| `.orchestra/project-context.toml` | 4 КБ | 1 | владелец | `app/mcp_stdio.py:3595` | 2026-09-03 | **живое** |
| `.orchestra/archive/` | 1.5 МБ | 61 | агенты (хроника закрытых веток) | никто из кода; только `rg` по требованию | 2026-09-05 12:08 | **архив** |
| `.orchestra/research/` | 148 КБ | 9 | никто | никто из кода; **0 ссылок из `kb/*.md`** (проверено `rg -ci -F` по 15 якорям) | контент 2026-05-31…06-15; mtime 09-03 — это `git mv` миграции #430 | **влить**, затем архив |
| `.orchestra/reviews/` | 100 КБ | 5 | никто | никто; 0 ссылок из KB | контент 2026-06-10/11 | **влить**, затем архив |
| `.orchestra/experiments/` | 472 КБ | 5 | никто | никто | контент 2026-08; mtime 09-03 от `git mv` | **архив** |
| `.orchestra/artifacts/` | 644 КБ | 12 | **никто.** `publish_artifact` пишет НЕ сюда: `app/artifacts.py:131` → `~/.local/state/orchestra/artifacts` | никто | mtime 09-03 от `git mv` | **архив** |
| `.orchestra/tg-media/` | 16 КБ | 2 | никто | никто | план реализован, ревью закрыто | **удалить** |
| `.orchestra/infra/` | 20 КБ | 3 | никто | никто; каталог вне git (`.gitignore:25`) | 2026-06-01 14:58 | **влить**, затем удалить |

## Главный вопрос: `kb/records/` + `manifest.json` — осадок

**Живой путь чтения есть, знаний в нём нет.**

1. **Он подключён к живому процессу.** `~/.local/state/orchestra/knowledge-v1/runtime-state.json`
   → `active_owner: "canonical"`, `project-knowledge-owner.json` → `active_owner: "project-local"`.
   Обе ветки гейта открыты, `app/main.py:404` поднимает рантайм безусловно. Проверено
   не по коду, а вызовом: `POST /api/memory/search` со `scope=/mnt/data/Projects/Python/orchestra`
   вернул записи с `"source_class":"immutable-evidence"` прямо из `.orchestra/kb/records/evidence/`.
2. **На СТАРТЕ агента его не читает никто.** Стартовый промпт берёт только оглавление тем
   (`app/kb_index.py:60` ← `app/manager.py:371`). `records/` читается исключительно по вызову
   `search_memory` в ходе работы.
3. **Записей за последнюю неделю — ноль.** Гистограмма mtime: единственный день `2026-08-28`,
   12 759 файлов. Писателя в живом коде нет вообще.
4. **Знаний, которых нет в `*.md`-темах, там нет ни одного байта.** Все 12 759 записей —
   `record_type: resource`, `source_class: immutable-evidence`, набор полей фиксирован:
   `git_blob, git_commit, project_id, source_path, source_sha256, stable_id, uri, storage, status`.
   Это **указатели на файлы**, а не факты. Содержимое `query_records` подтягивает из
   `root / source_path` в момент запроса.
5. **99.5 % указателей ведут в никуда.** `source_path` резолвится на диске у **64 из 12 759**.
   Остальные 12 695 смотрят в `docs/tasks/` (10 678), `docs/workers/` (1121), `docs/archive/` (352),
   `docs/kb/` (168) — в дерево, которого не существует с миграции #430 (`498c0d14`, 2026-09-03).
   Выжившие 64 — это 8 файлов (`CLAUDE.md`, `README.md`, `BUGS.md`,
   `docs/orchestrator-vps-onboarding.md`, `docs/tg-local-api-setup.md` и т.п.), которые агент
   открывает напрямую.
6. **Восьмикратный дубль.** 12 759 записей описывают **1612 различных `source_path`**;
   1581 путь записан ровно 8 раз. Различных `git_commit` — 8. То есть один и тот же импорт
   прогнали восемь раз и каждый раз завели новые `stable_id`.
7. **Цена.** Худший случай `search_memory` (запрос без совпадений = полный обход 12 759 файлов):
   **10.7 с на холодную, 2.3 с на прогретом кеше**. Совпадающий запрос отдаёт мусорный указатель
   раньше полезного лога, потому что `app/ia/runtime.py:2004` кладёт evidence **до** поиска по логам.
   На диске: 51 МБ × 18 worktree'ев = **665 МБ**, и каждый новый воркер платит их при чекауте.

**Что сломается при удалении.** Ровно одно место: `tests/test_orchestra_layout_430.py:417`
`_assert_all_historical_evidence_bindings` — `assert len(records) >= 12_759` и сверка с
`.orchestra/tasks/430/evidence-bindings-frozen.json` (1.3 МБ). Тест надо удалять тем же
коммитом; он проверяет не поведение платформы, а сохранность самого осадка.
`scripts/check_orchestra_paths.py:141` тоже читает `records/`, но, по TODO проекта, уже падает
до этого места (`ValueError` на строке 206) и цифр не печатает.
`query_records` на отсутствующем каталоге ничего не бросает: `glob` вернёт пусто, поиск честно
уйдёт в SQLite-логи (`app/ia/runtime.py:2010`). `manifest.json` нужен только
`scripts/activate_project_knowledge.py` в момент повторной активации — её не будет.

## Готовый список на удаление (исполняет владелец)

Каталог main-дерева `/mnt/data/Projects/Python/orchestra`:

| путь | размер на диске | что это |
|---|---|---|
| `.orchestra/kb/records/` | 51 МБ (12 759 файлов) | указатели на несуществующий `docs/`, 8 дублей на файл |
| `.orchestra/kb/manifest.json` | 4.1 МБ | опись тех же 12 759 указателей |
| `.orchestra/tg-media/` | 16 КБ (2 файла) | план и ревью реализованной фичи |
| `.orchestra/infra/` | 20 КБ (3 файла) | вне git; содержимое устарело, вливается в KB (см. `salvaged.md`) |
| `tests/test_orchestra_layout_430.py::_assert_all_historical_evidence_bindings` | — | обязателен к удалению тем же коммитом |
| `.orchestra/tasks/430/evidence-bindings-frozen.json` | 1.3 МБ | смысл имеет только вместе с `records/`; удалять последним |

Освобождается в main-дереве **56.4 МБ**; с учётом 18 worktree'ев — **≈665 МБ** на диске.
Из индекса git уходит 12 761 файл (`git ls-files .orchestra/kb` = 12 802 → 41).

Отдельным решением (в архив, не в удаление): 42.3 МБ сырых прогонов в `.orchestra/tasks`,
полный список с размерами — `raw/tasks-heavy-files.txt`.

## Найденные попутно расхождения

- `app/mcp_stdio.py:3518` — docstring `search_memory` гласит «not an agent MCP tool», но тул
  зарегистрирован `@mcp.tool()` и включён в `READONLY`/`REDUCER` наборы
  (`app/mcp_stdio.py:100,110`), то есть агентам он выдаётся. Либо описание врёт агенту,
  либо тул надо снимать с раздачи.
- `.orchestra/artifacts/` выглядит как выход `publish_artifact`, но тот пишет в
  `~/.local/state/orchestra/artifacts` (`app/artifacts.py:131`). Имя каталога вводит в заблуждение.
