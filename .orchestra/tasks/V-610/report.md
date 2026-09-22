# V-610 — замена строк стороннего авторства (Диденко В.) в `app/` и `scripts/`

## Как считалось

Идентичности автора в истории: одна — `vadimd <didenko.it.ai@gmail.com>` (20 коммитов,
23–26.05.2026; `git log --format='%an <%ae>|%cn <%ce>'` по всей истории, других имён/адресов
с `didenko`/`vadim` нет). Подсчёт — `git blame --line-porcelain` по каждому файлу из
`git ls-files app scripts`, фильтр `author-mail` по `didenko|vadim`. Скрипт:

```bash
for f in $(git ls-files app scripts); do
  n=$(git blame $BLAME_FLAGS --line-porcelain $rev -- "$f" | grep '^author-mail' | grep -c -i -E 'didenko|vadim')
  [ "$n" -gt 0 ] && echo "$f $n"
done
```

Подсчёт seedon (191) брал только `.py`; сверх него blame находил ещё 35 строк в
`app/static/js/app.js` и 14 в `app/templates/dashboard.html` (диалог удаления оркестратора).
`workspace.py` у меня 17 против 18 у seedon — другая ревизия main.

### До (main `2dcbfba9`), дословно

```
== git blame  HEAD (2dcbfba9) ==
app/backend_claude.py 7
app/db.py 44
app/manager.py 12
app/mcp_stdio.py 43
app/session.py 2
app/static/js/app.js 35
app/templates/dashboard.html 14
app/tg_bridge.py 65
app/workspace.py 17
TOTAL 239
== git blame -w HEAD (2dcbfba9) ==
app/backend_claude.py 7
app/db.py 44
app/manager.py 12
app/mcp_stdio.py 43
app/session.py 2
app/static/js/app.js 35
app/templates/dashboard.html 14
app/tg_bridge.py 65
app/workspace.py 19
TOTAL 241
== git blame -w -M -C HEAD (2dcbfba9) ==
app/backend_claude.py 7
app/db.py 44
app/manager.py 11
app/mcp_stdio.py 40
app/routes/sessions.py 1
app/routes/system.py 21
app/schema.sql 5
app/session.py 2
app/session_turns.py 1
app/static/js/app.js 28
app/templates/dashboard.html 13
app/tg_bridge.py 66
app/workspace.py 23
TOTAL 262
```

Построчный список «до» — `blame_before_lines.txt` рядом.

### После (ветка V-610), дословно

```
== git blame  (рабочее дерево V-610) ==
TOTAL 0
== git blame -w (рабочее дерево V-610) ==
app/workspace.py 9
TOTAL 9
== git blame -M (рабочее дерево V-610) ==
app/db.py 3
app/manager.py 2
app/mcp_stdio.py 11
app/session.py 2
app/tg_bridge.py 7
app/workspace.py 22
TOTAL 47
== git blame -w -M -C (рабочее дерево V-610) ==
app/db.py 3
app/manager.py 2
app/mcp_stdio.py 11
app/routes/sessions.py 1
app/routes/system.py 10
app/schema.sql 5
app/session.py 2
app/session_turns.py 1
app/tg_bridge.py 11
app/workspace.py 15
TOTAL 61
```

Приёмка задачи (обычный `git blame`) — **0**. Числа с `-w`/`-M`/`-C` разобраны ниже в разделе
«Что осталось»: там нет исходной логики этой задачи, но есть имена контрактов, строки-разделители
и несколько старых строк, которые Максим позже переотступил.

## Фрагменты

| Где | Было (его) | Стало |
|---|---|---|
| `db.py` путь к БД (19 строк) | `_resolve_db_path`: `os.getenv`, ветвление по абсолютному/относительному пути | `_db_path_from_env`: `_REPO_ROOT / configured` (pathlib сам оставляет абсолютный путь как есть), `from os import environ`; вызов в `main.py` переименован |
| `db.py` тест-лок (25) | читать → вставить/обновить | вставка первой `INSERT … ON CONFLICT(scope) DO NOTHING`; при конфликте — чтение и сверка держателя. Гонка двух захватов больше не может упасть на PRIMARY KEY между чтением и вставкой. `release` возвращает флаг «лок мой» вместо `rowcount`. Блок перенесён в конец файла |
| `mcp_stdio.py` три MCP-тула лока (41) | `result.get("error")` + три ветки текста | ветка `error` удалена как мёртвая: `_api` (`mcp_stdio.py`, конец `_api`) сам поднимает `ApiToolError` на любой ответ с `error`; описания тулов и ответы написаны заново; блок перенесён к `worker_wip`/`report_bug` |
| `mcp_stdio.py` `spawn_worker` (2) | параметр `description`, ключ `base_branch` | параметр стоит рядом с `model`, `base_branch` — в одной строке с остальными ключами worktree. Строки-объявления, другой формы у них нет |
| `routes/system.py` ручки `/api/test-lock*` (найдены только `-C`, 21) | ленивый импорт в каждой ручке, два `return` | импорт вынесен на уровень модуля, статус собирается одним выражением; форма ответов прежняя |
| `backend_claude.py` (7) | `_disallowed_tools` с `list.extend`, вызов при каждом построении | новая функция; список считается один раз в `__init__` (`self._cli_disallowed_tools`) и одинаков для клиента и для сверки handoff; константа — кортеж |
| `manager.py` `remove_scope` (11) | два цикла с проверкой `not in list` | `dict.fromkeys` по живым и сохранённым оркестраторам; метод перенесён к `remove()` |
| `manager.py` `remove()` (1) | `if session.loaded:` после гидрации | проверка `session is not None and session.loaded` до гидрации: у гидрированной сессии процесса нет. Порядок действий не изменился |
| `session.py` (2) | поля `_turn_gen`, `_auto_report_task` | `_turn_gen` стоит рядом с парным `_turn_start_cancel_gen` с комментарием, зачем их два, `_auto_report_task` — рядом с `_persist_task`. Поля перегруппированы, объявления прежние |
| `tg_bridge.py` `_pick_unique_topic_name` (22) | цикл `while` с счётчиком | `itertools.chain` + `itertools.count`, первый свободный кандидат через `next`; перенесено к коду создания топиков |
| `tg_bridge.py` `remove_topics_for_orchs` (41) | три списка, ранний `continue` | один `outcome`, `try/except/else`; семантика (что снимается из config при ошибке API, что при отсутствии топика) проверена тестами `TestRemoveTopicsForOrchs` |
| `tg_bridge.py:3028` (1) | инлайн-выражение имени топика | `_topic_title()` |
| `tg_bridge.py` `TG_USER_MENTION` (2) | константа окружения | та же строка, перенесена к `_mention_markup`, который её рендерит. Имя переменной — контракт конфигурации |
| `workspace.py` (17) | ручные `symbolic-ref` / `checkout` / восстановление в `finally`, `check-ref-format` | `_checked_out_branch`, `_checkout`, `_branch_name_error` (последний заменил 4 одинаковых вызова, 3 из них Максима); `finally` через `_checkout`; ветка worker'а — сначала успешный путь; два `else:` заменены проверками `if result is None:`, как во всей этой функции; поведение то же |
| `workspace.py:856` пустая строка | разделитель между `_branch_worktree_path` и `_clean_worktree_error` | `_branch_worktree_path` (код Максима) перенесён к `_inspect_branch_ref`. **Единственный перенос без правки смысла**: пустая строка между двумя неизменными функциями иначе blame не переназначить |
| `app.js` + `dashboard.html` (49) | статичная модалка в шаблоне + её открытие/закрытие + запасной `confirm()` | `confirmOrchestratorDelete`: диалог собирается в JS на один ответ и удаляется целиком, один обработчик кликов по `data-act`, `URLSearchParams`; модалка из шаблона и мёртвый запасной путь удалены; осиротевший ключ `'and all its workers?'` из `i18n.js` удалён |

## Проверка

- Интерпретатор `/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest`,
  импортирован `app` этого worktree. Каждый файл отдельно: test_db 84, test_production_db_isolation 2,
  test_mcp_stdio 125, test_disallowed_tools 2, test_manager 174, test_tg_bridge 193, test_workspace 118,
  test_audit0901_workspace 5, test_merge_branch_drift 7, test_merge_conflict_report_423 3,
  test_merge_foreign_task_ref 3, test_merge_operations 40, test_merge_ref_gate 5,
  test_merge_recovery_wedge 3, test_merge_target_oracle_386 31, test_return_to_merged_branch 6,
  test_merge_stuck 2, test_session 245, test_api 127, test_reducer_role 3, test_static_js_globals 1,
  test_compact_pending_ack_467 1, test_disconnect_dead_process 2, test_routes_surface 2 — все passed.
- Те же 23 файла одной командой повисли на ~85% и были убиты через 50 минут (bg job). Виновная
  пара не найдена; на main этот совместный прогон не повторял, связь с V-610 не доказана и не
  исключена → TODO.md.
- `test_tailwind_css::test_committed_css_matches_current_sources` красный, но не из-за V-610:
  пересборка добавляет `.text-red-300`, `.bg-slate-800/70`, `hover:bg-slate-600`,
  `hover:text-red-200` и убирает `.!grid`, `.text-amber-100` — ни одного из этих классов в
  моём diff нет. Классы диалога совпадают с удалённой модалкой. CSS не пересобирал → TODO.md.
- Диалог удаления проверен в headless Chromium на стенде с заглушками `api/T/escHtml`:
  галочка каждый раз снята; «Удалить» с галочкой → `DELETE /api/orchestrators/pm-x-orchestrator?scope=%2Fsrv%2Fmy+proj&delete_tg_topics=true`
  и перезагрузка списка; ✕, «Отмена» и клик по фону закрывают без запроса; клик внутри окна
  его не закрывает. `node --check app/static/js/app.js` — OK.
- Новых тестов не добавлял. Вставку-первой в тест-локе покрывают существующие `TestTestLock`
  (захват, отказ, повторный захват, снятие, переименование); отдельного теста на гонку нет.

## Что осталось и почему

- **`-w` (9, все `workspace.py`)**: строки, которые Максим позже переотступил, а `-w` возвращает
  их коммитам Диденко: `create_worktree` 588–594 (повторное использование существующей ветки),
  текст ошибки `target branch '…' does not exist` (1432), `["git", "merge", from_ref, "--no-edit"]`
  в `switch_worktree_branch` (2644) и `else:`/`)` без содержания.
- **`-M`/`-C`** дополнительно находят: имена и сигнатуры MCP-тулов лока (контракт с агентами),
  `TG_USER_MENTION` (контракт конфигурации), объявления полей сессии, сигнатуры
  `_pick_unique_topic_name`/`remove_topics_for_orchs` (их вызывают тесты и проводка менеджера),
  `TestLockRequest` и параметр `delete_tg_topics` ручки удаления (HTTP-контракт), колонки
  `test_lock` в `app/schema.sql` (схема данных), а также строки-разделители и типовые
  `cwd=str(repo), capture_output=True, text=True,`, которые `-M` приписывает ему по совпадению текста.
- Перенесено без смысловой правки (честный список): поля `session.py`, `TG_USER_MENTION`,
  `_branch_worktree_path`, порядок параметра `description`. Остальные переносы шли вместе
  с переписанным кодом.
- Тесты его авторства в `tests/` (например, шапка `tests/test_tg_bridge.py`) задача не
  затрагивала: область — `app/` и `scripts/`.
- Рестарт нужен: изменён Python (`db`, `mcp_stdio`, `backend_claude`, `manager`, `session`,
  `tg_bridge`, `workspace`, `routes/system`, `main`); JS/HTML подхватятся без рестарта.
  Новый текст MCP-тулов лока агенты увидят после перезапуска их MCP-подпроцессов.
