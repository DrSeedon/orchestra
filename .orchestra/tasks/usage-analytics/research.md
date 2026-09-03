# Usage Analytics v2 — research

Дата снимка: 2026-07-25 14:52 KRAT. Фаза 1: исследование и интерактивный прототип; production-код не менялся.

## Вопрос

**Контекст:** текущая модалка показывает общую virtual cost, Claude rate limits, один совмещённый график cost/cache и таблицу агентов.

**Изменение под проверкой:** превратить её в главный observability control room Orchestra с равноправными Claude/Codex capacity pools, routing signal, unit economics, cache/model mix, agent drill-down и reliability gaps.

**Baseline:** текущие четыре endpoint-запроса и узкая `max-w-3xl` модалка [1][2].

**Критерий:** каждый показанный показатель либо уже возвращается API, либо воспроизводимо вычисляется из существующей SQLite; недостающая телеметрия явно помечена, а макет остаётся читаемым при почти-fullscreen размере.

## Гипотезы

1. **Capacity-first экран полезнее cost-first экрана, потому что Claude и Codex имеют независимые пулы и выбор runtime — ежедневное операционное решение.** Фальсификатор: Codex limits не сохраняются исторически или нельзя сопоставить их с Claude. Результат: подтверждено — общий provider contract и snapshot history уже есть [3][4].
2. **Одного нового агрегирующего endpoint достаточно для всей панели.** Фальсификатор: часть показателей не собирается вообще. Результат: частично опровергнуто — `tool_errors` имеет schema/helper, но runtime его не вызывает; точный cold-start tax также не восстановить [5][6].
3. **Cost per completed task можно показывать как точный основной KPI.** Фальсификатор: слабая или неоднозначная связь task↔session. Результат: опровергнуто как безусловный KPI — за 7 дней связаны 12 из 17 завершённых задач; lifetime 43 из 237. Метрику можно показывать только вместе с coverage.
4. **Cache efficiency уже можно честно сравнить между провайдерами.** Фальсификатор: текущая агрегация применяет один TTL ко всем runtime. Результат: текущий endpoint неверен для сравнения: SQL использует 3600 секунд для всех, хотя registry задаёт Claude=3600, Codex≈1800 [7][8]. Существующих timestamps достаточно, чтобы исправить агрегацию; денежный cache tax потребует per-turn token telemetry.

## Измерения SQLite

База открывалась только `sqlite3 -readonly` с `PRAGMA query_only=ON`.

| Измерение | Результат | Уровень доказательства |
|---|---:|---|
| База | 147 MB; 297 sessions; 27,722 logs | прямое измерение |
| Capacity history | 7,029 snapshots, 2026-05-30 → 2026-07-25 | прямое измерение |
| Последний snapshot | Claude 5h 68%, Claude 7d 45%, Codex 7d 33%, Spark 7d 1% | прямое измерение |
| Lifetime virtual cost | $10,689.92; 23,217 session turns; 25,775 tool calls | прямое измерение |
| Retained turn events | 719, только 2026-07-17 → 2026-07-25 | прямое измерение |
| Последние 7 дней | $1,156.25 / 716 agent-turns: Claude $703.56 / 534, Codex $452.69 / 182 | прямое измерение |
| Cache gap heuristic, 7d | Claude 86.6% / 68 cold из 507 сравнимых; Codex 71.4% / 38 cold из 133 | прямое измерение, TTL из registry |
| Completed tasks, 7d | 17; к session cost привязаны 12 (71%); $21.62 на связанную задачу | прямое измерение, coverage обязателен |
| Tool errors | 0 строк, но `tool_error_add()` не вызывается нигде | прямое измерение + чтение call sites |
| Native Claude subagents, 7d | 221 completed, 19 failed, 5 running, 1 stopped | прямое измерение |
| Voice, lifetime | 12 записей, 193.2 секунды, $0.0167 | прямое измерение |

Raw-проверки, на которых построен прототип:

```text
latest usage snapshot:
Claude 5h 68% · Claude 7d 45% · Codex 7d 33% · Spark 7d 1%

7d provider totals:
Claude 534 turns · $703.56 · $1.32/turn
Codex  182 turns · $452.69 · $2.49/turn

7d cache, provider TTL:
Claude comparable=507 cold=68 hit=86.6%
Codex  comparable=133 cold=38 hit=71.4%

task linkage:
12/17 completed tasks linked in 7d
43/237 completed tasks linked lifetime
```

## Концепции

Вероятность — грубая первоначальная оценка того, что концепция **сама по себе** закроет задачу.

1. **Provider Capacity Cockpit — 0.38.** Два равных capacity card, ETA/headroom и прямой routing signal. Сильный ежедневный экран, но слабый drill-down.
2. **FinOps Scorecard — 0.22.** Virtual cost, cost/turn, cost/task, model mix. Хорош для ретро, но подписочная quota важнее виртуальных долларов.
3. **Agent Profiler — 0.18.** Рейтинг, аномалии, drill-down по агенту. Хорошо ищет пожирателей контекста, но не отвечает «куда роутить сейчас».
4. **Reliability NOC — 0.14.** Tool errors, subagents, voice, task coverage. Самая полезная долгосрочно, но текущая instrumentation неполна.
5. **Tabbed Operations Control Room — 0.08.** Capacity-first landing плюс отдельные Agents / Efficiency / Reliability. Более сложный tail-вариант, зато единственный закрывает «главную панель наблюдаемости» без превращения первого экрана в свалку.

**Выбран вариант 5:** почти-fullscreen command center. Landing screen остаётся capacity-first: равноправные Claude/Codex cards, routing decision, period KPIs и provider spend chart. Детали вынесены в три вкладки. Это сохраняет быстрый ответ за 5 секунд и даёт глубину по клику.

## Что уже доступно

| Блок | Источник сейчас | Состояние |
|---|---|---|
| Claude 5h/7d и Codex/Spark windows | `/api/usage` | готово |
| История capacity обоих провайдеров | `/api/usage/history`, `usage_snapshots.provider_usage` | готово |
| Lifetime agents/cost/cache-cost | `/api/usage.orchestra` и `/api/stats` | готово, но значения имеют разные semantics |
| Daily cost/turns | `/api/usage/daily` | готово только общим итогом |
| Daily agents/model/cost | `/api/usage/daily/agents` | готово, без provider/cache/error drill-down |
| Session tokens/tool calls/cache totals | `sessions` | готово lifetime |
| Native Claude subagents | `subagents` | готово в DB, нет fleet endpoint |
| Voice cost | `voice_costs` | `/api/usage` отдаёт только lifetime total |
| Tasks/completion | `tm_tasks`, `sessions.task_id` | доступно, linkage неполный |

## Что требует backend

1. **Provider-aware daily aggregation.** Добавить `provider`, `model`, provider TTL и retention metadata. Текущий 1h cache SQL смешивает runtimes.
2. **Один analytics payload.** Новый `/api/usage/analytics?days=` либо расширение двух daily endpoints: summary, daily provider series, models, agents, task coverage, subagent/voice rollups. Один запрос уменьшит frontend chatter с четырёх запросов и согласует snapshot time.
3. **Turn event вместо парсинга строки.** Сохранять структурированно runtime/model, turn cost, context cost, input/output/cache tokens, tool calls. Это даст точный model history, cache tax и устойчивость к изменению текста лога.
4. **Tool-error instrumentation.** Вызывать существующий `tool_error_add()` в Claude/Codex tool-result paths; иначе показатель нельзя показывать числом.
5. **Нормализованная task linkage.** Хранить внутренний `tm_tasks.id` или `(project_id, par_number)`, а не неоднозначный строковый `sessions.task_id`; UI всегда показывает coverage.
6. **Unified delegation telemetry.** `subagents` описывает Claude SDK subagents, но Codex делегирует через Orchestra workers. Их нельзя сравнивать одним числом без общего contract.

## Оценка трудозатрат для production v2

| Блок | Оценка | Комментарий |
|---|---:|---|
| Fullscreen shell, tabs, responsive, period/provider filters | 1.0–1.5 дня | `dashboard.html`, `app.js`/новый leaf module, CSS |
| Provider-aware analytics endpoint + SQL tests | 1.5–2.0 дня | cost/cache/model/retention |
| Agent drill-down + anomaly rules | 0.75–1.25 дня | сначала cost/turn + median, без магического anomaly score |
| Task, subagent, voice rollups + coverage | 0.75–1.0 дня | DB уже содержит основу |
| Structured turn events + exact cache tax | 1.5–2.5 дня | отдельная миграция; можно отложить |
| Tool-error collector | 0.75–1.25 дня | оба runtime + tests |
| UI/API regression tests | 0.75–1.0 дня | pytest + Playwright |

**Реализуемый сильный v2 без exact cache tax:** 4.5–7 инженерных дней.
**Полный observability contract со structured turns и tool errors:** 6.5–10 дней.

## Риски и edge cases

- `/api/usage` и history отключены при `is_auth_enabled()`, поэтому VPS/auth deployment требует отдельного решения доступа [3].
- «30 дней» и «всё время» по turn logs сейчас фактически покрывают только 8.7 дня; UI обязан показывать retention badge, а не молча выдавать неполный период.
- `sessions.model` — текущее значение. Смена модели переатрибутирует старые turn logs в historical model mix.
- Snapshot `total_cost_usd` считает загруженные manager sessions, а `/api/usage.orchestra` и `/api/stats` — DB sessions; эти totals нельзя смешивать без явной semantic label.
- Codex может вернуть только primary 7d window; UI не должен придумывать отсутствующий 5h window.
- Spark — отдельный limit id, но routing policy разрешает его только для коротких leaf-задач; низкая utilization не означает «отправить туда всё».
- Первые turns нельзя классифицировать как hit/cold по gap heuristic. Они должны быть `unknown`, а не автоматически cold.
- Нулевая таблица `tool_errors` сейчас означает «нет collector», а не «ошибок нет».

## Уверенность

- **CONFIRMED:** capacity обоих провайдеров и их история доступны — primary code + 7,029 measured snapshots.
- **CONFIRMED:** текущая cache aggregation неверно применяет 1h ко всем runtime — primary code в endpoint и registry.
- **CONFIRMED:** provider cost, model mix, anomaly-by-cost/turn и task coverage воспроизводимы из текущей DB — прямые SQL measurements.
- **CONFIRMED:** exact cache tax и достоверные tool-error counts сейчас невозможны — отсутствуют per-turn fields/call sites.
- **LIKELY:** capacity-first multi-tab control room лучше отвечает ежедневному workflow, чем один длинный financial dashboard — дизайн-вывод, проверяется пользовательским гейтом по HTML-прототипу.

## Контраргументы

- Один экран с четырьмя вкладками дороже текущей модалки и потребует дисциплины информационной архитектуры. Поэтому landing ограничен routing/capacity/spend, а остальные разрезы не дублируются.
- Virtual cost может стимулировать неверную оптимизацию подписочного продукта. Поэтому `$` всегда подписан как API-equivalent, а capacity pools визуально стоят выше расходов.
- Cost/turn аномалия не доказывает неэффективность: дорогая исследовательская задача может быть нормальной. В прототипе это только сигнал для drill-down, не автоматический verdict.
- Gap-based cache hit — proxy, а не подтверждённый provider cache event. UI прямо показывает метод и не переводит его в доллары.

## Артефакт и проверка

- Интерактивная демка: `docs/artifacts/usage-analytics-v2.html`
- Встроены реальные значения read-only snapshot и 7d aggregates.
- Работают tabs, periods, provider chart filter, agent filters/drill-down, Escape/close/reopen.
- Playwright: 12 interaction assertions, 0 console errors; light/dark responsive CSS предусмотрен.
- Production JS/Python/HTML не изменялись.

## Codex second opinion

Adversarial review перепроверил research, HTML и SQLite-расчёты; отдельно подтверждена медиана `$1.7346` для агентов с двумя и более turns. Verdict: **Approve**, blocking/suggestion/question — 0. Полный результат: `docs/tasks/usage-analytics/codex-review-research.md`.

## Источники

1. **Primary:** `app/static/js/app.js:5170-5331` — текущая загрузка и rendering аналитики.
2. **Primary:** `app/templates/dashboard.html:180-191` — текущая `max-w-3xl` модалка.
3. **Primary:** `app/routes/system.py:468-549, 676-803` — Codex normalization, provider history contract, `/api/usage`, auth behavior.
4. **Primary:** `app/db.py:1299-1372` — snapshot storage и history interpolation.
5. **Primary:** `app/db.py:254-260, 1183-1223` + repository-wide call-site search — tool errors schema/helper без runtime callers.
6. **Primary:** `app/db.py:46-103, 243-252, 869-912` — sessions/logs/subagents/voice/lifetime aggregates.
7. **Primary:** `app/routes/system.py:806-870` — current daily and per-agent SQL, общий 3600s cache threshold.
8. **Primary:** `app/models.py:117-127` — runtime cache policy: Claude 3600s, Codex ≈1800s.
9. **Direct measurement:** `/mnt/data/Projects/Python/orchestra/data/orchestra.db`, `sqlite3 -readonly`, queries executed 2026-07-25; raw values preserved above.
