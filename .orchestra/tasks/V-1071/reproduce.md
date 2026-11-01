# Воспроизведение, ограничения и фактический запуск

Все команды выполняются из корня provisioned copy. Python — provisioned **uv 0.11.28**, lock не менялся, `.venv` стандартная. При первом `uv run --frozen` создана `.venv`, установлено 76 locked packages. Другой интерпретатор вместо требуемого runner не использовался. У kit нет собственного lock/pyproject: офлайн-механизмы работают на stdlib; PyYAML для внешнего validator уже есть в lock Orchestra. `anthropic` для live-прогона kit не устанавливали.

```bash
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export PYTHONDONTWRITEBYTECODE=1 UV_OFFLINE=1 KIT_MODEL=fake
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export PYTHONPATH="$PWD/.orchestra/tasks/V-1071/exemplar/network_guard"
export TMPDIR="$PWD/.orchestra/tasks/V-1071/evidence/temporary"
mkdir -p "$TMPDIR"
ulimit -v 2097152
nice -n 15 uv run --frozen python -m pytest \
  .orchestra/tasks/V-1071/upstream/kit/tests/test_kit.py -q \
  --basetemp .orchestra/tasks/V-1071/evidence/temporary/pytest
nice -n 15 uv run --frozen python .orchestra/tasks/V-1071/exemplar/run_offline.py
uv run --frozen python .orchestra/tasks/V-1071/exemplar/edge_cases.py
uv run --frozen python .orchestra/tasks/V-1071/exemplar/analyze_recorded.py
uv run --frozen python \
  .orchestra/tasks/V-1071/upstream/skills/skills/skill-creator/scripts/quick_validate.py \
  .orchestra/tasks/V-1071/upstream/kit/skill
```

`run_offline.py` пишет отдельный stdout для каждой команды и `commands.json` с argv/exit code. Долгих polling/sleep-циклов нет. Python subprocesses получают `sitecustomize`, который запрещает socket connect/DNS; отдельная отрицательная проба подтверждает отказ. Это защита воспроизводимого offline replay, не заявленная ОС-песочница для произвольных программ. `NoModel` в ручном sample бросает исключение при любом обращении к модели. В kit smoke используется `KIT_MODEL=fake`.

| Проверка, реально выполненная 24.10 | Фактический результат | Артефакт |
| --- | --- | --- |
| Required uv + pytest upstream kit | **48 passed in 2.90s**, exit 0 | `evidence/kit-tests.stdout` |
| Запрет сети Python | RuntimeError при connect, ожидаемый exit 1 | `evidence/network-guard.stdout` |
| Ручной вызов реальных tools | 10 cases, assertions прошли, 0 model calls | `evidence/manual-sample.stdout` |
| Original demo fake | 19 tasks ran, 0 harness errors, exit 0 | `evidence/smoke-original.stdout`, `smoke-results/original/` |
| Single-loop demo fake | 19 tasks ran, 0 harness errors, exit 0 | `evidence/smoke-single.stdout`, `smoke-results/single/` |
| coupling_map на shipped synthetic traces | 200 traces; 96 orders→shipping, coupling 100% | `evidence/coupling-demo.stdout` |
| chain_coverage на старом real baseline | Пропуск account→returns, **ожидаемый exit 1** | `evidence/coverage-recorded-12.stdout` |
| chain_coverage на 19 fake tasks | Все перечисленные sets покрыты, exit 0; это не доказательство семантики handoff | `evidence/coverage-smoke-19.stdout` |
| compare на опубликованных real logs | Fold, as-tool и дополнительный rerun пересчитаны без модели | `evidence/recorded-*.stdout` |
| estimate на real baseline/probe | Полный и частичный estimate, без пересчёта в деньги | `evidence/estimate-full.stdout`, `estimate-probe.stdout` |
| Три adversarial synthetic cases | Все assertions прошли | `evidence/edge-cases.stdout` |
| Внешний skill-creator validator | `Skill is valid!`, exit 0 | `evidence/skill-validator.stdout` |
| Внешний lite report builder, Node v22.23.3 | 2 variants/12 cases, HTML + scores.tsv | `evidence/report-lite.stdout`, `lite-report-flow/` |
| Внешний runner scaffold | `--help` и `node --check`, exit 0; приложение/грейдер не реализованы и не запускались | `evidence/scaffold-help.stdout`, `scaffold-syntax.stdout` |
| Финальная проверка артефактов | 215/215 kit hashes, 61/61 source hashes; AST/local links OK; 449 text files без credential-shape/local-workspace findings | `evidence/final-verification.stdout` |
| Целостность kit после запуска | SHA-256 совпали для **215/215** source/fixture files | `evidence/replay.stdout`, `upstream/manifest.json` |

Ручной sample не переписывает приложение. Он импортирует **существующие** `Conversation`, `track_order`, `start_return`, `CustomerBackend`, `checked_response`, вызывает их на вымышленных записях и проверяет результат. `get_order(5002)` не даёт ETA, реальный `track_order(5002)` возвращает `2026-10-03`; чужая запись недоступна; просроченный/final-sale return отвергнут без записи; eligible return запрещён отказом write gate и создаётся при разрешении. Отсутствующий serial отвергнут до вызова модели; malformed summary помечен low confidence; пустой summary вызывает ошибку. Это показывает применение механизмов, не качество планирования LLM и не слияние Orchestra.

В `manual_sample.py` пакет `app` — **upstream demo app**, намеренно помещённый первым в `sys.path`; в upstream tests так же. В bootstrap отдельно импортирован **Orchestra app** и проверен разрешённый абсолютный путь. Публикуемый stdout содержит `<WORKSPACE>/app/__init__.py`: реальный абсолютный префикс с локальными installation identifiers заменён согласно заданию. Это не утверждение об импортировании Orchestra в demo smoke и не проверка живого сервиса.

Lite report построен отдельной командой `node upstream/skills/skills/claude-api/shared/evals/report/build-report-lite.mjs evidence/lite-report-flow` с task-префиксом перед обоими путями. В flow предварительно побайтно скопированы только `results.jsonl` из опубликованных fold baseline/v1. В отчёте нет встроенных trace bodies; missing traces не дорисованы. Node renderer использует builtin fs/path, модельных/сетевых вызовов не содержит. Источники не изменялись. HTML — вывод стороннего renderer на публичных данных, не новый product UI.

Полный suite Orchestra не запускали: исходники Orchestra не менялись, запуск живых сервисов и интеграций не нужен для этой исследовательской задачи. Не проверены live Anthropic API/auth/совместимость SDK, server-side tool search, платные evals, качество full single-loop на модели, реальное распределение задач Orchestra, время/квота её процессов, сбои/восстановление toolkit на VPS. Required runner и imports доступны; пропущенных обязательных проверок из-за runner нет. Сохранённые ранее model logs только читались.

Данные fixtures публичные и вымышленные; доступ к credentials, БД/логам production или другим машинам не выполнялся. Маскирование stdout ограничено абсолютным workspace-префиксом; числовые результаты не перетипизированы. Оригиналы upstream license/source сохранены. Бинарные caches и временные файлы проверок не являются доказательствами и удалены из task-пакета.
