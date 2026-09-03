# #251 — итоговый отчёт

Дата: 2026-08-13.

## Итог

- Grok CLI 1.0.3 и подписка работают; прямой каталог показывает 4.6 default и 4.5.
- Известные product analytics и external OTEL закрыты проверкой с положительным wire-control;
  trace upload, feedback, indexing, Mixpanel и Sentry выключены config + hard env.
- На 18 парных X-ходах `grok-4.5` лучше измеренного 4.6: 9.33 против 8.67 на однозначных A+B,
  exact permalink 4/6 против 2/6, медиана 34.616 s против 44.977 s. Порог удаления 4.5 не
  пройден; 4.5 и aliases остаются.
- `grok-4.6` зарегистрирован как явный Orchestra route, но не активирован. Spawn и первый
  завершённый Orchestra-ход остаются post-restart probe.
- Учёт расхода откалиброван: доказано только условное расхождение $0.05 на reported $8.23
  (0.6%) в 1/18 traces. Общий undercount не заявляется; exact account billing недоступен.

Полное обоснование и confidence: `research.md`. Raw traces и воспроизводимые расчёты:
`raw/`, `score_bench.py`, `score.json`, `reconcile_usage.py`, `usage-reconciliation.json`.

## Изменения

- `app/models.py` — `grok-4.6` в route/provider/context registries; только явный alias
  `grok4.6`; `grok` и `grok-build` остаются 4.5.
- `app/backend_grok.py` — model card 4.6; managed TOML закрывает известные telemetry channels;
  `_build_env()` hard-pins их после hostile host/MCP env. Runtime `costUsdTicks` остаётся
  источником стоимости; short-tier fallback намеренно не угадывает mixed long-context turns.
- `tests/test_backend_grok.py` — route/provider/context/cache-card и hostile telemetry env.
- `docs/grok-field-guide.md` — живой 4.6, 200k tier, account billing limits и границы fallback.
- `docs/tasks/251/` — prereg, prompts, runner, 18 traces, scoring/reconciliation, telemetry wire
  oracle, laptop read-only artifact, research и Codex review.
- `/home/kesha/.grok/config.toml` (вне Git) — user-level telemetry/feedback/indexing/trace/
  Mixpanel/external OTEL off; действует уже сейчас для прямого CLI.

## Проверки

```text
uv run pytest -q tests/test_backend_grok.py
82 passed in 5.01s

python3 docs/tasks/251/score_bench.py > /tmp/score-251.json
cmp /tmp/score-251.json docs/tasks/251/score.json
exit 0

python3 docs/tasks/251/reconcile_usage.py > /tmp/reconcile-251.json
cmp /tmp/reconcile-251.json docs/tasks/251/usage-reconciliation.json
exit 0

uv run python docs/tasks/251/telemetry_probe.py
positive: /events x19, /v1/logs x2, /v1/metrics x1; rc=0
production: zero collector requests; rc=0
```

`bash -n` и `py_compile` прошли. Shape-scan всей `docs/tasks/251/` по OAuth/API/GitHub/
Bearer/private-key паттернам — ноль совпадений. Полный suite не запускался: глобальный lock.

Codex Round 1 запросил изменения; приняты все семь замечаний. Round 2:
`APPROVED — All prior blocking findings are closed`, с проверкой `82 passed` и побайтным
воспроизведением обоих JSON. Артефакт: `codex-review-research.md`.

## Pre-mortem следующего потребителя

| Сценарий | Наблюдаемый симптом | Проверка/страховка |
|---|---|---|
| managed TOML не парсится | Grok падает до первого хода | production-arm реального telemetry probe завершён rc=0 |
| hostile env включает экспорт | collector получает `/events`/OTEL | positive получает 22 запроса, production — 0 |
| route 4.6 попал в чужой runtime/provider | spawn выберет не Grok или расход уйдёт не туда | focused assertions для backend/provider/context |
| alias молча переключил всех на 4.6 | `model="grok"` меняет поведение до решения | тест фиксирует alias `grok -> grok-4.5` |
| dynamic catalog снова отключён | `grok models` показывает fallback только 4.5 | не ставить `remote_fetch=false`; live catalog перед spawn |
| turn aggregate принят за provider bill | dashboard получает ложную точность на tool-loop | research фиксирует $0.05 как conditional и exact billing как UNKNOWN |
| Python-код смержен, но не загружен | `/api/models`/spawn не видит 4.6 | общий restart, затем отдельный Orchestra spawn + первый turn |

## Breaking / TODO

Breaking: нет. Модель добавлена явным значением; существующие aliases не менялись.

После общего рестарта:

1. проверить `/api/models` и `spawn_worker(model="grok-4.6")`;
2. зафиксировать session id, создание сессии и первый завершённый ход;
3. при MCP identity mismatch записать только различающиеся поля tuple без значений/секретов;
4. не удалять 4.5 и не включать Grok в общую маршрутизацию отдельным решением.
