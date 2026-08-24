<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

План пока не готов к реализации: есть несколько блокирующих противоречий между контрактом, frozen RED-оракулом и текущими ingress/runtime seams 😏 Провайдерские, модельные и eval-вызовы не запускались.

## Findings

1. blocking: доверенный `route_state` не определён.

   План требует, чтобы `route_state` собирался сервером и caller input не попадал в trusted path (`docs/tasks/298/plan.md:58-60, 82-85`), но frozen tests передают обычный словарь с `ox_eligible`, `ox_canary_green`, `spark_quota_available` и управляют выбором leaf (`tests/test_model_routing_tree.py:103-112`). Если router доверяет этим данным, MCP caller может подделать admission; если игнорирует — RED-тесты не пройдут. Нужен явный server-side state provider и отдельный test-only injection seam.

2. blocking: обязательные поля metadata отсутствуют в frozen oracle.

   `TaskRoutingMetadata` обязан содержать named-file count и explicit-decision flag (`docs/tasks/298/plan.md:56-58`), но `_metadata()` их не задаёт, а Spark-тест ожидает успешный выбор (`tests/test_model_routing_tree.py:23-34, 103-106`). При заявленном fail-closed поведении это либо `REFUSE_METADATA`, либо неявные небезопасные defaults. Нужно явно определить defaults/derived fields и закрепить их тестом.

3. blocking: порядок отказов противоречит acceptance.

   Первый policy rule требует отказ `REFUSE_METADATA` для invalid metadata (`docs/tasks/298/plan.md:10-13`), а T3 повторяет это (`docs/tasks/298/plan.md:110-114`). При этом T2 включает `openness="unknown", complexity="unknown"` и ожидает `REFUSE_SOL_AUTH` (`tests/test_model_routing_tree.py:47-62`). Нужно выбрать: unknown — это invalid metadata или валидный Sol-class, и синхронизировать policy, AC и oracle.

4. blocking: Sol authorization не имеет цельного trusted пути и обходится через `codex_review`.

   План требует ноль Sol spawn/review/eval calls без receipt (`docs/tasks/298/plan.md:96-99`), но `spawn_worker` сейчас не принимает receipt и пересылает caller-selected model напрямую (`app/mcp_stdio.py:894-927`). Отдельно `codex_review` принимает модель caller-а, а `_resolve_codex_review_model()` проверяет только Codex runtime/quota, не receipt (`app/mcp_stdio.py:2424-2460, 803-852`). Это конфликтует с non-goal «не менять `codex_review`» (`docs/tasks/298/plan.md:199-201`). Нужно описать issuer/trust root, транспорт receipt и обязательный gate для обоих путей.

5. blocking: Spark “one attempt” не покрывает существующие retries.

   T4 обещает одну попытку и отсутствие retry (`docs/tasks/298/plan.md:124-128`), но `OpenRouterClient.stream()` повторяет 429, 5xx, transport errors и некоторые 400 до `MAX_RETRIES` (`app/harness/llm.py:185-240`). `app/harness/llm.py` отсутствует в T4 file boundary. Нужен exact-model retry policy на этом seam и тест со счётчиком POST для каждого retryable failure.

6. blocking: quota/canary admission подвержен TOCTOU.

   Только OpenRouter получает заявленный atomic broker lease (`docs/tasks/298/plan.md:139-143`); для Spark quota, Codex quota, canary revision и route revision атомарной привязки решения к запуску/turn нет. Текущий код читает admission отдельно при spawn и отдельно перед send (`app/manager.py:760-780`, `app/session.py:1063-1087`). Два concurrent worker-а могут оба пройти stale snapshot и затем потратить последний ресурс. Нужны reservation/generation semantics и interleaving test.

7. suggestion: frozen RED oracle нужно формально заморозить в плане.

   Все tickets перечисляют `tests/test_model_routing_tree.py` как изменяемый файл, а T8 добавляет ещё focused tests (`docs/tasks/298/plan.md:75-85, 172-187`). При этом план не требует checksum/SHA-проверки или запрета правок frozen файла. Новые тесты следует вынести отдельно, а CI должен проверять неизменность oracle `6ff9718b`.

8. suggestion: T5 test не покрывает заявленный AC.

   `test_t7_ox_guard_rejects_paid_or_unknown_cost_before_provider_post` проверяет только статический `admit_attempt` (`tests/test_model_routing_tree.py:149-155`), но AC также обещает atomic lease, platform/upstream 429 distinction, persistence и monotonic cumulative cost (`docs/tasks/298/plan.md:139-143`). Нужны детерминированные fake-HTTP/SQLite тесты на эти ветви без реального provider call.

9. suggestion: migration/backcompat AC недостаточно конкретен.

   План обещает `legacy_unknown` и unchanged resume (`docs/tasks/298/plan.md:67-71, 191-197`), но не задаёт тест для старой DB-схемы, старого active worker и поведения его следующего turn. Текущие persistence paths используют ручные списки колонок (`app/db.py:967-1034`, `app/session.py:4553-4592`), поэтому нужно отдельно проверить migration, hydrate/load, save и отсутствие потери route fields.

10. question: какой именно публичный seam должен существовать?

   Canonical owner указан как `app/model_router.py:route_worker()` (`docs/tasks/298/plan.md:32-39`), но frozen oracle импортирует `app.mcp_stdio.route_worker` (`tests/test_model_routing_tree.py:15-19`), а текущего символа там нет. T1 должен явно требовать re-export/adapter в `mcp_stdio.py`; иначе реализация в новом owner корректна архитектурно, но acceptance всё равно останется красным.

## Verdict

❌ Not ready for implementation. Сначала нужно устранить trusted-state/receipt boundary, Sol bypass, Spark retry gap и TOCTOU admission; затем синхронизировать metadata contract, policy order и frozen oracle. Иначе план будет как турникет с табличкой «охрана есть», но проход проверяет только цвет куртки.
