# Срез: фактическая запись личной памяти агентов

Дата среза: 2026-08-12. Репозиторный срез — текущий worktree
`/home/kesha/orchestra/worktrees/home-kesha-bench219-p2-2/fan219-p2-write`.
SQLite во всех запросах открывался строго как
`sqlite3.connect('file:/home/kesha/bench219/orchestra-cut.db?mode=ro', uri=True)`.
Под «событием записи» ниже понимается зафиксированный в `logs` инструментальный вызов;
это нижняя граница, а не число байтов или число git-коммитов.

## Утверждения

1. **Память загружается сначала по имени агента, затем по имени роли; берётся первый
   непустой файл.** Уверенность: **CONFIRMED**. Артефакт: `app/prompting.py:59-78`,
   цитаты `for filename in (f"{name}.md", f"{role}.md" if role else None)` и
   `path = base / "docs" / "workers" / filename`.

2. **Память перечитывается с диска при переинжекте промпта, а не только при первом
   spawn.** Уверенность: **CONFIRMED**. Артефакт: `app/prompting.py:81-92`, цитаты
   `mem = load_worker_memory(name, role, scope)` и возврат нового
   `<worker-memory>` блока.

3. **При spawn непустая память добавляется в system prompt автоматически.** Уверенность:
   **CONFIRMED**. Артефакт: `app/manager.py:615-619`, цитаты
   `worker_memory = load_worker_memory(name, role, scope)` и
   `prompt += f"\n\n<worker-memory>...`.

4. **Инструкция агентам писать файл существует, но запись инициируется самим агентом
   перед DONE, а не отдельным серверным writer-механизмом.** Уверенность: **CONFIRMED**.
   Артефакт: `pipelines/default/prompts/modules/self-improvement.md:71-84`, цитаты
   `Before every DONE report, workers MUST ask` и `Yes → update
   docs/workers/<your-name>.md`.

5. **В текущем worktree лежит 35 файлов `docs/workers/*.md`; все 35 tracked, то есть
   незатреканных файлов этого шаблона нет.** Уверенность: **CONFIRMED**. Артефакт:
   `find docs/workers -maxdepth 1 -type f -name '*.md' | wc -l` → `35`;
   `git ls-files 'docs/workers/*.md' | wc -l` → `35`.

6. **Пустых файлов памяти нет; объём — 267608 байт, min/median/max —
   556/3704/45647 байт, самый большой `prompt-engineer.md`.** Уверенность:
   **CONFIRMED**. Артефакт: Python-команда по `Path('docs/workers').glob('*.md')`
   со `stat().st_size` → `n 35 zero 0 min 556 median 3704 max 45647
   max_file prompt-engineer.md total 267608`.

7. **Все 35 файлов текущего worktree принадлежат `kesha:kesha`.** Уверенность:
   **CONFIRMED**. Артефакт: `find docs/workers -maxdepth 1 -type f -name '*.md'
   -printf '%u:%g\\n' | sort | uniq -c` → `35 kesha:kesha`.

8. **История действительно содержит массовые записи памяти: 167 уникальных git-коммитов
   затрагивают `docs/workers`; авторы — DrSeedon 102 и Maxim 65.** Уверенность:
   **CONFIRMED**. Артефакт: `git log --all --format='%H\\t%an' -- docs/workers`
   с `sort -u` по hash → `unique commits 167 authors Counter({'DrSeedon': 102,
   'Maxim': 65})`.

9. **За эту историю в файлы добавлено 2668 строк и удалено 245; добавлены все 35
   текущих файлов.** Уверенность: **CONFIRMED**. Артефакт: `git log --all
   --format= --numstat -- docs/workers` → `numstat added deleted 2668 245`;
   `git log --all --diff-filter=A --format=%H -- docs/workers | wc -l` → `35`.

10. **В SQLite-срезе есть 65 сессий scope `/home/kesha/orchestra`: 41 `worker`,
    23 `full-cycle`, 1 `orchestrator`; по статусам 55 `archived`, 9 `idle`, 1
    `waiting`.** Уверенность: **CONFIRMED**. Артефакт: SQL с URI read-only
    `SELECT role,status,count(*) FROM sessions WHERE scope='/home/kesha/orchestra'
    GROUP BY role,status` → `worker archived 39`, `worker idle 2`,
    `full-cycle archived 16`, `full-cycle idle 7`, `orchestrator waiting 1`.

11. **Только 18 из 35 текущих файлов имеют одноимённую сессию в этом SQLite-срезе;
    17 файлов — кандидаты на осиротевшие/устаревшие: `audit-worktree`,
    `docs-changelog`, `feat-freshness`, `fix-bugsmd`, `fix-merge-branch-drift`,
    `fix-silent-errors`, `fix-tg-mention`, `fix-wake-after-restart`,
    `memory-research`, `merge-contours`, `migrate-vps`, `rag-max`,
    `research-compact-prompt`, `research-embeddings`, `research-memory`,
    `research-merge`, `skill-migrate-norestart`.** Уверенность: **CONFIRMED**.
    Артефакт: Python `files={p.stem for p in Path('docs/workers').glob('*.md')}`
    плюс SQL `SELECT name FROM sessions WHERE scope='/home/kesha/orchestra'` →
    `files 35 session names 65 intersection 18` и приведённый список разности.

12. **Из 18 совпавших файлов 13 принадлежат archived-сессиям и только 5 — idle-сессиям;
    running-сессий с одноимённым файлом в срезе нет.** Уверенность: **CONFIRMED**.
    Артефакт: тот же SQL по `sessions` с join по имени → archived:
    `audit-agent-slop,audit-front,codemap-ui,demo-artifact,feat-codex-gate,
    feat-codemap,feat-quota-guard,fix-reboot,perf,perf-codex-seedon,
    research-codex-html,research-opus5-migration,research-prime-agent` (13);
    idle: `back,feat-charts,feat-instant,frontend,prompt-engineer` (5).

13. **Обратная разность ещё больше: 47 из 65 имён сессий не имеют одноимённого файла в
    текущем worktree — 35 `worker`, 11 `full-cycle`, 1 `orchestrator`.** Уверенность:
    **CONFIRMED**. Артефакт: тот же Python/SQL set-difference →
    `sessions no exact file: 47` и `Counter({'worker': 35, 'full-cycle': 11,
    'orchestrator': 1})`.

14. **Телеметрия scope `/home/kesha/orchestra` фиксирует минимум 100 конкретных прямых
    мутаций файлов памяти от 22 имён агентов: 72 `Edit`, 18 `Write`, 10 `FileChange`.**
    Уверенность: **CONFIRMED**. Артефакт: read-only SQL выбирает
    `logs.type='tool'`, `content LIKE 'Write:%' OR 'Edit:%' OR 'FileChange:%'`,
    `sessions.scope='/home/kesha/orchestra'` → без фильтра конкретного пути
    `Edit 75`, `FileChange 11`, `Write 24` (110 строк); затем учитываются только
    записи, где JSON-поле `file_path`/`path` содержит конкретный
    `docs/workers/<имя>.md`. Результат → `direct concrete mutation events 100`,
    `Counter({'Edit': 72, 'Write': 18, 'FileChange': 10})`, `mutating agents 22`.

15. **Помимо API-мутаций, в телеметрии видны 26 shell-добавлений через точный шаблон
    `cat >> docs/workers/<file>.md`: back 10, frontend 11, perf 5.** Уверенность:
    **CONFIRMED**. Артефакт: read-only SQL `SELECT s.name FROM logs l JOIN sessions s
    ON s.id=l.session_id WHERE l.type='tool' AND s.scope='/home/kesha/orchestra'
    AND lower(l.content) LIKE '%cat >> docs/workers/%'` → `cat appends 26` и
    `Counter({'frontend': 11, 'back': 10, 'perf': 5})`.

16. **Итого наблюдаемый минимум — 126 событий записи от 22 агентов; лидируют back 28,
    frontend 26, feat-instant 21, feat-charts 9, perf 7, audit-front 6.** Уверенность:
    **CONFIRMED**. Артефакт: сложение результатов пунктов 14–15 и группировка по
    `sessions.name` → `direct 100 cat_append 26 combined 126`; те же SQL-строки дают
    перечисленные значения.

17. **В физически доступных соседних контурах память также лежит в репозиториях scope:
    `/home/kesha/projects/seedon/docs/workers` — 24 файла, `/home/kesha/projects/kesha-tg-bot/docs/workers` — 4; оба набора `kesha:kesha`.** Уверенность:
    **CONFIRMED**. Артефакт: `find <scope>/docs/workers -maxdepth 1 -type f
    -name '*.md'` и `-printf '%u:%g'` → `seedon 24 / kesha:kesha`,
    `kesha-tg-bot 4 / kesha:kesha`.

18. **Для scope `/home/kesha/projects/dnd-game-master` каталог `docs/workers` существует,
    но содержит 0 файлов; для `/home/kesha/projects/University` каталог отсутствует.**
    Уверенность: **CONFIRMED**. Артефакт: тот же `find` → `dnd-game-master 0`,
    `University ABSENT`.

19. **Файлов `worker.md`, `full-cycle.md`, `orchestrator.md`, `sub-orchestrator.md` в
    текущем каталоге нет, поэтому 17 mismatched-файлов не являются рольовым fallback
    для сессий с ролями из пункта 10.** Уверенность: **CONFIRMED**. Артефакт:
    `for f in docs/workers/{worker,full-cycle,orchestrator,sub-orchestrator}.md;
    do test -f "$f" ...; done` → все 4 `ABSENT`; fallback подтверждён
    `app/prompting.py:65-70`.

## Что говорит ПРОТИВ моих выводов

- **126 — нижняя граница, не полный аудит записи.** Уверенность: **CONFIRMED**.
  Артефакт: SQL с грубой выборкой даёт 280 tool-строк с упоминанием
  `docs/workers` и 66 строк с `cat >> docs/workers` по всей БД, тогда как итоговые
  100/26 получены фильтрацией scope и конкретных путей. Shell-команды через другие
  формы (`tee`, Python `write_text`, редактор без этого текстового маркера) могли не
  попасть в 126.

- **«Осиротевший» — это операционное определение по SQLite-срезу, а не доказательство
  удаления агента.** Уверенность: **CONFIRMED**. Артефакт: строки 11–13 используют
  только set-разность `docs/workers` и `sessions` на снимке; исторически файл может
  быть намеренно оставлен после архивирования или сессия могла быть удалена из
  живой БД.

- **Git-коммит не равен одной записи памяти.** Уверенность: **CONFIRMED**. Артефакт:
  `git log --all --numstat -- docs/workers` даёт 167 коммитов и 2668 добавленных
  строк, а telemetry tool-events даёт 126 событий; один вызов может менять много
  строк, а один коммит может включать несколько вызовов и файлов.

## Чего я проверить не смог

- **Не проверял содержимое и владельцев `/home/kesha/orchestra/docs/workers` главного
  checkout и других `/home/kesha/orchestra/worktrees/*`: это прямо запрещено
  периметром среза.** Уверенность: **CONFIRMED**. Артефакт-ограничение: чтение
  выполнялось только в текущем worktree и в явно разрешённых соседних
  `/home/kesha/projects/*`; для основного scope использованы только DB-поля и
  `app/prompting.py:65-70`.

- **Не смог доказать, что 17 mismatched-файлов никогда больше не читаются живым
  процессом:** SQLite-срез фиксирует сессии и логи, но не runtime filesystem access
  после точки снимка. Уверенность: **UNCERTAIN**. Артефакт: SQL с URI
  `SELECT min(ts),max(ts) FROM logs` → `2026-07-27T16:20:40.227730+00:00` —
  `2026-08-11T09:53:23.715300+00:00`; отсутствует read-only
  доступ к живому основному checkout по жёсткой границе задания.

- **Не смог отделить каждую запись, сделанную вручную до появления конкретного log-event,
  от записи агентом:** это ограничение телеметрии, а не вывод о поведении. Уверенность:
  **UNCERTAIN**. Артефакт: таблица `logs` содержит события инструментов и результаты,
  но не файловую audit-журнализацию; схема подтверждена `PRAGMA table_info(logs)`.
