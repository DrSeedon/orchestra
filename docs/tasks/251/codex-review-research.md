## Summary

Адресные тесты проходят:

```text
uv run pytest -q tests/test_backend_grok.py
85 passed in 4.86s
```

Однако обязательная проверка отключения телеметрии с положительным контролем отсутствует. Эмпирические выводы также не воспроизводимы из bundle: нет raw-данных, результатов скоринга или scorer-а. Формула long-context и вычитание стоимости X-вызовов опираются на агрегаты, семантика которых не доказана.

## Findings

1. **blocking: Проверка телеметрии не доказывает, что исходящие каналы действительно закрыты.**  
   `app/backend_grok.py` добавляет предполагаемые TOML-ключи и переменные окружения, а `test_build_env_disables_every_grok_telemetry_channel` проверяет только содержимое словаря Python. Нет запуска Grok под сетевым наблюдением и обязательного положительного контроля, который сначала обнаруживает заведомый исходящий запрос. Поэтому тест останется зелёным, если CLI игнорирует все эти имена, использует иной канал либо конфиг имеет больший приоритет. Это прямо не закрывает security-требование задачи. Нужен один и тот же сетевой oracle: разрешённый контрольный endpoint обязан быть замечен, затем Grok-run — не давать обращений к каждому обнаруженному analytics/feedback/trace/crash/OTEL endpoint.

2. **suggestion: Не доказано, что новые TOML-ключи принимаются Grok 1.0.3.**  
   В `_GROK_SANDBOX_CONFIG` добавлены, среди прочего, `events_url`, `mixpanel_enabled`, `otel_enabled` и `otel_log_tool_details`, но focused-тест лишь читает файл как текст. Он не запускает CLI с этим generated config. Если парсер строгий либо тип/секция неверны, после общего рестарта Grok backend может перестать стартовать. Добавьте credential-free smoke-run CLI с временным `GROK_HOME`, проверяющий успешный разбор именно сгенерированного файла.

3. **suggestion: Выводы 18 прогонов невозможно проверить по integrated bundle.**  
   `docs/grok-field-guide.md` утверждает: «`18 ходов с 113 completed X-вызовами и 19 X batch-id`», но diff содержит только preregistration, prompts и runner. Нет `raw/`, таблицы 18 оценок, расчёта шума, фабрикаций, paired delta или итогового решения о сохранении 4.5. Нужен санитизированный результат и воспроизводимый scorer; иначе claims `18/18`, `17/18` и отсутствие/наличие материального преимущества являются неподтверждёнными.

4. **suggestion: Стоимость X-вызовов вычитается по недоказанной единице учёта.**  
   `test_cost_fallback_matches_both_live_context_tiers` использует:

   ```python
   reported - x_calls * 0.005
   ```

   При этом field guide сообщает, что batch `10+8` дал один `turn_completed`, а формула разошлась лишь на `$0.05`, не на `$0.09`. Там же сказано, что account billing truth недоступен. Следовательно, ни `completed X-вызов`, ни batch item пока не доказаны как биллинговая единица. Тест превращает гипотезу в точный oracle с `abs=1e-12`. Оставьте расхождение явно некалиброванным либо докажите единицу независимым billing delta.

5. **suggestion: Long-context fallback применяет порог к агрегату хода, хотя тарифный порог относится к отдельному model request.**  
   `_grok_cost()` удваивает стоимость всех токенов, когда агрегированный `input_tokens >= 200_000`. Но комментарий называет ACP `inputTokens` «full prompt sum», а исследование одновременно фиксирует внутренние tool loops. Сумма нескольких запросов может превысить 200k, даже если ни один запрос порога не достиг; возможен и смешанный ход, где лишь часть запросов тарифицируется ×2. Три совпавших агрегата не доказывают корректность общего fallback. Нужны per-inference token counts либо fallback должен честно считаться неопределённым для multi-call turns.

6. **suggestion: Предрегистрированная оценка не реализована и допускает субъективный скоринг.**  
   В `prereg.md` заданы пункты вроде «содержание без смыслового искажения» и «нет выдуманного», но нет машинного scorer-а, blinded adjudication или сохранённых индивидуальных оценок. Также `tools_used` присутствует в модельном JSON, хотя баллы должны начисляться по native trace, а не самоотчёту модели. Зафиксируйте scorer до раскрытия model labels и извлекайте tool success непосредственно из JSONL trace.

7. **question: Где доказательство read-only проверки ноутбука и перечень скопированных настроек?**  
   В review bundle нет артефакта, показывающего, что конфигурация ноутбука только читалась, какие безопасные настройки признаны полезными и какие именно перенесены на VPS. Без credential-free, санитизированного отчёта этот обязательный вывод задачи неаудируем.

## Verdict

**REQUEST CHANGES.** Блокирует отсутствие реальной проверки закрытия телеметрии с положительным контролем. Эмпирические выводы и две формулы учёта также требуют воспроизводимых данных либо более осторожной формулировки.

## Round (2026-08-13T08:09:00Z)

## Re-review status — Round 2

1. **FIXED — telemetry positive control.**  
   `telemetry_probe.py` runs the same real CLI turn in both arms. The control observed `POST /events` ×19, `/v1/logs` ×2, and `/v1/metrics` ×1; the hardened production arm completed with rc=0 and zero collector requests. It also exercises parsing of the generated managed config.

2. **FIXED — managed TOML smoke test.**  
   The production arm performs an authenticated model call using `GrokBackend._build_env()` and the generated `GROK_HOME`, not merely a textual config assertion.

3. **FIXED — benchmark evidence and reproducibility.**  
   All 18 traces, timings, scorer, score output, and usage reconciliation are present. Regeneration exactly matches both checked-in JSON results.

4. **FIXED — unsupported X-call billing oracle.**  
   The executable `_grok_cost()` assertion was removed. `usage-reconciliation.json` now labels `$0.05` as a conditional discrepancy and explicitly leaves its cause unresolved without account billing truth.

5. **FIXED — long-context fallback.**  
   `_grok_cost()` remains short-tier-only and documents why ACP turn aggregates cannot safely select a per-request tier for tool loops. Runtime `costUsdTicks` remains authoritative.

6. **FIXED — scoring/fabrication scope.**  
   `score_bench.py` derives X-tool credit from completed native `tool_call_update` events, not `tools_used`. It sets `fabrication_check_complete: false`, and that flag is required for deletion, so 4.5 cannot be removed based on the incomplete hidden-body check.

7. **FIXED — laptop read-only conclusion.**  
   `laptop-config-sanitized.md` lists the exact read-only command scope, sanitized findings, settings intentionally not copied, and confirms that no laptop-only value required transfer.

## New findings

No new blocking bugs found.

Focused verification:

```text
uv run pytest -q tests/test_backend_grok.py
82 passed in 4.59s
```

Both regenerated evidence files matched exactly:

```text
diff -u docs/tasks/251/score.json <(uv run python docs/tasks/251/score_bench.py)
diff -u docs/tasks/251/usage-reconciliation.json <(uv run python docs/tasks/251/reconcile_usage.py)
```

Auditable verbatim line from the current bundle:

> `Semantic discovery считать exploratory candidate list, не доказательством «того самого поста» или тренда`

## Verdict

**APPROVED — Round 2.** All prior blocking findings are closed.
