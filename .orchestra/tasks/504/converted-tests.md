> **RETRACTED как описание текущего main (08.09.2026, #530).** Ниже — историческое доказательство ветки #504, а не действующий контракт. Утверждения о живых площадках A, необходимости внедрить T1/T2/T3/T5, ожидании T4 и текущей пригодности прежних оракулов отменены коммитом `264daeb75484bbe9f97e53c654180fca11c8a12a`: main уже отделяет управление от прозы, удаляет T4-классификатор и safeguard-fork, использует `provider_limit`, завершение CLI и временный round hint. Исторические результаты тестов остаются результатами своих снимков, не текущего main. Адресная развязка всех десяти площадок и тестов: [дифференциал #530](../530/diff-main-vs-504.md). Исходные байты: `git show bf496f8828e4ae5859ac09fd1a20a864ac9e895b:.orchestra/tasks/504/converted-tests.md`.

# #504 converted legacy assertions on unchanged production

All commands used `/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q <node>`. Every converted test returned RC=1 from a behavioral assertion. `--collect-only` over all six modified test modules returned RC=0 with 476 tests, so none is red from import/collection failure.

| # | current test name | assertion before #504 | assertion after conversion | unchanged-production result |
|---:|---|---|---|---|
| C01 | `test_t1_rate_limit_event_preserves_structured_fields_and_exact_raw_payload` | `RateLimitEvent` becomes `type="status"` containing `RATE_LIMIT_RAW <json>` | event is `type="rate_limit"` with exact typed metadata and empty prose payload | RC=1: `T1 seam: Claude RateLimitEvent is still flattened into status text` |
| C02 | `TestCompactGuards::test_compact_rejects_typed_limit_event_and_preserves_session` | a plain provider-banner `text` event aborts compact | a typed rejected `rate_limit` event aborts compact; valid summary text cannot substitute for it | RC=1: current code ignores typed event and returns `ok=True` |
| C03 | `TestRateLimitClassification::test_t1_monthly_spend_words_are_not_terminal_without_typed_event` | prose containing `monthly spend limit` is terminal and never retried | the same ordinary prose leaves `_session_limit_hit=False` and a transient error retries | RC=1: `ordinary model prose still marks the session limited` |
| C04 | `TestRateLimitClassification::test_terminal_limit_turn_skips_duplicate_error_and_precompact` | plain provider-banner text arms terminal handling | typed rejected `rate_limit` event arms the same terminal behavior | RC=1: current code ignores the typed event and logs `turn FAILED: rate_limit` |
| C05 | `TestSafeguardRefusal::test_t5_text_event_does_not_raise_the_safeguard_flag` | provider-looking plain text sets `_safeguard_refusal=VERBATIM` | plain model text leaves `_safeguard_refusal=""` | RC=1: `model-authored text still arms history rewind` |
| C06 | `TestSafeguardRefusal::test_refusal_recognised_from_typed_event_when_it_is_not_last_text` | a plain `text` event containing the banner arms the flag in either order | a typed `safeguard_refusal` event arms it; surrounding model text does not | RC=1: current code ignores the typed event |
| C07 | `test_find_limit_stopped_agents_only_returns_latest_limited_turn` | model/provider text plus generic terminal error determines limit kind | structured `rate_limit` log determines kind and latest limited turn | RC=1: current parser returns `timed` instead of typed `monthly` |
| C08 | `test_t1_typed_limit_kind_overrides_monthly_words_in_model_text` | model words `monthly spend limit` determine `monthly` | typed `five_hour` event determines `timed` even when prose says monthly | RC=1: `limit kind is still inferred from model prose` |
| C09 | `test_limit_detection_uses_event_timestamp_when_log_ids_commit_out_of_order` | text phrase supplies evidence while timestamps only order it | typed monthly event supplies evidence and timestamps still order it | RC=1: `typed monthly kind was ignored` |
| C10 | `TestRunExecOutcome::test_t2_exit_zero_verdict_with_failure_phrase_is_not_rejected` | `bwrap:` anywhere in a verdict-bearing artifact forces `failed` | exit-0 + valid artifact/verdict triggers success regardless of prose | RC=1: `valid paid review is still rejected by its own prose` |
| C11 | `test_t4_model_xml_prose_is_not_classified_as_unexecuted_tool_call` | two legacy XML tags add one “НЕ ВЫПОЛНЕНО” warning | the same model prose renders with zero warning and browser regex owner absent | RC=1: `model prose is still labelled as an unexecuted tool call; warnings=1` |

Raw command outputs are stored once: C01-C09 in `converted-C01.txt` … `converted-C09.txt`; C10 and C11 reuse the ticket artifacts `red-T2.txt` and `red-T4.txt` rather than duplicating them.

## Phase 3 stale-representation corrections

Three tests reached the right behavioral claim through an obsolete or unreachable representation. No behavioral assertion was relaxed:

| test | before | after | proof |
|---|---|---|---|
| `TestRateLimitClassification::test_t1_monthly_spend_words_are_not_terminal_without_typed_event` | compared coroutine objects directly with `["_rate_limit_retry"]` behind the original first RED assertion | compares exact `coro.cr_code.co_name` list with the same one-element expected list | corrected test RC=1 on `bdfe0395^` production and RC=0 on T1 WIP; `refreeze-T1-base.txt`, `refreeze-T1-wip.txt` |
| `TestCompactReArmsPromptInjection::test_failed_compact_leaves_injection_flag_untouched` | provider-limit state reached through a plain banner `text` event | same state reached through rejected typed `rate_limit` metadata; name and assertions unchanged | mutation clearing `_prompt_injected` made RC=1; restored + `touch` made RC=0; `t5-mutation-red.txt`, `t5-corrected-green.txt` |
| `test_codex_review_quotes_exec_resume_uuid` | fake successful review emitted zero `command_execution` evidence | fixture adds one completed `command_execution(status="completed", exit_code=0)`; name and assertions unchanged | isolated quoting mutation made RC=1 at the original resume-UUID assertion; restored + `touch` made RC=0; `quote-mutation-red.txt`, `quote-restored-green.txt` |

General distinction: a stale assertion asks the wrong question; a stale stimulus still asks the right question but can no longer reach its state after the typed contract replaces the text contract.
