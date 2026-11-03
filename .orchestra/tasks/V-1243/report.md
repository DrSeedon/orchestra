# V-1243 — независимый host QA V-1240

## Результат

Проверен ровно кандидат `06f3af9a5536d4f2813c17469e258fcc39fb12ed` (`task-V-1240/enforce-hub-sol`). Исправлений source/test не вносил. Кандидат проверялся в отдельном локальном checkout с полной историей Git: `--is-shallow-repository=false`, `CLAUDE.md` — tracked symlink на `AGENTS.md`, `.env` и `.orchestra/private` в checkout отсутствуют. Рабочая ветка автора, текущий `main` (`79d525dc…`), сервисы и live state не изменялись.

Все **27** путей из `V-1240/source-hashes.sha256` сверены: `27/27 OK`. В частности, `app/models.py` SHA-256 `b745ff54a695407e87509b0987827b65b2cf75dae309f3ec29a8d3a3e1cf9ab6`; `tests/test_hub_sol_only_v1240.py` SHA-256 `3a9957644de2006a069d55277bee5495b48de8b1f80f32831375689590eb53aa`. Абсолютный импортированный `app` находится внутри этого exact-candidate checkout; абсолютный путь и источник проверки записаны в приватном `checkout-verification.log`.

## Проверки

| Проверка | Результат |
|---|---|
| `uv run --frozen python scripts/check_instruction_contract.py` | PASS: правила <16 KiB, `CLAUDE.md` указывает на `AGENTS.md`, KB индекс и ссылки проходят |
| `uv run --frozen python -m pytest tests/test_knowledge_instruction_source.py` | **3 passed**: архив, две клиентские копии правил и достижимость исторического источника |
| `uv run --frozen python scripts/check_pipeline_manifest.py --check` | PASS |
| 18 mapped test-файлов V-1240 (routing, backend, pool, session/manager, очередь, local Luna, defaults) | **1,153 passed, 4 deselected**; исключены только browser-marked layout cases. Полный набор тестов проекта не запускался. |

Python проверки шли serial через uv **0.11.28**, `--frozen`, offline; `nice=15`, `choom -n 1000`. Вызовы шли с очищенным env: без `NOTIFY_SOCKET`, auth, service/live DB и task-store values. Только тестовый SQLite и `TMPDIR`/pytest cache были в отдельном `/tmp` дереве вне checkout. Тесты использовали fake/mock Hub/provider; реальных CLI, аккаунтов, inference или provider requests не было.

## Mutation check — committed test

Проверка выполнена на committed `tests/test_hub_sol_only_v1240.py` в том же изолированном checkout. Набор включал все 22 параметризованных non-Sol refusal assertions и положительные проверки Sol, native orchestrator и protected local Luna:

- baseline: **38 passed**;
- отключён ровно один canonical отказ для не-Sol Hub, восстановив admission со stale enabled flags: **22 ожидаемых DID NOT RAISE**, **16 положительных проверок прошли**, неожиданных падений нет;
- после восстановления исходного `app/models.py`: **38 passed**.

SHA-256 source до и после восстановления совпал (`b745ff…9ab6`); mutant SHA-256 `39f9ea07d4f90675ff53c1d095244daf67db805a1e9f69a894f7c2b8082040f5`. Подробности в `mutation-proof-v1243.json` и трёх приватных raw logs.

## Контракты и recovery

Канонический `ensure_hub_worker_allowed` проверяется до spawn admission и model-reason/credit paths; session, manager, route и Hub backend повторяют guard перед загрузкой/переключением, backend connect/send/recovery и consumption pending input. Тесты покрывают aliases/direct IDs, versioned/catalog flags, creative reason и API-credit обходы. Refusal не меняет модель, историю или recovery latches и не делает provider call. Durable receipt может перейти в `FAILED_BEFORE_SUBMIT`, но исходный payload остаётся; отказ model-change для held route сохраняет `WAITING_QUOTA` без capacity/dispatch вызовов.

Старый Hub-session может быть **явно** переведён на Sol: API нормализует `hubsol` в canonical model, admission проверяет target, а текущий runtime путь вызывает `HubBackend.retarget_model` только для разрешённого Sol. При имеющемся thread код использует control-plane `t3_thread_configure`, не turn-send/inference; при отсутствии backend обновляет persisted model без генерации. Target-capacity и fake Hub retarget проверки прошли. Реальный remote результат не проверялся, migration автоматически не выполнялась. Отказ на не-Sol target не меняет старый model/history или latches.

Нативные orchestrator defaults/manual выбора и effort mappings не изменены; protected local Luna остаётся под прежним reason guard. Sol-only policy не меняет quota/capacity, privacy, ownership или queue controls.

## Ограничения и доказательства

Must-fix: не обнаружено в проверенном кандидате. Открыто: четыре browser/layout проверки сняты marker-фильтром; полный suite и live activation не выполнялись. Это host QA exact commit, не утверждение о production процессе или remote Hub ответах.

Reading order: этот итог → полный `.orchestra/tasks/V-1240/report.md`, `notes.md`, `mapped-tests.json` → exact candidate product/test diff → приватные логи `instruction_contract.log`, `missing_source_contracts.log`, `pipeline_manifest.log`, `mapped-tests.log`, `source-hash-check.log`, `checkout-verification.log`, `mutation-proof-v1243.json` и mutation logs. Raw host paths находятся только в `.orchestra/private/V-1243/`.

Сохранён только этот report в task worktree; candidate checkout и тестовое окружение — локальные временные данные. No merge, push, deployment or restart.


## Repair receipt — test interpreter environment (2026-11-02)

The failed merge test-gate selected only the exact `.venv` Python in the `enforce-hub-sol` worktree. Before repair, that interpreter returned `No module named pytest` for `python -m pytest --help`, matching an incomplete environment rather than a source/test failure. As `kesha`, only that worktree's ignored `.venv` was synchronized with locked `uv sync --frozen --offline`; sync exited 0 and installed 76 locked packages, including `pytest-timeout==2.4.0`.

Using the same interpreter, `python -m pytest --help` now exposes both `--timeout=TIMEOUT` and `--timeout-method={signal,thread}`. In a clean `env -i` probe with a **15-second per-node timeout**, `tests/test_hub_sol_only_v1240.py::test_all_non_sol_hub_requests_refuse_even_with_old_enabled_flags` passed **22/22** in 4.68s. The probe selected that node explicitly and supplied no exclusion selectors. In the repair shell `PYTEST_DISABLE_PLUGIN_AUTOLOAD` and `PYTEST_ADDOPTS` were unset; the probe environment was empty except for explicit non-secret paths/timeout inputs. The prior failed gate's child environment was not inspected, so its flags are not inferred; this receipt describes only the current repair shell and controlled probe.

Post-sync, the target worktree still has HEAD `2bbfa7a211bb0fa676a58ea2d6c3b65bc78cba23`, a clean Git status, and unchanged `uv.lock` hash (`51594d7af253f53060ba1fd89423c1230b722a4e`). No source, public task file, live DB, service, queue, latch or remote state there was modified. The exact environment proof, pre/post help output, sync log and guard-test log are mode-600 under `.orchestra/private/V-1243/`. No full suite was rerun; no provider was called. The prior terminal merge operation `77acb570-6baa-4847-b0a7-1fdb1d5f7dcb` was not replayed.
