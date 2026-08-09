# #170 — план исправлений после forensic-аудита

Статус: Phase 2. Этот документ не разрешает изменения Seedon, live SQLite,
systemd, production или уже запущенных сессий. Реализация допустима только после
отдельного approval Phase 3.

## Цель и проверяемые инварианты

Цель — исправить четыре доказанных runtime-дефекта и отдельно проверить одну
гипотезу об эффективности, не превращая нормальную долгую работу `xhigh` Sol в
ложную latency-регрессию.

Инварианты для всех runtime-тикетов:

1. Решение о допуске остаётся единым: свежий weekly window `<95%` допускается,
   `>=95%`, stale, malformed и unknown блокируются. MCP не получает второго
   независимого quota evaluator.
2. Совместимость старой и новой версии никогда не достигается через fail-open.
   Если старый ответ не содержит доказательства weekly/freshness, новый клиент
   отказывает с actionable `upgrade_required`.
3. Каждый runtime-тикет сначала получает воспроизводящий **before**-тест на
   текущем коде, затем **after**-тест, затем независимую мутацию исправленного
   условия. Before/after outputs и красный mutation run сохраняются в
   `docs/tasks/170/measurements/`, без prompts и секретов.
4. Мутации выполняются по одной из свежей копии файла, откатываются в той же
   команде, после отката проверяется уникальный маркер. Ни одна мутация не
   коммитится. Асинхронные behavioral-тесты после первого зелёного прогона
   повторяются три раза.
5. Generic message delivery, MCP transport/lifecycle, compact/precompact и #97
   не меняются: forensic-аудит опроверг их regression. Единственное изменение
   `app/mcp_stdio.py` ограничено quota-readiness adapter для `codex_review`.

## T1 protocol: безопасная совместимость readiness

### Wire contract

`QuotaDecision` и `WORKER_WEEKLY_LIMIT_PCT = 95.0` остаются source of truth.
FastAPI сериализует решение в dual envelope:

```json
{
  "policy": "worker-weekly-v1",
  "wire_version": 2,
  "decision_state": "available|blocked|unknown|not_applicable",
  "state": "available|reset",
  "observed_at": 1786270000.0,
  "valid_until": 1786270300.0,
  "decision_reset_at": "...|null",
  "reset_at": "...|null"
}
```

- `decision_state` и `decision_reset_at` — canonical поля нового клиента.
- `state`/`reset_at` — безопасная проекция для старого MCP parser. Для
  `available`/`not_applicable` это `available`; для `blocked` и `unknown` —
  `reset`. Если реального будущего reset нет, server выдаёт только в legacy
  поле именованный короткий `legacy_retry_at`; canonical reset остаётся `null`.
  Старый parser поэтому блокирует, а не проходит неизвестное состояние.
- `observed_at` и `valid_until` остаются реальными timestamps наблюдения.
  Synthetic retry timestamp не выдаётся за freshness или provider reset.
- Новый MCP предпочитает `decision_state`. Он также принимает текущий v1
  envelope без `decision_state`, если `policy`, canonical `state` и timestamps
  валидны. Legacy ответ без `policy`/freshness не может доказать `<95%`, поэтому
  получает `weekly_quota_upgrade_required`, не background job.
- Для quota-applicable verdict клиент принимает finite positive Unix seconds
  (текущий v1 format) или timezone-aware ISO, затем проверяет `observed_at` не
  дальше малого именованного clock-skew в будущем, `now < valid_until`, и период
  валидности не больше server freshness budget (300 s). Naive ISO,
  stale/future/malformed — fail-closed. `not_applicable` не выдумывает
  timestamps: оно допустимо только для модели, которую central policy
  положительно разрешила вне subscription quota.

Такой envelope нужен потому, что старый parser знает только
`available|reset`, а нынешний новый parser уже требует `policy=v1`. Простая
смена top-level `state` на `reset` сломала бы текущего клиента; удаление legacy
проекции оставило бы старый клиент fail-open на `blocked`.

### Rollout matrix

| MCP client | FastAPI server | Ожидаемое поведение | Rollout status |
|---|---|---|---|
| legacy pre-v1 | legacy pre-v1 | Исторический baseline; hard weekly95 не доказан | не считать безопасной целевой парой |
| legacy pre-v1 | current v1 (`state=blocked`) | Старый parser может fail-open | запрещённый промежуточный skew |
| legacy pre-v1 | new dual | `<95` allow; `>=95`/unknown → `reset`, block | безопасно |
| current v1 client | legacy pre-v1 server | explicit fail-closed legacy-policy error | безопасно, но unavailable |
| current v1 client | new dual | `<95` allow; blocked/unknown fail-closed как unknown state | безопасно |
| new client | legacy pre-v1 server | actionable `upgrade_required`, no launch | безопасно, но unavailable |
| new client | current v1 server | canonical fallback + local freshness validation | безопасно |
| new client | new dual | полный verdict и точная причина | целевое состояние |

Развёртывание только server-first: dual FastAPI → проверка mixed-version matrix
→ новый per-call MCP. Rollback клиента на current v1 безопасен на dual server;
rollback server до current v1 запрещён, пока может существовать legacy MCP.
Ни один compatibility branch не меняет exact boundary `94.999 allow / 95.0
block` центрального evaluator.

## Tickets

### T1 — Readiness dual-envelope и version-skew matrix

- **Vertical result:** старый MCP безопасно работает с новым FastAPI, новый MCP
  безопасно распознаёт current/new FastAPI, а pre-v1 FastAPI даёт ясный
  fail-closed upgrade verdict; weekly95 и freshness проверяются end-to-end.
- **Files:** `app/quota_gate.py`, `app/routes/system.py`, `app/mcp_stdio.py`,
  `tests/test_quota_gate.py`, `tests/test_usage_readiness.py`,
  `tests/test_mcp_quota_gate.py`, при необходимости точечный сценарий в
  `tests/test_mcp_codex_review.py`.
- **Before evidence:**
  1. historical old-parser fixture на текущем v1 `blocked` response проходит
     дальше (воспроизводит fail-open сторону skew);
  2. текущий MCP принимает `available` с истёкшим `valid_until`;
  3. legacy response без policy возвращает общий unknown вместо отдельного
     rollout diagnosis.
- **AC:**
  1. Table-driven тест покрывает все восемь строк rollout matrix и доказывает,
     что launch возможен только при доказанном fresh `<95%`/not-applicable.
  2. При `94.999%` оба поддержанных parser пути допускают; при `95.0%` и
     `100%` old/current/new client paths блокируют. Server gate из #168 также
     остаётся красной линией, даже если client response подменён.
  3. Числовой `observed_at` на 299.999 s проходит; на 300 s, expired
     `valid_until`, excessive validity и future timestamp блокируются. ISO
     варианты отдельно принимают timezone-aware значение и отвергают missing
     timezone/malformed ISO — всё до `bg_create`/subprocess launch.
  4. Legacy `reset_at` синтезируется только для compatibility block, всегда в
     будущем; canonical `decision_reset_at` не подменяется.
  5. Ответ pre-v1 server даёт `weekly_quota_upgrade_required` с требуемой
     server policy/version, без quota-exhausted утверждения и без fail-open.
  6. Behavioral suite проходит три раза; полный quota subset зелёный.
- **Independent mutation evidence:** отдельно мутировать `(a) >=95` в `>95`,
  `(b) unknown→legacy available`, `(c) freshness check в accept,
  `(d) preference `decision_state` обратно на top-level `state`,
  `(e) synthetic future retry убрать`. Для каждой мутации заранее названный
  behavioral test обязан покраснеть; результат записывается в
  `measurements/mutations-t1.md`.
- **Commands:**
  `uv run pytest -q tests/test_quota_gate.py tests/test_usage_readiness.py tests/test_mcp_quota_gate.py tests/test_mcp_codex_review.py`;
  затем три повтора новых async/mixed-version node ids.
- **blocked-by:** none.

### T2 — Runtime-specific quota telemetry в turn-end

- **Vertical result:** turn-end одного runtime никогда не показывает окно
  другого provider/runtime; DB snapshot и видимая строка строятся из одного
  выбранного свежего snapshot.
- **Files:** `app/session_turns.py`, `tests/test_turn_usage.py` либо узкий новый
  `tests/test_turn_quota_telemetry.py`.
- **Design:** заменить глобальный `_format_limits()` на чистый selector/formatter
  с явными `(runtime, model, now)`. Claude читает только `five_hour/seven_day`,
  Sol — только Codex `primary/secondary`, Spark — только nested
  `spark.primary/secondary`. Missing/stale/malformed snapshot не подставляет
  чужое значение: quota suffix отсутствует. Тот же выбранный snapshot питает
  `_cached_quota_state`, чтобы log и DB не расходились на границе TTL.
- **Before evidence:** при Claude `7d=100%` и Codex `primary=33%` текущий Sol
  turn печатает Claude `5h/7d`; отдельный Spark case также не выбирает nested
  bucket.
- **AC:**
  1. В смешанном cache Sol log содержит только Codex labels/33% и не содержит
     `5h`, `7d` или 100%; Spark содержит только nested Spark окна; Claude —
     только свои `5h/7d`.
  2. Stale/missing snapshot каждого runtime не показывает quota suffix и не
     откатывается на глобальный Claude cache.
  3. Зафиксированный clock доказывает одинаковые provider/utilization/reset в
     DB update и turn-end text.
  4. Before fixture красный на текущем commit, after зелёный три раза.
- **Independent mutation evidence:** отдельно вернуть Claude `_usage_cache` в
  Sol selector, вернуть top-level Codex bucket в Spark selector и отключить
  stale check; каждый runtime-specific тест обязан покраснеть. Артефакт —
  `measurements/mutations-t2.md`.
- **Commands:** `uv run pytest -q tests/test_turn_usage.py tests/test_turn_quota_telemetry.py`
  (если новый файл создан), затем три повтора async node ids.
- **blocked-by:** none.

### T3 — Isolation managed Codex workers без потери Orchestra delegation

- **Vertical result:** каждый CodexBackend, запущенный Orchestra, стартует с
  native `features.multi_agent=false`; full-cycle worker с разрешённым
  `can_spawn` по-прежнему видит и вызывает только tracked Orchestra
  `spawn_worker` path.
- **Files:** `app/backend_codex.py`, `tests/test_backend_codex.py`,
  `tests/test_default_pipeline.py` (либо существующий тест MCP config в
  `tests/test_backend_codex.py`).
- **Before evidence:** fake app-server command для `is_orchestrator=False` не
  содержит `features.multi_agent=false`; worker config при этом уже содержит
  Orchestra `spawn_worker`.
- **AC:**
  1. Fake-process behavioral test для orchestrator и worker фиксирует один и
     тот же native multi-agent disable flag.
  2. Full-cycle worker с `can_spawn=["*"]` сохраняет Orchestra MCP
     `spawn_worker`; роль без delegation его не получает.
  3. Никакие `subagent_start/progress/end` native события не нужны для
     поддерживаемой делегации: тест проверяет command/MCP capabilities, а не
     строку исходника.
  4. Existing Codex connect/config suite проходит три раза.
- **Independent mutation evidence:** вернуть условие
  `if self._is_orchestrator` — worker command test обязан покраснеть, а paired
  Orchestra-delegation test остаться зелёным; затем удалить `spawn_worker` из
  разрешённого MCP config — paired test обязан покраснеть. Артефакт —
  `measurements/mutations-t3.md`.
- **Commands:** `uv run pytest -q tests/test_backend_codex.py tests/test_default_pipeline.py`.
- **blocked-by:** none.

### T4 — Early guard для `.codex` и oversized project instructions

- **Vertical result:** repo-owned `.codex` file остаётся byte-for-byte
  нетронутым, но Codex получает canonical skill index как per-session fallback;
  oversized `AGENTS.md` диагностируется до CLI start и получает компактную
  инструкцию дочитать ровно отсутствующий хвост, без изменения repo/config.
- **Files:** `app/prompting.py`, `app/session.py`, `app/runtime_registry.py`,
  при необходимости pure config helper в `app/backend_codex.py`;
  `tests/test_manager.py`, `tests/test_prompting.py`,
  `tests/test_runtime_registry.py`, `tests/test_session.py`.
- **Design:**
  1. Общая внутренняя injection-функция возвращает structured result,
     различающий `installed`, `home_path_is_file` (включая признак tracked),
     `tracked_skill`, `missing_source` и `unsafe_git_state`, а не одинаковый
     `0`. Существующий `inject_skills_to_worktree(...) -> int` остаётся
     backward-compatible wrapper над `.written`; session использует detailed
     helper, поэтому guards не дублируются и другие call sites не ломаются.
  2. Только `repo_owned_home_file` включает ephemeral skill-index fallback в
     `BackendBuildContext`; native `.codex/skills` и generated index одновременно
     не включаются. Fallback пересобирается при connect и идемпотентен.
  3. Codex preflight читает effective `project_doc_max_bytes` из
     `$CODEX_HOME/config.toml` через `tomllib`, считает **bytes** реально
     существующего root `AGENTS.md` после `sync_agents_md` и находит первую
     строку, не помещающуюся целиком в budget. При overflow один session status warning
     до `connect()` сообщает `path / actual bytes / budget / first omitted
     line`; system prompt получает короткую инструкцию один раз перечитать с
     этой (возможно частично auto-loaded) строки до EOF. Repo doc и config не режутся, не расширяются и не
     перезаписываются. Если effective budget нельзя доказать, exact overflow не
     утверждается.
  4. Повторный reconnect не дублирует warning или fallback block. Одновременно
     обнаруженные `.codex`-conflict и oversize выводятся как две разные причины.
- **Before evidence:** tracked empty `.codex` даёт только silent skip и лишает
  worker skill body; `155284-byte AGENTS.md` при `65536` не даёт pre-connect
  warning/fallback.
- **AC:**
  1. Git fixture с tracked `.codex` file остаётся с тем же SHA/content и clean
     `git status`; backend prompt содержит ровно один canonical index с каждым
     ожидаемым skill/path один раз.
  2. Обычный `.codex/skills` path не получает generated duplicate.
  3. ASCII и multibyte fixtures проверяют byte budget, boundary `== budget`
     без warning и `budget+1` с точным first-omitted-line warning до fake CLI
     connect.
  4. Два reconnect не меняют repo и не размножают prompt/status warning.
  5. Missing/malformed config не вызывает overwrite или выдуманный exact
     threshold; startup остаётся fail-safe с явной диагностикой только там,
     где факт доказан.
- **Independent mutation evidence:** отдельно превратить
  `repo_owned_home_file` в generic success, отключить fallback flag, заменить
  byte length на character length и подавить oversize instruction. Соответствующие
  content/clean-tree/multibyte/ordering tests обязаны покраснеть. Артефакт —
  `measurements/mutations-t4.md`.
- **Commands:** `uv run pytest -q tests/test_manager.py tests/test_prompting.py tests/test_runtime_registry.py tests/test_session.py`
  с узкими node ids для новых сценариев, затем три повтора async connect tests.
- **blocked-by:** none.

### T5 — Evidence gate для repeated reads/context и test polling

- **Vertical result:** либо отдельный fixed-workload A/B доказывает улучшение и
  допускает один узкий repo-owned change, либо runtime/prompt остаётся без
  изменений, а итог содержит только quantified recommendation.
- **Files:** всегда — новые redacted fixtures/aggregates в
  `docs/tasks/170/measurements/` и вывод в `docs/tasks/170/report.md`; runtime или
  pipeline prompt — только после прохода gate и с отдельным перечислением в
  отчёте.
- **Pre-registered experiment:**
  1. Заморозить одинаковый redacted workload: один multi-file review с большим
     tool result, один test command, который yields один handle, и один
     далёкий от Seedon domain case. Никаких live Seedon sessions.
  2. Сначала выполнить повторные baseline-vs-baseline прогоны и посчитать
     split-half noise для active wall, repeated reads одного unchanged path,
     tool-result bytes, compactions и poll calls.
  3. Только затем сравнить baseline с одним заранее описанным candidate на тех
     же inputs/Sol model/effort/cache policy; Claude не используется. Primary outcome — correctness/no lost
     work; secondary — repeated-read count и result bytes; wall/compactions/
     polls — diagnostic.
  4. Change разрешён, только если correctness не хуже, нет lost turn/test
     process, а paired improvement по целевой метрике превышает измеренный
     median noise. Prompt candidate дополнительно обязан пройти distant-domain
     case. Круглый абсолютный threshold после просмотра результата запрещён.
  5. Нет quota, нет сравнимых прогонов, эффект ≤ noise или workload изменился →
     **no code/prompt change**. Записать measured baseline (`193` reads,
     `2.34 MB` results, `39` large results, `31.06 s` explicit poll wall) и
     рекомендацию, не выдавая её за regression/fix.
- **AC:** raw run metadata и aggregates воспроизводимы без prompts/secrets;
  before/after workload hashes равны; gate verdict однозначно `PASS → named
  change` либо `NO CHANGE → quantified recommendation`. Если PASS приводит к
  runtime diff, для него обязательны собственный behavioral test, независимая
  мутация и three-run async evidence по общему инварианту выше. При NO CHANGE
  mutation неприменима, потому что runtime diff отсутствует.
- **Commands:** отдельный measurement script фиксируется вместе с fixture;
  точная команда, repetitions, model/effort, commit и split-half расчёт
  записываются до первого candidate run.
- **blocked-by:** T1, T2, T3, T4 — A/B снимается после runtime fixes, чтобы не
  смешивать версии и workload.

## Phase 3 порядок и общий verification

T1–T4 могут реализовываться последовательно в любом порядке до T5; T5 всегда
последний. После каждого тикета: before/after artifact, targeted behavioral
suite, отдельные мутации, чистый откат. После всех тикетов:

```bash
uv run python -m pytest -x -q > /tmp/pytest-170.log 2>&1
```

Лог читается один раз; повторное polling запрещено. Если команда yielded,
используется ровно её handle/wait path. После suite проверяются `git diff`,
`git status` и отсутствие `uv.lock` изменений. Реализация shared runtime
требует отдельного Codex implementation review; quota/readiness/legacy block
не обходятся.

## Не делать

- Не рестартовать и не деплоить FastAPI/systemd; rollout matrix — тестовый
  контракт, не разрешение на rollout.
- Не писать в Seedon worktree/DB/session и не управлять `feat-groom-demo`.
- Не менять generic delivery, MCP cancellations/transport, compaction или #97.
- Не повышать автоматически `project_doc_max_bytes`, не обрезать и не
  переписывать tracked `.codex`/`AGENTS.md`.
- Не отключать поддерживаемую Orchestra delegation.
- Не оптимизировать normal `xhigh` model time и не обещать latency gain без A/B.
