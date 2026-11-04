> **sanitized-publication-copy** — identifying Hub account/host/workspace paths are replaced with neutral placeholders. Raw originals and their SHA/byte manifest were preserved by root at `private/tasks/V-1277/originals/manifest` (root-private; not read here). Test results, exit codes and measured lengths below describe the original runs; path replacement does not recalculate those measurements.

# V-1277 — частичное исправление; CSS и приёмка заблокированы неполной source copy

Заданный источник: main `5660f3c64e2b92f12cce15b6c78da03382535b72`, GitHub run
`41788061708`. В broker-copy нет `.git`; независимо подтвердить revision нельзя.
Проверенная рабочая папка:
`<WORKSPACE>`.

## Что изменено

Только два source-файла: `prompts/modules/model-routing.md` и
`prompts/roles/orchestrator.md` внутри `.orchestra/pipelines/default/`.
Дубли versioned ID в прозе заменены названиями семейств Native Luna / Astra,
Hub Sol / Terra; сохранён существующий alias `hubsol`. Точные versioned ID
предписано разрешать через live manifest/catalog. Это названия в тексте, не новые
registry aliases. Сохранены native Sol/Terra equivalence, все задачи и границы
таблицы, Astra manual-only, Luna protected-local-only с model_reason, отсутствие
Hub Terra в registry, specialist/non-spawning Argon и запрет fallback при нехватке
Hub Sol. Названия/допуск runtime-маршрутов, роли, effort и manifest не менялись.

Checker, guards и tests не изменены. Новых тестов/фикстур и changelog нет.
Compiled CSS в результате **не изменён**: оригинал восстановлен побайтно после
диагностической сборки. Полный diff: `prompts.diff`.

## Обнаруженный блокер

Первый штатный запуск exact двух тестов завершился **2 setup errors**, не дошёл
до assertion: `tests/conftest.py:665` импортирует отсутствующий
`app.routes.sessions`. В этой копии `app/` содержит только 26 static-файлов;
нет `app/templates/`, `app/models.py`, `app/pipeline.py`, `app/prompting.py`,
`app/kb_index.py`, `app/__init__.py`. Поэтому контракт delivery/role isolation
и runtime models/admission здесь проверить невозможно.

`app.__file__ = None`: импортирован только namespace package с `app.__path__ =`
`['<WORKSPACE>/app']`.
Полноценный application package из этой копии не импортирован.

Отдельная диагностика неизменённых тестов с `--noconftest` до правок дала
**2 failed**: literal-ID manifest assertion и CSS mismatch. Это не штатная
приёмка: общие фикстуры отсутствующего приложения отключены только параметром
диагностической команды, их код не изменён. Manifest failure воспроизведён;
CSS mismatch на неполных источниках не доказывает тождественность причины
исходному CI на полном main.

`bash scripts/build-tailwind.sh` успешно исполнен офлайн с cached
`tailwindcss@3.4.17`: кандидат **17 947 байт**, исходный CSS **20 940 байт**.
Но `tailwind.config.js` требует `./app/templates/**/*.html`, которых не прислали.
Импортировать такой кандидат небезопасно: отсутствуют template-only utilities.
Кандидат сохранён только как `tailwind.incomplete-candidate.css`; оригинал
`tailwind.before.css` возвращён в `app/static/css/vendor/tailwind.css`.
Предупреждение outdated caniuse-lite сохранено в build log; обновление зависимостей
не выполнялось.

## Команды и фактический результат

В каждом Python test shell использован provisioned **uv 0.11.28**, default `.venv`:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:/usr/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1277/tmp"
export PYTHON_DOTENV_DISABLED=1
export npm_config_offline=true
export npm_config_cache="$PWD/.orchestra/tasks/V-1277/npm-cache"
echo 1000 > /proc/self/oom_score_adj
```

Локальные `/usr/bin/node`, `/usr/bin/npx` выбраны перед remote-dispatcher shims.
Существующие npm `_npx`/`_cacache` скопированы read-only из HOME в task-local cache;
npm запускался с offline=true. `uv run --frozen` создал `.venv` и установил
76 locked packages. Другого интерпретатора/lockfile/фикстур вместо требуемых нет.
Тесты последовательные, nice=10; до запуска проверены RAM/cgroup: available
76 GiB на хабе, cgroup 35 946 700 800 / 52 755 525 632 байт, quota 8 CPU.

Все ниже относительны к проверенной рабочей папке; каждый test/build запуск —
с указанным окружением и префиксом `nice -n 10`. `<log>.exit` содержит exit code.

| Команда | Exit | Фактический результат / log |
|---|---:|---|
| `uv --version` | 0 | uv 0.11.28; `runner.log` |
| `uv run --frozen python -m pytest tests/test_check_pipeline_manifest.py::test_check_passes_on_current_default tests/test_tailwind_css.py::test_committed_css_matches_current_sources -q` | 1 | 2 setup errors: app.routes отсутствует; `reproduce.log` |
| `uv run --frozen python -m pytest --noconftest tests/test_check_pipeline_manifest.py::test_check_passes_on_current_default tests/test_tailwind_css.py::test_committed_css_matches_current_sources -q` | 1 | До правок: 2 failed; `diagnostic-before.log` |
| `bash scripts/build-tailwind.sh` | 0 | Offline build; неполный кандидат отклонён, оригинал восстановлен; `build-tailwind.log` |
| `uv run --frozen python -m pytest --noconftest tests/test_check_pipeline_manifest.py tests/test_tailwind_css.py -q` | 1 | После правок: 11 passed, 2 failed, 0 skipped; `diagnostic-after.log` |
| `uv run --frozen python scripts/check_pipeline_manifest.py --check` | 0 | OK; `check-manifest.log` |
| `uv run --frozen python scripts/check_instruction_contract.py` | 1 | app.kb_index отсутствует; `check-instructions.log` |
| `uv run --frozen python -m pytest tests/test_default_pipeline.py tests/test_prompting.py tests/test_local_delegation_prompts.py -q` | 2 | 2 collection errors из-за отсутствия app.pipeline; `required-prompts.log` |
| `uv run --frozen python -m pytest --noconftest tests/test_check_pipeline_manifest.py -q` | 0 | 10 passed, 0 skipped; включает negative controls checker; `manifest-diagnostic-after.log` |
| `uv run --frozen python -` (stdin: hashlib/difflib review) | 0 | Проверка restored CSS, source hashes, diff и namespace import; `source-review.log` |

Два оставшихся диагностических CSS failure: отсутствующий
`app/templates/dashboard.html` в `test_play_cdn_compiler_is_gone` и прежний
`test_committed_css_matches_current_sources`. Полный runner не запускался:
отсутствует application source; штатные exact и prompt checks уже заблокированы.
Ни один skip не выдан за pass. Tests не читали `.env` или live DB; реальные
provider CLI, сеть тестов, external SSH, сервисы, restart и чужие задачи не тронуты.

## Хэши, границы и продолжение

`before.sha256` и `after.sha256` фиксируют SHA-256 двух prompts, manifest,
checker, build script, двух acceptance test-файлов, CSS, Tailwind config/input,
pyproject и uv.lock. `source-review.log` подтверждает, что изменились только
два prompts; остальные перечисленные файлы совпадают с исходными.
`static-source-inventory.sha256` перечисляет все фактически supplied static-файлы.
Снимки исходных prompts и CSS сохранены рядом. Временные pytest-копии и npm-cache
после проверок удалены из task notes; dependency environment не является патчем.

**CI не закрыт, merge-ready не заявляется.** Root может принять отдельно wording
patch, но для завершения V-1277 нужен полный source checkout того же HEAD с
`app/**/*.py` и `app/templates/**/*.html` (и всеми прочими content sources).
В нём: применить эти два prompts, выполнить штатный offline build-tailwind.sh,
проверить diff CSS, затем штатные два exact tests, оба полных test-файла,
prompt-delivery checks и check_instruction_contract.py. Пересборку по неполной
копии, подмену fixture или ослабление checker не использовать.
