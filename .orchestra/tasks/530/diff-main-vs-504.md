# #530 — дифференциал main и исторической ветки #504

Проверяемый main и исходный HEAD worktree: `67b1ada1130e67ed635263455e6a5c5dbd91a4ab`.
Источник #504: `bf496f8828e4ae5859ac09fd1a20a864ac9e895b`, ветка
`task-504/research-text-oracles`; merge-base — `1b7953008a050e7d0a987db5a40e4153fbd888ab`.
Все шесть обязательных документов прочитаны полностью через `git show` до изменений.

## Изменение задания

В main уже входит `264daeb75484bbe9f97e53c654180fca11c8a12a` от 07.09.2026,
автор — владелец: `Separate runtime control from model prose and preserve review results`.
Его согласованный контракт описан в
[результате реализации main](../model-text-control-flow/result.md).
После предъявления различий постановщик отменил перенос production: main выигрывает,
`app/**` не менять, xfail не добавлять, сохранить историю и только дополнительные зелёные тесты.
Перенос production не начинался; конфликтные файлы не заменялись версиями #504.

## Десять площадок A

Номера и старые координаты взяты из [таблицы #504](../504/research.md).
Две ветви лимитов, две копии очистки истории и две копии T4 считаются отдельно;
добавленная во второй фазе площадка JSONL обозначена 6b.
Ниже «закрыта» означает отсутствие исходного решения по свободной прозе модели,
а не эквивалентность архитектуры #504 и main.

| Площадка #504 / старое место | Что текст решал | Закрытие в текущем main | Вариант #504 | Существенное различие контрактов | Открыта |
|---|---|---|---|---|---|
| 1 — `app/session.py:248`, monthly | Фраза `monthly spend limit` включала терминальный лимит | `app/backend_claude.py:1397` создаёт `provider_limit`; `app/session.py:2414` блокирует только по первичному `status=rejected`. В `app/limit_wake.py:82` читается типизированная запись | `rate_limit`, точная карта `overage → monthly`, журнал с `limit_kind` | Да: main сохраняет `RATE_LIMIT_RAW` отдельно и использует `provider_limit`; wake возвращает `overage`, не `monthly`. Наследные server status/error допускаются, `text` исключён | Нет |
| 2 — `app/session.py:250`, timed | Слова `session limit` / `usage limit` запрещали retry и compact | Тот же producer/consumer; retry в `app/session.py:2454` читает `metadata.model_error`, а поздний отказ проверяется повторно под lifecycle-lock. Wake фильтрует `provider_limit/error/status` | Точный список окон даёт `timed`, неизвестное — терминальный `unknown` без автоматического wake | Да: main относит неизвестный rejected window к `timed` при поиске wake, #504 запрещал угадывание. Это различие обработки типизированных данных, не незакрытая площадка A | Нет |
| 3 — `app/session.py:284`, safeguard | Префикс `api error:` и слова safeguard ставили флаг; провал хода запускал fork/rewind | `app/session.py:2408` сохраняет прозу; `app/session_turns.py` больше не содержит `_rewind_past_safeguard_refusal` и ветви автоотката. `AssistantMessage.error` остаётся отдельным provider error | `safeguard_refusal` из `invalid_request` + provider-banner fallback; прежний auto-fork сохранялся | Да: main удалил автоматический откат и сохраняет исходную историю; #504 восстанавливал бы отменённую возможность | Нет |
| 4 — `app/session.py:3013`, compact | `_GARBAGE_PATTERNS` и терминальный matcher отбрасывали короткую успешную сводку | `app/session.py:2938` требует `turn_end`, `ok is True`, отсутствие error и непустой summary. Вывод tool не становится сводкой | Отдельные `rate_limit/safeguard_refusal/error` запрещают compact; слово в summary не влияет | Да: main дополнительно отвергает обрыв без `turn_end` и неуспешный turn, не примешивает tool-output. Перенос #504 ослабил бы эти проверки | Нет |
| 5 — `app/tool_call_guard.py:27`, TG | Две XML-формы в прозе давали ярлык «НЕ ВЫПОЛНЕНО» | Модуль удалён в `264daeb7`; в `app/tg_bridge.py` нет его импортов и вызовов, outcome реального инструмента читается из `tool_is_error` | T4 оставлен без production-изменений | Да: HELD относится только к исторической #504; main уже удалил классификатор | Нет |
| 6 — `app/bg_jobs.py:54`, review artifact/stdout | `_BLIND_REVIEW` отвергал RC=0 и оформленный вердикт из-за текста | `app/bg_jobs.py:1072` использует общий `review_result_error`; произвольный artifact/stdout не сканируется на `bwrap:`. Последний явный Verdict остаётся контрактом B; advisory-ветвь сохранена | Проза игнорируется; проверка Verdict остаётся, execution вынесен в shell JSONL guard | Да: main использует общий parser последнего результата и отдельный advisory режим, сохраняет частичные находки. Успешный stdout с прежней фразой не отвергается обоими | Нет |
| 6b — `app/mcp_stdio.py:3590`, JSONL agent text | Regex по `agent_message.text` выставлял `execution_guard` | Shell matcher удалён; `app/mcp_stdio.py:4669` вызывает финализатор. `app/codex_review_artifact.py:36` требует последний завершённый CLI turn и непустой финальный ответ, учитывает typed error | Требуется хотя бы один `command_execution(status=completed, exit_code=0)` | Да: успешная команда не является обязательным доказательством main; он проверяет завершение CLI и ответ, а качество ревью из этого не выводит. Прежние command-only оракулы несовместимы | Нет |
| 7 — `app/harness/loop.py:209`, history | Удаление всех сообщений с префиксом `[round guard]` | `_round_hint` в `app/harness/loop.py:131` добавляется только в текущий запрос (`:228`), вообще не записывается в history | Список producer-owned объектов; удаление только по `is` | Да: main предотвращает попадание guard в историю, #504 сначала записывает, затем чистит | Нет |
| 8 — `app/harness/loop.py:211`, new_messages | Второй prefix-фильтр удалял модельную цитату перед persistence | Тот же request-only hint; `new_messages` его не получает; `finally` очищает только `_round_hint` (`:206`). Размер hint учтён в token budget (`:406`) | Один identity-предикат чистит оба массива | Да: main не нуждается в cleanup двух массивов, сохраняет учёт контекста текущего запроса | Нет |
| 9 — `app/static/js/chat.js:794`, browser | Вторая копия XML-matcher добавляла ложный ярлык | Определения и вызовы удалены в `264daeb7`; `addChatEntry` (`app/static/js/chat.js:3838`) выводит текст без этого решения. Main browser-тест зелёный | T4 оставлен без production-изменений | Да: main уже закрыл HELD-площадку; xfail(strict=True) на её отсутствие дал бы XPASS | Нет |

Открытых исходных площадок A: **0 из 10**. Это адресный дифференциал исходного
инвентаря, не новый exhaustive-аудит app. Остальные 83 площадки C не менялись и заново
не проверялись. Контракты B, промпты, статусы вердиктов и форматы находок не менялись.

## Отбор тестов #504

Весь delta тестов проверен через `git diff 1b795300 task-504/research-text-oracles -- tests`.
Условие переноса: тест проходит на неизменённом production main и даёт дополнительное
покрытие относительно `tests/test_model_text_control_flow.py`. Дубли уже имеющихся
проверок в других файлах тоже не копировались. Отброшенные оракулы не переписывались
ради зелёного результата и не помечались xfail.

| Тест / изменение из #504 | Решение и причина |
|---|---|
| `TestRunExecOutcome::test_t2_exit_zero_stdout_failure_phrase_is_not_rejected` | Перенесён без изменения тела в `tests/test_bg_jobs.py`. Проверяет настоящий subprocess → validation → persisted job `triggered` → wake без FAILED, когда stdout содержит `bwrap:`. В main модуле `test_model_text_control_flow.py` есть только helper-проверка review prose, stdout-путь отсутствует |
| `TestRunExecOutcome::test_t2_exit_zero_verdict_with_failure_phrase_is_not_rejected` | Не копируется: main уже содержит `test_exit_zero_verdict_with_bwrap_is_preserved`, включая сохранность артефакта |
| Четыре `test_t2_jsonl_*` и `_guard_returncode` из `test_model_text_control_flow_504.py` | Отброшены, потому что кодируют обязательный успешный `command_execution` и прежний shell guard, отменённые в `264daeb7`. Main проверяет terminal CLI + final response; её typed positive/negative controls уже есть |
| `test_t3_model_authored_round_guard_prefix_survives_history_cleanup` | Перенесён без изменения тела в `tests/test_harness_tools.py`. Main `test_round_guard_quote_preserved_and_runtime_hint_ephemeral` проверяет сохранность цитаты только в history, а для new_messages проверяет лишь отсутствие platform hints. Оракул #504 дополнительно требует сохранения assistant quote в new_messages — источнике persistence |
| `test_t4_model_xml_prose_is_not_classified_as_unexecuted_tool_call` | Не копируется: browser-поведение уже покрыто `test_model_xml_is_displayed_without_execution_verdict`, фактический запуск зелёный. Состояние «T4 HELD» отменено в `264daeb7` |
| `test_t4_model_text_classifier_has_no_python_or_browser_owner` | Не копируется: удаление owner уже выполнено; перенос как xfail противоречил бы main. Статическая проверка отсутствия символов выполнена при дифференциале, отдельного wording/ownership-теста не добавлено |
| `test_t1_rate_limit_event_preserves_structured_fields_and_exact_raw_payload` (C01) | Отброшен, потому что кодирует единственный event `rate_limit`, отменённый альтернативным контрактом в `264daeb7`: main отдаёт status telemetry + `provider_limit`. Типизированный первичный статус main покрыт параметризованным adapter-тестом, exact raw — `test_rate_limit_capture_441.py` |
| `TestCompactGuards::test_compact_rejects_typed_limit_event_and_preserves_session` (C02) | Отброшен: ввод `rate_limit` кодирует отменённый event contract в `264daeb7`; существующий main-тест уже вводит `provider_limit` |
| `TestRateLimitClassification::test_t1_monthly_spend_words_are_not_terminal_without_typed_event` (C03) | Отброшен: ожидает retry от одного `error.content=rate_limit` без metadata, что отменено в `264daeb7`. Main отдельно проверяет безвредность прозы и retry по `metadata.model_error` |
| Изменение `test_terminal_limit_turn_skips_duplicate_error_and_precompact` (C04) | Отброшено: `rate_limit` вместо `provider_limit` и неструктурированный error — отменённые в `264daeb7` представления. Поведенческий тест с main-сигналом уже есть |
| `test_t5_text_event_does_not_raise_the_safeguard_flag` (C05) | Не копируется: main `test_prose_never_sets_runtime_failure` уже проверяет этот запрет; direct attribute `_safeguard_refusal` удалён в `264daeb7` |
| `test_refusal_recognised_from_typed_event_when_it_is_not_last_text` (C06) | Отброшен, потому что кодирует флаг для auto-fork, отменённый в `264daeb7`. Main проверяет сохранение истории и отсутствие вызова fork |
| `test_t5_safeguard_banner_isolated_by_typed_provider_error_channel` | Отброшен, потому что кодирует event `safeguard_refusal` для прежнего восстановления, отменённого в `264daeb7`; обычный provider error остаётся |
| Три изменения wake C07/C08/C09 (`test_find_limit_stopped_agents_only_returns_latest_limited_turn`, `test_t1_typed_limit_kind_overrides_monthly_words_in_model_text`, `test_limit_detection_uses_event_timestamp_when_log_ids_commit_out_of_order`) и `_typed_limit_log` | Отброшены, потому что кодируют журнал `rate_limit/limit_kind=monthly`, отменённый альтернативным журналом `provider_limit` в `264daeb7`. Независимость wake от прозы и порядок timestamp уже покрыты main |
| `test_t5_compact_accepts_short_summary_that_discusses_rate_limits` и параметр `summary_text` helper | Не копируются: такого теста нет в `test_model_text_control_flow.py`, но он уже есть в `test_compact_receipt_and_tail.py::test_summary_can_quote_provider_errors` и проверяет то же поведение |
| Изменение `test_failed_compact_leaves_injection_flag_untouched` | Отброшено: #504 вводит отменённое имя `rate_limit`; main использует `provider_limit`, проверка сохранения injection state остаётся |
| Две fixture-правки `test_codex_review_sandbox.py` (command status/exit=0 и resume command event) | Отброшены, потому что кодируют обязательность успешной команды, отменённую в `264daeb7`. Main-фикстуры завершённого CLI не заменялись |

Тест без переноса stdout-проверки оставил бы реальную регрессию: вывод успешной
команды, цитирующий прежний marker, снова мог бы превратить завершённый job в failed.
Это проверяется мутацией только в памяти отдельного pytest-процесса,
без записи в `app/**`: [mutation_stdout.py](mutation_stdout.py).
Второй перенесённый тест защищает сохранение модельной цитаты в `new_messages`:
history может оставаться правильной, а persistence потерять ответ. Его мутация
возвращает старый prefix-фильтр только в `new_messages`, не затрагивая history:
[mutation_history.py](mutation_history.py).

## Архив и границы доказательств

43 исходных файла `.orchestra/tasks/504/` перенесены из указанного source commit.
[Манифест](archive-manifest.json) содержит исходный и перенесённый SHA-256 каждого.
Markdown получает RETRACTED-область применимости с перечнем отменённых current-state
утверждений и ссылкой на этот дифференциал; численные результаты не пересчитываются.
Выводы pytest и JSON манифесты прежнего полного сьюта сохраняются побайтно.
Их сообщения о failed/T4 описывают исторические запуски, не сегодняшний main.

`check_anchors.py` закреплён на `1b795300`: это до-реализационная инвентаризация,
текущий код не проверяет. `git diff 1b795300 f21b4ab5 -- app` пустой, поэтому смена
historical ref с f21 на исходный merge-base не меняет проверяемые production-байты.
`blast_test.py` явно архивный: его старые импорты не заменялись совместимыми обёртками.
Историческая ветка не удалялась; исходные байты доступны через `git show`.

Полный сьют не запускался. Production, промпты, T4, сервисы, live БД и VPS не изменялись.
Проверки и итоговые RC — в [результате #530](result.md).
