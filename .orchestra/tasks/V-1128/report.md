# V-1128 — исключение всех оркестраторов из policy quota gate

Дата: 2026-10-29. Source-only worker; код на работающем сервисе не менялся.

## Уточнение после host-прогона

По сообщению родителя, required full на интегрированном
`eb096a71ec21dbaeed3cd7c835823062912e01a3`: **6767 passed, 54 skipped, 1 failed,
467.56 s**. Этот прогон НЕ зелёный. Единственный FAIL:
`tests/test_t344_quota_lines_browser.py::test_hard_99_stops_everyone_and_orchestrator_still_works`,
строка 864: `.ql-chart` совпал с двумя SVG (timeline и quota chart), поэтому
`inner_text()` нарушил Playwright strict mode. Предыдущие assertions blocked workers,
бейджа всех оркестраторов и отсутствия Claude в бейдже прошли.

Селектор уточнён до `[data-ql-panel='all'] svg[data-ql-chart='all']`: проверяет именно
quota chart, без `.first`, ослабления assertion или изменения production-кода.
Следующий host single-case после `51c5ad6fc`: **1 failed, 4.21 s** — селектор уже
однозначен, но SVG не является HTMLElement: `Locator.inner_text: Node is not an HTMLElement`.
Предшествующие worker-hard-stop/all-orchestrator-badge assertions прошли. На той же строке
`inner_text()` заменён на SVG-совместимый `text_content()`; точный селектор и проверяемый
текст сохранены. Production-код не изменён. Повторный single/full после этой замены ещё
не выполнен; полный runner родитель не перезапускал на известном red.
В копии Chromium по-прежнему отсутствует; для этой замены проверены AST и точный
однострочный diff (`svg-text-content-check.log`), браузерный успех не заявляется.
Родитель также подтвердил собственные gate/queue/wake мутации: **20/8/3** красных
committed cases; исходники после контролей byte-identical.
Локально через provisioned uv 0.11.28 выполнено:
```sh
uv run --frozen python -m pytest tests/test_t344_quota_lines_browser.py::test_hard_99_stops_everyone_and_orchestrator_still_works -q --basetemp=.orchestra/tasks/V-1128/tmp/selector --override-ini=cache_dir=.orchestra/tasks/V-1128/tmp/pytest-cache
```
Итог: **1 setup error, 2.54 s**, exit 1: тот же отсутствующий Chromium executable,
до assertions выполнение не дошло. Лог: `selector-followup-tests.log`. Синтаксис Python
проверен; сверка с прежним SHA подтверждает ровно одну изменённую строку теста.
Результаты source-copy ниже сохранены как предыдущая диагностика, а не итог host-проверки.

## Решение владельца

Переданное в задании решение от **2026-10-29 18:37 KRS**:
> orchestrators must ALWAYS work independently of quota gate.

Датированное правило закреплено по-английски в каноническом модуле
`.orchestra/pipelines/default/prompts/modules/safety.md`, рядом с правилом quota admission.
Личный routing не продублирован; корневой AGENTS.md и model-review не изменены.

## Изменения

- `session_requires_quota` теперь зависит только от признака оркестратора. Существующие
  вызовы manager creation, delivery preflight, send и pending flush автоматически получают
  одинаковое исключение, включая legacy model names и все message origins.
- `quota_queue` снимает старые policy holds с оркестраторов для обеих durable-очередей.
  Исключение проверяется до кеша решений по модели: worker и orchestrator одной модели
  не наследуют решения друг друга. Порядок initial-before-direct и условные UPDATE сохранены.
- Codex limit-wake передаёт признак оркестратора и при release, и при фактическом send.
  Gate обычного worker сохранён. Для всех остаются свежая provider capacity, проверка
  wake binding, отмены, Stop/new instruction/task/model/branch/runtime generation guards.
  Wake cache разделён по модели и признаку оркестратора.
- Policy hard stop 99% больше не держит оркестратора. Реальный provider limit не скрывается:
  после provider refusal автоматический wake по-прежнему ждёт подтверждённую ёмкость;
  100%, неполные окна и ошибка refresh не считаются восстановлением. Исключение не создаёт
  utilization/observation. Обычный provider send error остаётся видимым, без fallback.
- Бейдж говорит «Все оркестраторы: всегда работают»; из подписи/легенды/графика убран Claude-only
  qualifier. Формулы и остальная UI не менялись. CHANGELOG честно отмечает ошибочное применение
  V-1121 к Codex-оркестраторам и исправление V-1128.
- Старые неверные ожидания заменены в V-1121 и writer-lock тестах; queue/recovery проверки
  сохранены для обычных workers. Добавлены отрицательные/разрешающие случаи и реальные
  blocked/hard-99 решения, concurrency/idempotency и guards.

## Неочевидные детали

1. `save_session` при UPDATE намеренно не меняет `is_orchestrator`. Поэтому recovery fixtures
   задают kind и в памяти, и в своей SQLite; изменение только Python-поля моделировало бы
   противоречивые данные. Production persistence не изменён.
2. В recovery явный сохранённый kind имеет приоритет; только отсутствующий/None использует
   существующий legacy role fallback, как AgentSession. Название агента не используется.
3. Codex wake раньше принудительно попадал в admission даже после исправления общего helper.
   Пропустить только обычный send gate было недостаточно. Provider readiness выделено от policy.
4. Существующие отдельные Hub pool/configuration readiness checks не менялись. Ни Hub account
   data, ни реальные provider/paid/native вызовы для проверки не использовались.

## Runner и фактические проверки

Использован provisioned **uv 0.11.28**, default `.venv`, frozen lock. Не подменял runner.
Импорт проверен: **`app/__init__.py`**, interpreter **`.venv/bin/python3`** — оба из этой копии.
Pinned setup создал окружение из uv.lock; дополнительных установок, Chromium install не было.
TMPDIR и pytest basetemp направлены внутрь каталога этой задачи.

В каждой test shell:
```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1128/tmp"
```

Финальная команда:
```sh
uv run --frozen python -m pytest tests/test_codex_quota_gate_1121.py tests/test_codex_limit_resume_v1081.py tests/test_quota_wait_queue.py tests/test_quota_gate.py tests/test_quota_headroom_447.py tests/test_quota_admission_e2e.py tests/test_quota_admission_collection.py tests/test_session.py tests/test_manager.py tests/test_limit_wake.py tests/test_codex_writer_conflict_536.py tests/test_message_delivery_receipts_380.py tests/test_initial_delivery_review_regressions.py tests/test_delivery_head_of_line_block.py tests/test_i18n_quota_gate_reasons.py tests/test_usage_readiness.py tests/test_agent_hub_routing.py tests/test_hub_pool.py tests/test_t344_quota_lines_browser.py -q --basetemp=.orchestra/tasks/V-1128/tmp/pytest --junitxml=.orchestra/tasks/V-1128/targeted-results.xml
```

Результат: **867 passed, 129 failed, 39 errors, 89.84 s**; exit 1. Это НЕ зелёный полный прогон.

| Проверка | Passed | Failed / errors |
|---|---:|---:|
| V-1121 admission/session regressions, включая Node formula + panel rendering | 96 | 0 |
| Codex provider-limit recovery V-1081/V-1128 | 74 | 0 |
| Durable quota queues | 33 | 0 |
| Writer-lock | 7 | 0 |
| Session | 250 | 0 |
| Quota gate | 108 | 0 |
| Limit wake | 52 | 0 |
| Message receipts / initial review / head-of-line | 38 | 0 |
| Routing / Hub pool / usage readiness / collection | 134 | 0 |
| Manager | 69 | 115 failed |
| Quota admission E2E | 2 | 14 failed |
| Headroom / i18n / quota browser | 4 | 39 setup errors |

**210 тестов четырёх модулей, изменённых для backend/queue регрессий, прошли полностью.**
Остальные 129 падений находятся в manager/E2E: отсутствуют provisioned
`.orchestra/pipelines/default/pipeline.yaml` и source skills `laptop-access` / `html-artifacts`;
производные resume/skill assertions и traceback сохранены в диагностике. Не создавал вместо
отсутствующих исходников фиктивный production manifest. Новый creation admission test имеет
свой минимальный manifest и останавливает вызов сразу после admission, до выделения ресурсов.

Все **39 browser setup errors**: отсутствует Playwright Chromium executable
`[home]/.cache/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-linux64/chrome-headless-shell`.
Отдельная команда `uv run --frozen python -m pytest tests/test_t344_quota_lines_browser.py -q`
с task-local basetemp также дала 35 setup errors. Chromium не устанавливался. Node проверил
реальное построение панели, текст исключения и совпадение формул с Python; это не заменяет
браузерный прогон на полном хосте.

## Чувствительность регрессий

Отдельные offline pytest processes, без изменения исходных файлов:
```sh
uv run --frozen python .orchestra/tasks/V-1128/mutations.py old-gate
uv run --frozen python .orchestra/tasks/V-1128/mutations.py model-only-queue
uv run --frozen python .orchestra/tasks/V-1128/mutations.py forced-wake-gate
```

- Возврат исходного `not is_orchestrator or runtime == "codex"`: **20 failed, 34 passed**.
- Удаление проверки kind при release: **8 failed**.
- Возврат обязательного policy admission в Codex wake: **3 failed, 2 passed**.

Во всех трёх pytest вернул TESTS_FAILED (1), что проверяет mutation runner. Блокировки обычных
workers сохранились. Логи этих намеренно красных прогонов не являются результатом финального кода.

## Артефакты и оставшаяся проверка

- `final-targeted-tests.log`, `targeted-results.xml`, `test-summary.json`: финальные результаты.
- `mutation-*.log`, `mutations.py`: воспроизводимая чувствительность к трём регрессиям.
- `runner.log`, `js-tests.log`, `browser-tests.log`: runner/Node/browser evidence.
- Промежуточные `first-tests.log`, `core-tests.log`, `final-core-tests.log`, `targeted-tests.log`
  сохраняют диагностику до исправления фикстур/старого writer expectation/Node harness.
- `source-files.sha256`: 13 изменённых source/test/document файлов. Проверены синтаксис Python,
  окончания строк и trailing whitespace. В логах детерминированно заменены приватные execution
  paths на placeholders; применён publication secret filter. Временные test repositories удалены.

Повтор required full и браузерная проверка после уточнения селектора остаются родителю.
Live override, env, сервисы, deployment и restart не трогал. Git commit/push не выполнял:
изменения импортирует и коммитит платформа на назначенную ветку.
