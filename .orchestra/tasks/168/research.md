# #168 — centralized weekly quota hard gate: research (Phase 1)

Дата проверки: **2026-08-08**, ветка `task-168/feat-quota-guard`, база `f4d054a`.
Исследование выполнено без запуска Claude/Opus: только чтение кода, read-only SQLite,
чистые функции, тесты с mock backend и второе мнение Codex/Sol.

## Вопрос

- **Контекст.** Orchestra принимает сообщения из MCP, HTTP/dashboard, Telegram, background jobs
  и внутренних lifecycle-механизмов. Они могут начать ход уже существующего worker либо направить
  сообщение в уже идущий ход. Top-level/sub-orchestrators используют тот же session layer.
- **Изменение под проверкой.** Единый admission-control для **нового worker turn**: недельное
  использование quota bucket модели `>=95%` (remaining `<=5%`) запрещает старт; уже идущий ход,
  stop и перевод на доступный provider остаются рабочими; orchestrator turns не блокируются.
- **Baseline.** #154 поставил Codex-only MCP-префлайты при `100%` на `spawn_worker`,
  `change_worker_model`, `codex_review`, сознательно оставив delivery-path без гейта [S8].
- **Проверяемый исход.** Ни один серверный путь не вызывает start-side-effect backend для idle/
  waiting worker на закрытом weekly bucket; active-turn steering проходит; одинаковые `94.9/95.0`
  дают одинаковый результат для Claude и Codex; ошибка называет закрытый и доступный bucket.

## Гипотезы и фальсификаторы

| # | Гипотеза | Что доказало бы обратное | Итог |
|---|---|---|---|
| H1 | Все новые worker turns сходятся в `AgentSession.send`, поэтому одной проверки там достаточно | Прямой `backend.send`/provider process вне `send`, который начинает новый ход | **REFUTED:** `_flush_pending`, Claude compaction и `codex_review` обходят `send` [S3][S5] |
| H2 | `SessionManager.send` — достаточный общий лист | Внутренний retry/flush обходит manager либо manager не отличает steering от нового turn атомарно | **REFUTED:** retries зовут `self.send`, flush — backend напрямую; решение new-vs-active принимается только под `_lifecycle_lock` внутри session [S4][S5] |
| H3 | Существующий `provider_readiness` можно переиспользовать без изменения семантики | Он учитывает не только weekly либо порог не 95 | **REFUTED:** Claude требует одновременно 5h+7d, все providers закрываются только при `>=100`; на синтетических `95` оба отвечают `available` [S2][M2] |
| H4 | Нормализованных данных достаточно для одинакового weekly-решения Claude/Codex | Weekly окно нельзя надёжно отличить от короткого окна или quota buckets слиты | **CONFIRMED:** contract несёт `window_minutes=10080`; Claude, Codex и Spark разнесены по bucket [S1][M1] |
| H5 | Глубокий гейт обязательно потеряет уведомления background jobs | Ошибку невозможно вернуть user/orchestrator без запуска закрытого worker | **REFUTED для основных путей:** HTTP/TG/bg handlers уже ловят delivery failure, а сообщения orchestrator проходят по требуемому exemption; queued flush всё ещё требует явной диагностики [S6] |

## Findings

### F1. Фактическая модель quota data — CONFIRMED

**Evidence tier 1 (живой SQLite snapshot) + tier 2 (код нормализации).**

`_provider_usage_snapshot()` приводит provider-specific ответы к одному контракту:

```text
provider_id -> {label, windows:[{id, label, utilization, window_minutes, resets_at}]}
```

- Claude: raw keys `five_hour` и `seven_day`; weekly = `id=seven_day`,
  `window_minutes=10080` [S1].
- Codex: `rateLimitsByLimitId.codex`, окна `primary`/`secondary`; длительность приходит как
  `windowDurationMins`. Все обычные Codex-модели делят bucket `codex` [S1][S7].
- Spark: отдельный upstream limit id `codex_bengalfox`, нормализуется в отдельный bucket
  `codex_spark`; гейт по runtime `codex` был бы ложным [S1][S2].
- Grok существует в model registry, но #168 его не включает. Текущий `_provider_for_model()`
  по fallback относит любую не-Claude и не-Spark модель к `codex`; новый gate не должен
  переиспользовать этот fallback для Grok [S2][S7].

Последний живой snapshot (`usage_snapshots`, `2026-08-08T07:46:29.009079+00:00`):

```text
anthropic  five_hour  3.0% / 300 min; seven_day 97.0% / 10080 min
codex      primary    2%   / 10080 min
codex_spark primary   1%   / 10080 min
```

То есть требуемый реальный кейс уже присутствует: Claude weekly = **97%**, Codex weekly =
**2%**. На этой машине Claude worker turns сейчас должны блокироваться, Codex — предлагаться
как доступный provider [M1].

**Следствие:** admission decision должен смотреть только weekly window (`window_minutes == 10080`,
с `id=seven_day` как проверяемым Claude-якорем), а не `max()` всех окон. Короткое 5h окно не
является условием из требования.

### F2. Текущий #154 не реализует новую семантику — CONFIRMED

**Evidence tier 1 (чистый прогон) + tier 2 (код/tests).**

`provider_readiness()` закрывает Claude при `five_hour >=100 OR seven_day >=100`, Codex — при
любом observed window `>=100`. `_quota_refusal()` затем ограничивает результат только
`codex`/`codex_spark`; Anthropic исключён намеренно [S2][S3][S8].

Прямой прогон чистой функции на будущем reset:

```text
anthropic: five_hour=10, seven_day=95 -> {'state':'available', ...}
codex:     weekly primary=95          -> {'state':'available', ...}
```

Таким образом baseline пропускает именно Claude=97 из живого snapshot и любой Codex в
диапазоне `[95, 100)` [M1][M2]. MCP `send_message` вообще не вызывает `_quota_refusal`; он
сразу делает `POST /api/sessions/{name}/send` [S3].

### F3. Реальная граница “steering vs новый turn” находится внутри session lifecycle lock — CONFIRMED

**Evidence tier 2 (код) + tier 1 (mock-backend tests).**

Все **внешние** доставки (HTTP/MCP, TG, timers/cron/bg completion, quota wake, CI webhook,
notifications) сходятся в `SessionManager.send()`; текущий grep дал 13 call sites [M3].
Manager берёт session operation lock, делает optional branch auto-switch, затем вызывает
`AgentSession.send()` [S4][S6].

Но только `AgentSession.send()` под `_lifecycle_lock` знает фактическое состояние в момент
решения:

- `RUNNING` + runtime supports steering (Claude и Codex оба `mid_turn_inject=True`) →
  `backend.send()` продолжает **текущий** turn; это разрешено требованием [S5][S7].
- `IDLE`/`WAITING` → status меняется на `RUNNING`, затем `_ensure_backend()` и
  `backend.send()` начинают новый turn [S5].

Проверка текущего baseline на mock backend: idle send стартует backend, running send steering/
queue не теряет сообщение — `2 passed` [M4]. Гейт перед `SessionManager.send()` был бы слишком
ранним: он заблокировал бы допустимый steering и имеет TOCTOU race по status. Проверка должна
исполняться **под тем же `_lifecycle_lock`, после ветки RUNNING и непосредственно до start-side
effects**. Orchestrator exemption доступен там как `session.is_orchestrator` [S5].

### F4. `AgentSession.send()` не является единственным start path — CONFIRMED

**Evidence tier 2 (полный grep direct backend sends).**

Новые provider operations, которые не проходят обычный idle-send:

1. `_flush_pending()` после завершения текущего хода сам переводит session в `RUNNING`, вызывает
   `_ensure_backend()` и `backend.send(combined)` [S5]. Это реальный обход hard gate. При отказе
   payload обязан остаться в `_pending_messages`, а причина — стать видимой, иначе sender уже
   получил “queued”, но работа молча не стартует.
2. Internal rate-limit retry, server-error retry и max-turn continuation вызывают `self.send()`;
   session-level admission автоматически закроет их [S5].
3. Claude `compact()` посылает как минимум summary prompt и отдельный acknowledgement turn
   backend напрямую; auto-compact применяется к workers. Если “никакие новые worker turns”
   трактуется буквально, оба старта обязаны использовать тот же admission decision [S5].
   Codex native compact — отдельная provider operation, а не обычный prompt turn; включение её в
   quota gate — безопасная консервативная граница, но не load-bearing для delivery bypass.
4. `codex_review()` запускает отдельный `codex exec` через bg job и не имеет `AgentSession`.
   Существующий preflight нужен, но должен использовать **тот же weekly decision**, а не отдельную
   Codex-only семантику [S3].

Direct backend sends при reconnect/heartbeat выполняются только пока status уже `RUNNING`; они
восстанавливают оборванный transport текущего хода и не должны блокироваться/обрываться [S5].

### F5. `spawn_worker` и model change — разные типы действий — CONFIRMED

**Evidence tier 2 (код).**

- Создание worker в `SessionManager.create_session()` заканчивается `session.start(persist=False)`
  **без initial message**: backend/model turn не запускается. MCP `spawn_worker` после публикации
  session отдельным HTTP-вызовом отправляет initial task; квоту расходует именно delivery [S3][S4][S5].
- Один session-level gate гарантирует, что initial task не стартует. Дополнительный spawn preflight
  до worktree остаётся UX/compensation-защитой от созданного, но не запущенного worker; он не может
  быть единственным hard gate.
- `change_model()` при idle disconnects backend, меняет metadata/native session id и сохраняет
  state; provider turn не запускает. Поэтому model change не должен быть authoritative admission
  point. Переключение на **доступный** provider обязано проходить, а следующий `send()` решает,
  можно ли стартовать. Переключение на закрытый provider само по себе не обходит гейт [S5].
- Текущий MCP preflight на `change_worker_model` — поведение #154, не необходимое для hard gate;
  он также не покрывает dashboard HTTP route напрямую [S3][S6].

### F6. Orchestrator exemption разрешает прежнее противоречие “hard gate vs потеря уведомлений” — LIKELY

**Evidence tier 2 (код; не проверено end-to-end до реализации).**

#154 сознательно не гейтил `manager.send`: background failure мог потеряться [S8]. В #168 цена
ошибки другая и дан явный exemption: orchestrator должен отвечать. Основные callers уже имеют
failure routing:

- HTTP/MCP возвращает ошибку вызывающему;
- Telegram delivery сообщает недоставку пользователю;
- bg completion/failure пишет job state и в основных ветках зовёт `report_undelivered`;
- worker auto-report и `notify.py` адресованы orchestrator, значит проходят exemption [S6].

Контрпример остаётся у queued `_flush_pending`: synchronous sender уже ушёл, поэтому одного
exception недостаточно. Phase 2 должен явно потребовать: сохранить очередь + log quota refusal +
уведомить parent orchestrator без запуска worker turn.

### F7. Freshness — ограничение данных, не повод оставлять bypass — CONFIRMED / decision needed

**Evidence tier 1 (история SQLite) + tier 2 (код).**

Фоновый snapshot loop имеет интервал 300 с. Последние 20 фактических дельт: **301.3–304.8 с**;
изменение Claude weekly `94→95` впервые записано `2026-08-07T12:28:56.824707+00:00`,
`95→96` — `2026-08-08T01:49:11.311305+00:00`, `96→97` —
`2026-08-08T06:40:58.855691+00:00` [M1].

`_get_usage_data(force_refresh=False)` использует cache до 300 с, затем пытается обновить, но
при failure подставляет старое значение; `usage_readiness()` маркирует такой snapshot как
`fresh=True` без timestamp [S1]. Значит абсолютную гарантию относительно мгновенного upstream
процента текущий contract дать не может: обнаружение crossing запаздывает до ~5 минут, а при
telemetry failure — дольше.

Для формулировки **hard gate** безопасная полярность после появления центрального server-side
decision такая:

- достоверный weekly `<95` → allow;
- достоверный weekly `>=95` → block;
- weekly отсутствует/нечисловой/stale beyond policy → **block worker start as “quota unknown”**,
  но allow orchestrator/stop/model change.

`fresh` без доказательства времени недостаточно. Authoritative admission input обязан нести
`observed_at` из provider cache. Если age `>= _USAGE_CACHE_TTL` (сейчас 300 с), admission сначала
делает один bounded refresh; успешный refresh заменяет observation, failure оставляет worker start
закрытым как `quota unknown`. Фоновый loop с фактическим периодом 301–305 с сам по себе не может
быть freshness-доказательством: он регулярно пересекает 300-секундную границу. Это не требует
refresh на каждый ход — только при истёкшем observation — и не позволяет старому fallback
маскироваться под свежие данные.

Иначе `unavailable → allow`, 404 между MCP и route и неполный Claude payload остаются
документированными bypass paths #154 [S3][S8]. Цена fail-closed — временная остановка workers при
telemetry outage; явный orchestrator exemption и предложение другого **достоверно доступного**
provider сохраняют управление. Порог и unknown-policy должны жить в одном pure decision, а не в
MCP/route copies.

Остающееся ограничение надо честно зафиксировать в report: без synchronous refresh перед каждым
turn hard gate гарантирует admission по последнему свежему snapshot, не по невидимому upstream
изменению между снимками. #154 измерил cold Codex refresh примерно в 1.0–1.25 с против ~7–9 мс
cache; refresh на каждый turn меняет latency и failure surface [S8].

### F8. Baseline tests #154 протухли по абсолютному reset time — CONFIRMED

**Evidence tier 1 (test run).**

Команда:

```text
uv run pytest -q tests/test_usage_readiness.py tests/test_mcp_quota_gate.py
```

дала **2 failed, 20 passed**. Оба failure — `FUTURE_RESET = 2026-08-08T05:53:45Z` уже в прошлом,
поэтому `provider_readiness` корректно вернул `unavailable` вместо ожидаемого `reset` [M4].
Phase 3 должна убрать wall-clock fixture (инъекция `now`/относительная дата), иначе тесты #168
нельзя отличить от протухшего baseline.

## Counter-evidence and rejected shortcuts

1. **“Просто расширить `_GATED_PROVIDERS` и заменить 100→95”.** Rejected: это одновременно
   начнёт блокировать Claude по 5h, не закроет `send_message`/flush, оставит MCP 404/fail-open и
   hardcoded Claude alternative [S2][S3].
2. **“Гейтить только `SessionManager.send`”.** Rejected: ломает active steering/TOCTOU и не видит
   internal flush/retry/compaction [S4][S5].
3. **“Гейтить каждый route/tool отдельно”.** Rejected: уже опровергнуто #154 — TG, bg jobs и
   direct server callers обходят HTTP/MCP lists [S6][S8].
4. **“Любой direct backend.send надо запретить”.** Rejected: reconnect/heartbeat sends продолжают
   уже идущий turn; их остановка нарушит “уже идущие не обрывать” [S5].
5. **Credits override.** Нормализованный Codex payload несёт supplemental credits, но пользователь
   задал безусловный threshold `>=95`; credits не являются разрешением обхода #168 [S1].

## Affected files, risks, edge cases for Phase 2

### Load-bearing production files

- `app/session.py` — атомарная граница start/steer, pending flush, compact, orchestrator exemption.
- `app/routes/system.py` — quota caches/normalization/freshness; текущий readiness API.
- `app/limit_wake.py` — model→quota bucket и существующий, но семантически другой readiness.
- `app/mcp_stdio.py` — spawn UX preflight, `change_worker_model`, `codex_review`, dynamic error.
- `app/manager.py` — auto-switch before delivery и parent notification path.
- `app/routes/sessions.py`, `app/tg_bridge.py`, `app/bg_jobs.py`, `app/notify.py` — error propagation;
  прод-правки здесь нужны только если центральная ошибка не доходит до человека.

### Tests

- Новый focused contract test для weekly decision: Claude/Codex/Spark, 94.9/95, missing/stale,
  short window irrelevant, dynamic alternatives.
- `tests/test_session.py`: idle/waiting blocked before status/backend; RUNNING steering allowed;
  flush retains messages; internal continuation; orchestrator bypass; stop unaffected.
- `tests/test_mcp_quota_gate.py`: spawn preflight и codex_review use same decision; model change to
  available provider succeeds; no hardcoded Claude suggestion.
- `tests/test_usage_readiness.py`: remove absolute-time fixture and align endpoint semantics.
- Integration seam through `routes/sessions.send_message` for switch→send and HTTP error text.

### Risks / edge cases

- Race: quota decision must be inside `_lifecycle_lock` and before status/log/backend start;
  otherwise concurrent sends can pass stale status or log a task as delivered when blocked.
- Slow async refresh while holding lifecycle lock delays stop; use a bounded precomputed snapshot or
  a two-stage check with revalidation, not an unbounded provider request under the lock.
- Pending payload must not be dropped or spin-retried while closed.
- Error alternative must be computed from the same snapshot; never suggest Claude when Claude is
  itself `>=95`, and do not conflate `codex` with independently available `codex_spark`.
- Grok remains out of scope and must not inherit Codex state through fallback.
- Server-side central code avoids #154's hot-MCP/old-route deployment mismatch; do not introduce a
  new cross-process request contract that is fail-open during restart.

## Confidence summary

- **CONFIRMED:** current live Claude weekly is 97%; current gate allows it.
- **CONFIRMED:** weekly data is normalized for Claude/Codex/Spark and distinguishable by 10080 min.
- **CONFIRMED:** `send()` + `_flush_pending` are the load-bearing start seams; manager/routes alone
  are insufficient.
- **CONFIRMED:** active steering and reconnect are different from new turn and must remain allowed.
- **LIKELY:** existing error routing plus orchestrator exemption prevents the notification loss that
  blocked a deep gate in #154; queued flush needs an explicit new notification path.
- **CONFIRMED:** missing/malformed/stale observation fail-closes only new worker turns; `observed_at`
  и bounded refresh при age >=300 с — обязательная часть hard-gate contract.
- **UNCERTAIN until Phase 2:** exact two-stage placement of bounded refresh versus lifecycle lock.
  Provider I/O must not hold the lock long enough to impair stop, but the final admission still needs
  atomic revalidation immediately before start-side effects.

## Codex adversarial second opinion

Полный протокол: `docs/tasks/168/codex-review-research.md`.

- Round 1: технического вердикта не было — Codex sandbox не смог читать workspace
  (`bwrap: loopback: Failed RTM_NEWADDR`).
- Round 2: тот же persistent-сеанс получил self-contained evidence packet. Он подтвердил
  неправильность #154/readiness, необходимость fail-closed timestamp freshness, execution-time
  проверки flush и dynamic alternatives. Blocking-возражение: internal continuation якобы надо
  exempt через provenance token.
- Round 3: после сверки `TurnManager.finish_turn_status` и internal retry code возражение снято.
  Codex согласился: после `turn_end` status уже `IDLE/WAITING`, поэтому retry/auto-continue — новый
  provider turn; exemption был бы обходом. Claude idle compaction sends тоже признаны новыми turns;
  native Codex compact — консервативный, не load-bearing случай.
- Финальный verdict: **research conclusions approved** при явном timestamp-based
  stale/unknown fail-closed contract; это условие внесено в F7 выше.

## Evidence / sources

All sources below were opened in this session; no web/prior-art search was needed because the answer
lives entirely in Orchestra code and its local telemetry.

- **[S1], tier 2 primary:** `app/routes/system.py:394-1046,1119-1165` — raw fetch,
  Codex normalization, unified snapshot, 300 s loop, readiness endpoint.
- **[S2], tier 2 primary:** `app/limit_wake.py:29-210,624-699` — quota bucket mapping,
  `provider_readiness`, wake delivery.
- **[S3], tier 2 primary:** `app/mcp_stdio.py:541-642,606-750,794-803,1112-1123,1902-1925` —
  #154 gate, spawn, send, model switch, Codex review.
- **[S4], tier 2 primary:** `app/manager.py:471-750,918-932,1506-1558,1668-1750` — create,
  common send, auto-report, restore/restart delivery.
- **[S5], tier 2 primary:** `app/session.py:746-1028,1060-1285,1360-1690,1782-1840` and
  `app/session_turns.py:410-485`, `app/session_hibernate.py:120-184` — exact lifecycle starts,
  retries, flush, compaction, steering/reconnect.
- **[S6], tier 2 primary:** `app/routes/sessions.py:174-210,453-500,596-615`,
  `app/tg_bridge.py:345-397`, `app/bg_jobs.py:520-750`, `app/notify.py:1-100`,
  `app/routes/system.py:1710-1750` — callers and error routing.
- **[S7], tier 2 primary:** `app/models.py:35-150`, `app/runtime_registry.py:29-42,286-334` —
  model/runtime/provider registry and steering capabilities.
- **[S8], tier 2 primary project record:** `docs/tasks/154/{research,plan,report}.md` — measured
  baseline, accepted fail-open and known Telegram/delivery hole.
- **[M1], tier 1 direct measurement:** read-only query of
  `/home/kesha/orchestra/data/orchestra.db`, latest normalized snapshot + last 300 transitions;
  recorded above. No database writes.
- **[M2], tier 1 direct measurement:** pure `provider_readiness()` calls at fixed
  `now=2026-08-08T00:00:00Z`; both 95% inputs returned `available`.
- **[M3], tier 1 reproducible static measurement:** `rg` over all `manager.send`, `self.send` and
  direct backend sends; 13 external manager call sites plus the bypasses enumerated in F4.
- **[M4], tier 1 direct test:** session lifecycle mock tests `2 passed`; #154 quota tests
  `2 failed, 20 passed` solely on expired fixed reset timestamp.
