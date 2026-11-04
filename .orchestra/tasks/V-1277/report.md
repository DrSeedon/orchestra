> **sanitized-publication-copy** — identifying Hub account/host/workspace paths are replaced with neutral placeholders. Raw originals and their SHA/byte manifest were preserved by root at `private/tasks/V-1277/originals/manifest` (root-private; not read here). Test results, exit codes and measured lengths below describe the original runs; path replacement does not recalculate those measurements.

# V-1277 — оба исходных CI failure исправлены; финальная host-приёмка за root

Источник по заданию: main `5660f3c64e2b92f12cce15b6c78da03382535b72`,
GitHub run `41788061708`. `.git` в broker-copy отсутствует, поэтому revision
независимо не подтверждён и GitHub CI здесь не проверялся.

## Итоговый патч

Только три source-файла:

- `.orchestra/pipelines/default/prompts/modules/model-routing.md`;
- `.orchestra/pipelines/default/prompts/roles/orchestrator.md`;
- `app/static/css/vendor/tailwind.css`.

Обе прежние prompt edits сохранены без изменений после refresh. Дубли
versioned IDs заменены названиями семейств с указанием брать точные IDs из
live manifest/catalog; существующий alias `hubsol` сохранён. Не менялись задачи,
допуск или реальные названия registry-маршрутов: Native Sol/Terra equivalent,
Astra manual-only, Luna protected-local-only с model_reason, обычные Hub workers
на Sol, Hub Terra отсутствует, Argon specialist/non-spawning, fallback запрещён.
Registry/admission сверены с предоставленным `app/models.py`, он не изменён.
Manifest остаётся владельцем defaults/effort. Diff prompts: `prompts.diff`.

CSS пересобран **штатным** `bash scripts/build-tailwind.sh` после расширения
bundle до public tracked app/. Все 3 HTML и 14 JS inputs присутствуют и
не изменились между сборкой и проверками. Offline Tailwind 3.4.17 добавил ровно
два правила: `.border-emerald-700` и `.border-red-700`, используемые
`app/static/js/app.js:5174`. Удалённых или изменённых правил нет.
Размер: **20 940 → 21 129 байт** (+189). PostCSS-сверка: `refresh/css-diff.log`.
Неполный кандидат первого этапа **не перенесён** в source CSS.

Checker, frozen tests, guards, manifest, Tailwind config/input, build script,
pyproject и uv.lock не изменены. Новые тесты/фикстуры/changelog не добавлены.

## Проверки после refresh

Рабочая папка:
`<WORKSPACE>`.
Реально импортирован:
`<WORKSPACE>/app/__init__.py`.

Все Python-запуски — provisioned **uv 0.11.28**, locked default `.venv`.
В каждом test shell:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:/usr/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1277/refresh/tmp"
export PYTHON_DOTENV_DISABLED=1
export npm_config_offline=true
export npm_config_cache="$PWD/.orchestra/tasks/V-1277/refresh/npm-cache"
echo 1000 > /proc/self/oom_score_adj
```

`/usr/bin` выбирает реальные local node/npx/git перед remote-dispatcher shims.
Имеющиеся npm caches прочитаны из HOME в task-local cache; npm строго offline.
Все test/build команды ниже выполнялись последовательно с `nice -n 10`.
Ни `--noconftest`, ни подмена фикстур после refresh не использовались.

Обозначение `TARGETS` в таблице означает дословно:

```text
tests/test_check_pipeline_manifest.py tests/test_tailwind_css.py tests/test_default_pipeline.py tests/test_prompting.py tests/test_local_delegation_prompts.py tests/test_instruction_contract.py
```

| Команда | Exit | Результат / log внутри refresh/ |
|---|---:|---|
| `uv run --frozen python -m pytest tests/test_check_pipeline_manifest.py::test_check_passes_on_current_default tests/test_tailwind_css.py::test_committed_css_matches_current_sources -q` ДО build | 1 | 1 passed, 1 failed: реальный CSS mismatch; `exact-before.log` |
| `bash scripts/build-tailwind.sh` | 0 | Offline build из refreshed inputs; `build-tailwind.log` |
| Та же exact2 команда ПОСЛЕ build | 0 | **2 passed**; `exact-after.log` |
| `uv run --frozen python scripts/check_pipeline_manifest.py --check` | 0 | OK; `manifest.log` |
| `uv run --frozen python scripts/check_instruction_contract.py` | 1 | Нет CLAUDE.md symlink; `instructions.log` |
| `uv run --frozen python -m pytest TARGETS -q` | 1 | 157 passed, 1 failed: warning length 665 >=600 на длинном tmp path; `targeted.log` |
| `uv run --frozen python -m pytest TARGETS --basetemp="$PWD/.orchestra/tasks/V-1277/refresh/pt" -q` | 0 | **158 passed**, 0 skipped; `targeted-basetemp.log` |
| `/usr/bin/node -` (stdin: cached PostCSS AST comparison) | 0 | 2 rules added, 0 removed/changed; `css-diff.log` |
| `uv run --frozen python -` (stdin: hashlib source review) | 0 | Единственное app-изменение — CSS; `final-source-review.log` |

Численные exits сохранены в одноимённых `.exit`. Source review перед работой
также exit 0: `source-review-before.log` / `.exit`.

## Все оставшиеся red, ограничения и непройденные проверки

1. **Instruction CLI остаётся красным**: в Hub-copy нет `CLAUDE.md` symlink;
   `.git` тоже отсутствует. Согласно указанию root metadata не создавалась.
   Root должен проверить instruction CLI, symlink, exact HEAD/diff на полном host.
   Из-за раннего отказа symlink-check остальная root documentation validation
   этой CLI здесь не выполнена; 9 synthetic instruction-contract tests входят
   в прошедшие 158 и не заменяют root-проверку.
2. **Сохранён исходный red общего targeted run**: один неизменённый тест
   `TestCodexProjectDocPreflight::test_multibyte_overflow_reports_first_incomplete_line_and_bounded_fallback`
   требует instruction length <600, а длинный default pytest tmp path Hub-copy
   даёт 665. `app/prompting.py:598` включает абсолютный путь дважды.
   Повтор с явным task-local `--basetemp` убирает лишнюю вложенность
   pytest-of-user/pytest-N и проходит без изменения теста/лимита/фикстуры.
   Ограничение предупреждения на длинных путях **не исправлено** в этом scope;
   обычный прогон с исходным TMPDIR не объявляется зелёным.
3. Первый этап до refresh: штатный exact2 дал 2 setup errors (нет app.routes),
   prompt checks — collection errors (нет app.pipeline), instruction CLI —
   import error (нет app.kb_index). `--noconftest` использовался только как
   обозначенная диагностика: до edits 2 failed; после 11 passed/2 CSS failed
   (нет dashboard.html и CSS mismatch); manifest-only 10 passed. Все эти red
   и exact команды сохранены в `report.initial.md` и исходных logs.
   Кандидат 17 947 байт от неполной source copy отклонён и оставлен только
   evidence-файлом `tailwind.incomplete-candidate.css`. После refresh app-import
   и template blockers устранены; старые диагностические результаты не
   подменяют новые штатные проверки.
4. Build выдал warning outdated caniuse-lite; dependency update не выполнялся.
   Полный runner не запускался: scope — указанные CI cases и targeted contracts.
   External CI, merge, live activation не выполнялись. Не было skips.

Никаких `.env` или live DB не читалось: checkout `.env` отсутствует, штатные
conftest sandbox/guards включены, временные БД/каталоги внутри task TMPDIR.
Реальные providers, external SSH, remote projects, restart, платные вызовы
и изменения app-систем коллег V-1274/V-1275 не затронуты. Перед тестами проверены
ресурсы: хаб available 76 GiB, cgroup 38 572 691 456 / 52 755 525 632 байт,
quota 8 CPU. Тесты последовательные; браузер/сервисы не запускались.

## Evidence и дальнейшее принятие

- `before.sha256`, `after.sha256`: исходный этап и обе сохранённые prompt edits.
- `refresh/app-before.sha256`, `refresh/app-after.sha256`: все **176** supplied
  app-файлов; изменён только CSS, остальные 175 идентичны.
- `refresh/tailwind-inputs.sha256`: 17 неизменённых HTML/JS inputs.
- `refresh/final.sha256`: финальные prompts/CSS и неизменённые guard/test/config/lock.
- Финальный CSS SHA-256:
  `b212419b713867a62efd0daab4c356f11198b54d1a445b71f8b47e534b67ef5f`.

Финальная проверка canonical `scripts/secret_scan.py::scan_text` через
`uv run --frozen python -`: exit 0, 58 source/evidence-файлов, 0 находок.
Live forbidden-string lists/credentials не загружались; `refresh/secret-scan.log`.

Task-local npm cache, pytest sandboxes и basetemp очищены после проверок;
dependency .venv не является патчем. Source edits готовы к root-приёмке:
проверить исходный HEAD, штатный instruction contract и необходимые host checks,
затем решать merge/archive. Здесь commit/push/merge не выполнялись.
