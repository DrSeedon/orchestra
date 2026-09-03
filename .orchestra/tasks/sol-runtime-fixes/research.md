# Research — честный контекст Sol и остановка retry на исчерпанной подписке

Дата проверки: 2026-07-16.

## Вопрос

- **Контекст:** Orchestra запускает GPT-5.6 Sol через ChatGPT-auth Codex CLI и показывает `context_pct/context_tokens`; Claude backend автоматически повторяет временные `rate_limit` ошибки.
- **Изменение под проверкой:** заменить ложную метрику окна Sol на измерение текущего контекста Codex и не повторять запросы при терминальных subscription-limit сообщениях.
- **Базовая линия:** `CodexBackend` делит агрегированный `turn.completed.usage.input_tokens` на hardcode `997500`; `Session` распознаёт только `session limit` и сбрасывает retry-счётчик на каждом `turn_end`.
- **Измеримый результат:** dashboard совпадает с `token_count.last_token_usage/model_context_window`; `monthly spend limit` создаёт ноль retry, а временный `rate_limit` — не более трёх.

## Гипотезы и опровержение

### H1 — `761k/998k` не является занятым окном

Причина: Codex runtime отдельно хранит `last_token_usage` (текущий model call) и `total_token_usage` (накопительный расход), а `codex exec --json` экспортирует только агрегированный usage завершённого turn.

**Опровергнет:** rollout текущей сессии сообщит окно около 997500 и текущий `last_input` около 760838.

### H2 — доступный runtime-бюджет текущего ChatGPT-auth Sol равен 258400

Причина: свежий server-fed model cache и живые rollout-сессии сообщают 272000 raw × 95% = 258400 effective.

**Опровергнет:** свежий cache или rollout текущей сессии сообщит 1050000/997500.

### H3 — месячная квота зацикливается из-за неполного matcher и сброса retry-счётчика

Причина: код знает только `session limit`; DB показывает `monthly spend limit`, после которого каждый цикл снова логирует `(1/3)`.

**Опровергнет:** код содержит terminal matcher для monthly quota либо последовательность DB достигает `(2/3)` и `(3/3)`.

## Измерения

### M1 — текущая Sol-сессия

Строка `sessions` в `data/orchestra.db`:

```text
session_id=019f699a-0125-7e20-947f-3f3b299e8e5b
context_pct=76
context_tokens=760838
```

Последний `token_count` в rollout этой же сессии:

```json
{"last_input":95489,"last_cached":92928,"total_input":2042411,"window":258400}
```

На момент измерения реальная доля текущего model call: `95489 / 258400 = 36.95%`. Dashboard показывал `760838 / 997500 = 76.27%`. Число `760838` может быть реальным агрегированным расходом turn, но не может быть одновременно занятым окном размером 258400.

### M2 — отдельный минимальный `codex exec --json`

Команда:

```text
codex exec --json --sandbox read-only -m gpt-5.6-sol 'Reply exactly: SOL_CONTEXT_PROBE_OK'
```

Stdout завершился с exit 0 и содержал:

```json
{"type":"thread.started","thread_id":"019f69a2-4ba8-73b2-9122-ec6b3b012a76"}
{"type":"turn.completed","usage":{"input_tokens":25381,"cached_input_tokens":9984,"output_tokens":9,"reasoning_output_tokens":0}}
```

Stdout не содержит `model_context_window`, `last_token_usage` или `token_count`. Rollout того же thread содержит:

```json
{"last_input":25381,"total_input":25381,"window":258400,"cache":9984}
```

В простом одношаговом turn агрегат совпадает с current usage; в многошаговом turn такое совпадение контрактом stdout не гарантируется.

### M3 — повторяемые terminal retry

В DB-логах `Orchestra-orchestrator` найдено не менее восьми последовательностей:

```text
You've hit your monthly spend limit · raise it at claude.ai/settings/usage
⏳ rate limit (Anthropic сервер) — повтор через 30s (1/3)
[system] Retrying after rate limit. Continue where you left off.
```

Счётчик всегда остаётся `(1/3)`. Код подтверждает два механизма:

- `app/session.py:575-577` распознаёт только `session limit`/`hit your session`, но не `monthly spend limit`;
- `app/session_turns.py:138-140` сбрасывает `_rate_limit_retries` на каждом обычном `turn_end`, поэтому следующий failed turn снова начинается с нуля.

## Findings

### 1. Миллион токенов доступен модели в API, но не текущей Codex CLI-сессии

Прямая API-поверхность Sol заявляет 1.05M, однако проверенный ChatGPT Plus/Codex CLI 0.144.3 runtime объявляет 258400 effective. Физический transport limit запросом >258400 не проверялся; для accounting/compaction Orchestra источником истины является runtime window 258400.

**Уверенность: CONFIRMED** — свежий model cache, несколько живых rollout и текущая сессия дают одно значение.

### 2. `76% (761k/998k)` — ложная метрика занятости окна

`turn.completed.usage.input_tokens` — usage агрегат завершённого turn, а не гарантированное число токенов последнего model context. Текущий rollout напрямую показывает 95489/258400, тогда как DB хранит 760838/997500.

**Уверенность: CONFIRMED** — одновременное прямое измерение DB и rollout одной session id.

`cache 89%` остаётся полезной метрикой повторно использованного input, но это не доля свободного/занятого окна.

**Уверенность: CONFIRMED** — поле вычисляется из cached input / input usage в `backend_codex.py`.

### 3. Честную метрику нельзя получить только из публичного stdout `codex exec --json`

Публичный stream не экспортирует runtime window/current usage. Точное значение доступно в локальном rollout `token_count`; если rollout недоступен или формат изменился, fail-soft поведение должно скрывать процент, а не показывать агрегированный usage как context.

**Уверенность: CONFIRMED для CLI 0.144.3; LIKELY для будущих версий** — прямой probe плюс локальный rollout, но формат rollout внутренний.

### 4. `monthly spend limit` ошибочно считается временным server rate limit

Сообщение не проходит terminal matcher, а retry budget сбрасывается между неуспешными turns. Это создаёт неограниченный цикл `(1/3)` вместо трёх попыток.

**Уверенность: CONFIRMED** — код и восемь+ повторов в DB.

## Контрдоказательства и ограничения

- Официальная API-карточка 1.05M подтверждает способность модели через другую поверхность; она не доказывает окно ChatGPT-auth Codex CLI.
- Rollout — внутренний файл Codex. Исправление должно иметь явный fallback и тест на отсутствие/битый формат.
- `last_token_usage.input_tokens` является контекстом последнего model call; между calls во время активного turn значение меняется. Dashboard после turn должен показывать последний зафиксированный call.
- Точное множество terminal subscription сообщений Anthropic не задокументировано в коде; в scope входят измеренные `session limit` и `monthly spend limit`, без широкого matcher по слову `limit`.

## Затронутые файлы и риски

- `app/backend_codex.py` — runtime context extraction, правильный max, fail-soft fallback; существующий hardcode и `turn.completed` mapping.
- `tests/test_backend_codex.py` — simple/multi-call usage, rollout missing/corrupt, Sol 258400.
- `app/session.py` — terminal quota classifier и сохранение retry budget для внутренних повторов.
- `app/session_turns.py` — преждевременный reset `_rate_limit_retries`.
- тесты Session/TurnManager — monthly quota без retry; transient retry 1/3→2/3→3/3→stop; новый пользовательский turn сбрасывает budget.

Главный риск — привязка к внутреннему rollout Codex. Без успешно разобранного `token_count` безопаснее вернуть `context_pct=0`/unknown, чем повторять заведомо ложную цифру.

## Adversarial review

`codex_review` проверил документ против кода и измерений и вернул:

```text
The only change is a research document. Its claims are consistent with the referenced code paths and recorded measurements, and it introduces no runtime or test regressions.
```

Blocking findings отсутствуют. Полный structured format не сохранился: первый review был оборван рестартом Orchestra, а повторный снова записал только финальный `agent_message`. Платформенный дефект зарегистрирован через `report_bug`; короткий проверяемый verdict сохранён в `codex-review-research.md`.

## Baseline tests

До реализации выполнено:

```text
tests/test_backend_codex.py: 10 passed
tests/test_backend_codex.py + tests/test_session.py: 56 passed, 3 failed
```

Три существующих failure в `tests/test_session.py` вызваны `sqlite3.OperationalError: no such table: bg_jobs` в чистом worktree и одним зависимым async timing assertion. Они появились до изменений runtime-кода; Phase 3 должна добавить изолированные unit-тесты с замоканными persistence/background paths и не принимать эти baseline failures за регрессию.

## Источники доказательств

1. `docs/tasks/sol-pilot/research.md` — model cache и три live rollout (прямые измерения).
2. `data/orchestra.db`, session `019f699a-0125-7e20-947f-3f3b299e8e5b` — текущая dashboard-метрика и retry logs (прямые измерения, 2026-07-16).
3. `~/.codex/sessions/2026/07/16/rollout-2026-07-16T13-25-28-019f699a-0125-7e20-947f-3f3b299e8e5b.jsonl` — current/total/window одной сессии (прямое измерение).
4. `~/.codex/sessions/2026/07/16/rollout-2026-07-16T13-34-31-019f69a2-4ba8-73b2-9122-ec6b3b012a76.jsonl` — отдельный probe (прямое измерение).
5. `app/backend_codex.py`, `app/session.py`, `app/session_turns.py` — фактические contracts и bug paths (первичный source code).
