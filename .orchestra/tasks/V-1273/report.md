# sanitized-publication-copy
# Private originals: private/tasks/V-1273/originals/ (root-held SHA-256/bytes manifest; not accessed here).

# V-1273 — удаление нового файла после отказа scanner

Минимальная правка подготовлена для импорта платформой в `task-V-1273/fix-hub-untracked-delete`. Production diff: **18 добавленных строк**, только `app/hub_workspace.py:commit_sync`. CHANGELOG обновлён вручную; существующие/замороженные тесты не менялись. Worker не коммитит результат сам.

## Причина и цепочка

`backend_hub._provision` → `hub_workspace.local_delta(..., keep=state.hub_made)` сохраняет baseline импортированных Hub-файлов вне upload ownership. `_sync_back` сохраняет snapshot/journal; `_finish_sync` вызывает `apply_changes`, восстанавливает changed/deleted при replay, `_record_sync` сохраняет manifest/provenance, затем вызывается `commit_sync`.

После первого отказа scanner новые импортированные файлы остаются staged. Второй импорт удаляет один из них. `git add -A` успешно удаляет staged addition из индекса, но прежний `commit_sync` передаёт исходный список в `git commit --only`. Теперь путь неизвестен Git, и commit остальных изменений целиком падает. В точном synthetic sequence ошибка возникает **в commit --only после staging**, а не в add:

```text
[hub sync] changed 2, deleted 2
NOT COMMITTED (git commit failed: error: pathspec 'duplicate.txt' did not match any file(s) known to git)
```

Отдельно покрыт add-refusal для уже отсутствующего untracked deletion. Реальные журналы/импорты не читались и не воспроизводились.

После staging/fallback правка проверяет отсутствующие deleted-пути через индекс и cached diff (`--no-renames`). Путь исключается из commit candidates и staging-refusal diagnostics, только если отсутствует на диске, в индексе и cached diff. Настоящий HEAD deletion остаётся в diff и коммитится, включая уже staged deletion и delete/add pair. Ошибки Git inspection вызывают явный отказ; missing changed и существующие ignored outputs остаются видимыми отказами. Reset/stash, широкого staging, обхода scanner и изменений import/privacy/ownership/recovery/data-loss guard нет.

## Регрессия

Новый `tests/test_hub_untracked_delete_v1273.py` содержит **9 проверок**:

- absent deletion: исходно untracked либо staged addition; отдельно либо вместе с changed output;
- смешанные tracked/staged deletions, vanished addition, отсутствующий deleted, changed output, ignored/missing changed; точное сохранение посторонних index/unstaged patches, untracked/ignored contents;
- явный отказ при ошибке каждого из двух Git inspection;
- интеграция двух настоящих backend turns с synthetic transport/provider, реальными tar import/state/local_delta/commit и production pre-commit/scanner: первый turn отказывает из-за отсутствующего scanner, второй удаляет дубликат и tracked source, сохраняет survivor/source. Проверяются один итоговый commit, tree, чистый worktree, manifest/provenance/journal.

История доступна через CHANGELOG V-1008 (sparse fallback), V-1062 (input provenance), V-1213 (durable import/commit/report) и текущие тесты `test_hub_workspace.py`, `test_hub_report_order_v1213.py`. Git log/blame недоступны: в предоставленной копии нет `.git`.

## Фактические проверки

Все прогоны — provisioned **uv 0.11.28**, `uv run --frozen`, default `.venv`, `nice -n 10`, `oom_score_adj=1000`. В каждой test shell:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1273/tmp"
export PYTHONDONTWRITEBYTECODE=1
```

uv установил 76 locked packages. Подмены интерпретатора/лока нет. Transport/provider, DB/catalog/publication rules и CLI homes изолированы тестами. Перед ограниченными группами: cgroup 36,224,061,440 / 52,755,525,632 байт, available хаба 77 GiB, CPU limit 8. Не больше двух групп по 2 xdist workers, лимит каждой 480s; браузеров нет.

| Прогон | Результат и raw output |
|---|---|
| Первый test-first запуск | 7 failed, 30.07s; один — моя опечатка теста `backend.paths`, исправленная до корректного RED. `red-initial-test-typo.txt` |
| Корректный RED, production ещё без правки | **7 failed, 26.81s**, точный второй импорт NOT COMMITTED/pathspec. `red.txt` |
| Правка + исходные 7 регрессий | **7 passed, 30.10s**. `green-focused.txt` |
| Ограниченная core-группа: новые 9, прежние commit/WIP/deletion/conflict/truncation, V-1213 report recovery, V-1062/V-1063 inputs | **105 passed, 264.30s**, exit 0, без skips. `green-core.txt`; точная команда `core-command.txt` |
| Privacy + scanner, `-q -ra -n 2` | **99 passed, 5 failed, 70.92s**: все 65 privacy зелёные; scanner 34 passed/5 ограничений копии, перечислены ниже. `guards.txt` |
| Мутация: старый commit_sync в памяти, тот же integration test | **Ожидаемый RED: 1 failed, 36.58s**, exit 1, тот же второй импорт/pathspec. `mutation.txt` |
| Отдельный старый prompt test | 1 failed/16.88s с правкой; **тот же отказ до правки**, 1 failed/22.54s. `prompt-control.txt`, `prompt-baseline.txt` |
| Исходный расширенный набор 9 модулей | **НЕ ЗАВЕРШЁН**, exit 143 без summary; наблюдался prompt failure. Зелёным не считается. `green-suite.txt`; collection: 400 cases, `collected.txt` |
| Diff / compile / scan форм секретов | `source-review.txt`, финальный `final-review.txt` |

Команды: `uv run --frozen python -m pytest <перечисленные source/test paths> -q -ra -n 2`; core включает новый файл целиком, 7 прежних commit/conflict/truncation test functions (с параметрами), целиком `test_hub_report_order_v1213.py`, `test_hub_inputs_v1062.py`, `test_hub_inputs_v1063.py`. Guards: целиком `test_hub_file_policy_v1073.py`, `test_secret_commit_gate.py`. Для воспроизведения мутации: `uv run --frozen python .orchestra/tasks/V-1273/mutate.py`; frozen исходная функция — `commit_sync_before.txt`, рабочий исходник не переписывается.

Импортированный `app`: оригинальный замер был абсолютным; здесь корень заменён относительным workspace-плейсхолдером:
`<workspace>/app/__init__.py`

Модуль: тот же корень + `/app/hub_workspace.py`; raw `import-path.txt`.

## Красные, пропущенные и границы

- **5 guard failures из-за состава копии**, без изменений frozen tests: отсутствуют 315 fixture `.orchestra/tasks/315/acceptance/fixtures/t5_recovery_records.json`, `CLAUDE.md`, `.orchestra/kb/runtimes.md` (3 existence controls); mention-through-hook повторно требует отсутствующий 315 fixture; repo-level check-ignore требует отсутствующий `.git` (exit 128). Ни один из этих тестов не вызывает изменённый commit_sync.
- **Prompt failure до/после**: отсутствует `.orchestra/pipelines/default/prompts/hub/worker.md`, `hub_preamble` берёт fallback без ожидаемой идентичности. Соседний код не менялся.
- Исходный широкий прогон завершился с 143, причину сигнала инструмент не раскрыл; worker его не останавливал. Его незавершённые проверки не засчитываются. Результат оценён по завершённым ограниченным группам.
- Полный repository suite и instruction/history/git-status проверки неполной копии не запускались. Пропуски pytest у завершённых групп указаны в их summary; никаких ослаблений/выдуманных fixtures.
- Реальные импорты/replay/archive, рестарт, очереди/сессии Hub, другие scope/worktree, credentials, paid calls, push/deploy/merge и model review не выполнялись. Все Git commits — только внутри synthetic test fixtures. Временные test repos удалены после проверок.
- Root принимает diff/тесты/мутацию, делает merge/push и проверяет обычную активацию; это не заявление об исправленном живом процессе. Платформа коммитит возвращённые файлы после окончания worker.
