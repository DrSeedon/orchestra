## Summary

Core resolution order and scalar backward compatibility work, and the focused tests pass: 24/24. Existing sessions remain unaffected because only the new-session spawn path resolves the manifest map; persisted `sessions.effort` behavior is unchanged.

Pydantic rejects integer and boolean effort values rather than coercing them to strings.

## Findings

- suggestion — `app/pipeline.py:263` — `grok` has the same ambiguity as `codex`: both are runtime IDs and aliases (`grok → grok-4.5`). Runtime-first validation therefore makes `{grok: high}` apply to every future Grok-runtime model, not specifically `grok-4.5`. `claude` and `opencode` are not currently aliases. → Treat runtime names as explicitly reserved keys and document that aliases colliding with them cannot select a model; add a `grok` regression test. Exact `grok-4.5` remains available for model-specific selection.

- suggestion — `app/pipeline.py:265` — Unknown model keys are destructively removed during cached manifest validation. If `load_pipeline()` runs before `fetch_models_from_proxy()` registers a proxy model, that model’s effort entry is permanently absent from the cached `RoleSpec`, even after the registry gains the model. → Preserve unknown string keys for spawn-time exact matching, or clear/reload the pipeline cache after every model-registry refresh. Preserving keys also avoids coupling manifest correctness to startup ordering.

- suggestion — `app/pipeline.py:256` — Dropping misspelled keys or levels and falling through to `default`/`None` hides configuration errors in a shared runtime; warnings may never be noticed, while every subsequent worker silently receives the wrong effort. → Reject invalid entries when loading the manifest, or at minimum mark the pipeline invalid instead of mutating the configured map. If fail-open availability is mandatory, surface the degradation through the pipeline validation result rather than logs alone.

## Verdict

Changes requested before approval. Spawn-time selection and scalar compatibility are correct, but dynamic registry timing can silently discard valid per-model configuration, and ambiguous/runtime or invalid keys need a clearer, observable contract.


> ⚠️ **Раунд 2 восстановлен из транскрипта джоба, а не записан штатно.** Обёртка
> `codex_review_artifact.py` упала с `exit 2` (`the following arguments are required:
> --usage-event-id, --usage-session-id, --usage-model`) — причина в #217: `d9d770e4`
> добавил обязательные аргументы, а живой MCP-процесс воркера поднят до мержа и зовёт
> скрипт по-старому. Само ревью отработало: 572 858 input / 3 700 output токенов.
> Текст ниже — полный `agent_message` из `/tmp/codex_review_impl-effort-model_codex-review-impl.jsonl`,
> дословно. Первая ручная реконструкция (по хвосту в 3000 символов) была неполной и заменена этой.

## Round 2

## Summary

Round 1 status:

- Unknown model keys / dynamic registry timing: FIXED.
- `grok` runtime/alias ambiguity: FIXED and tested.
- Silent dropping of invalid effort levels: STILL BROKEN.
- Cache-contract regression: FIXED by deliberately changing and testing the contract.

Focused tests pass.

The running-turn claim is correct: every `RUNNING` branch returns before `_apply_manifest_effort()`. The lifecycle lock serializes session operations, but it does not make concurrent filesystem edits deterministic because manifest writers do not share that lock.

## Findings

- suggestion — `app/session.py:1158` — NEW BUG: `desired is None` is treated as “keep the DB value,” so removing an effort mapping cannot clear an existing effort. This contradicts the stated comparison contract and prevents a bulk manifest edit from changing agents back to backend-default effort. → Distinguish “manifest/role could not be read” from a successfully resolved `None`; after a successful read, apply and persist `None` when it differs. If inheritance of legacy DB values is intentional, restrict it explicitly to legacy sessions rather than all roles without a match.

- suggestion — `app/session.py:1161` — NEW BUG: state is committed before backend disconnection succeeds. If `backend.disconnect()` raises, `self.effort` and potentially the DB contain the new value while `_backend` still references a backend built with the old effort. On later turns `desired == self.effort`, so the disconnect is never retried and the agent can continue indefinitely at the wrong effort. → Disconnect first and commit the new effort only after success, or roll back `self.effort` on failure so the next turn retries.

- suggestion — `app/pipeline.py:386` — NEW BUG: `stat()` and `read_text()` are separate operations with no stable-snapshot check. An in-place bulk edit can therefore expose partial YAML, and the lifecycle lock provides no protection against it. `_apply_manifest_effort()` catches this, but `get_role_icons()` and worktree preparation do not generally catch parse/validation failures, widening a brief edit into unrelated request or spawn failures. → Require atomic replacement for manifest updates, or re-stat after reading and retry when `(mtime_ns, size)` changed during the read.

- suggestion — `app/pipeline.py:256` — STILL BROKEN: an invalid level is deleted, potentially causing fallback to a valid but unintended `default`. The availability argument explains why one bad edit should not replace the last working configuration, but silent mutation is not the only alternative. → Retain the last successfully parsed manifest when a changed file is invalid and expose the validation error; this preserves availability without accepting a typo as different routing.

## Verdict

Changes requested. Running turns are protected and the cache shim is compatible with existing `cache_clear()`/`cache_info()` callers, but clearing effort and disconnect failure currently leave persistent live/backend disagreement. The manifest read also needs an atomic-update contract or stable-read protection.

### Разбор

| находка | решение | что сделано |
|---|---|---|
| `NEW BUG`: значение фиксируется до успешного дисконнекта | **ACK, настоящий баг** | Порядок инвертирован: `_disconnect_backend()` ПЕРВЫМ, фиксация после. Сбой оставляет расхождение живым, следующий ход повторит. Тест `test_failed_disconnect_leaves_change_pending`; мутация «вернуть старый порядок» — красная |
| `NEW BUG`: `stat()`+`read_text()` не атомарны, возможен торн-рид | **ACK по сути, другое лекарство** | Проверено: `pipeline.yaml` в `app/` никем не пишется программно, писателя нет вообще. Требование «писать через `os.replace()`» записано в отчёт §8 и уходит в `CLAUDE.md`. Re-stat с ретраем не делаю: при атомарной записи торн-рида не существует, ретрай — код ради случая, закрываемого дисциплиной писателя |
| `desired is None` → наследуем значение из БД вместо очистки | **DISAGREE, обосновано** | Это явное требование постановки: «нет значения для этой модели → остаёмся на текущем». Очистка в `None` означала бы, что роль без эффорта СБРАСЫВАЕТ живым агентам ступень на дефолт рантайма — то есть битая/неполная карта тихо понижает всех. Ограничение «только для legacy» не помогает: отличить «роль намеренно без эффорта» от «ключ для этой модели забыли» в манифесте нельзя |
| `STILL BROKEN`: неизвестный УРОВЕНЬ отбрасывается | **DISAGREE, позиция прежняя** | Предложенное лекарство — «держать последний удачно разобранный манифест» — это второй владелец значения конфига и тихая работа на устаревшей конфигурации; ровно то, от чего отказались, отвергнув отдельный тул. Идея «показывать деградацию в результате валидации» принята как верная и отложена сознательно (отчёт §9) |
