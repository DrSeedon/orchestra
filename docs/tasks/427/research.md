# #427 — Dynamic Workflows: живая механика и граница переноса в Orchestra

Дата исследования: 2026-09-01. Фаза: 1 (research only).

## Статус входных данных и границы

- Два утренних запуска (`wf_0ac5aab5-12d`, `wf_4dacb762-819`) завершены; их числа из карточки сохранены как исходный raw-row срез.
- Третий запуск (`wf_d609dd9a-f8a`) измерен **2026-09-01 22:20:19 +07:00** (`2026-09-01T15:20:19.002198Z`): 53 agent JSONL, 53 `started`, 43 `result`, 10 незавершённых; 41 Verify, 10 Fix, 2 Review. Прогон в этот момент продолжался, поэтому это не финал.
- Тот же запуск завершился **2026-09-01 23:06:45.982 +07:00** (`2026-09-01T16:06:45.982Z`): final state `status=completed`, `agentCount=59`, 59/59 progress agents `done`. Полный transcript/journal corpus содержит ещё один реально запущенный, затем прерванный leaf `a5a56e9aa17a00e53`, которого final state не учитывает: поэтому spend-анализ видит 60 started JSONL / 59 results / 1 no-result.
- Новых workflow/agent/model запусков для #427 не было. Единственный новый runtime-эксперимент — пять локальных пар `true`/`bwrap true`, без модели, сети и записи.
- Все внешние файлы, `~/.claude/` и боевая SQLite читались read-only. Записаны только файлы в `docs/tasks/427/`.
- `docs/tasks/dynwf/research.md` принят как вход: три старых дизайна и уже пройденные CLI-гейты не переоткрывались.
- Обычно Phase 1 продвигает вывод в `docs/kb/`; здесь этого намеренно нет, потому что пользователь запретил любые записи вне `docs/tasks/427/`.

## Вопрос

**Context.** Orchestra сейчас координирует долгоживущие worker sessions через `spawn_worker`/`run_fan`: task, ветка, worktree, accumulated context, durable barrier и merge принадлежат платформе.

**Change under test.** Добавить дешёвый детерминированный workflow runner с короткими Luna-first leaf agents и проверить, способен ли он заменить не только исследовательский fan-out, но и существующую worker-механику без потери свойств.

**Baseline.** Текущие `run_fan` и child `spawn_worker`, а не три уже написанных архитектурных эскиза.

**Outcomes.** Решают: (1) точная topology/result/journal/schema механика по трём живым Claude Workflow runs; (2) cache create/read и API-equivalent cost по реальным provider request, а не по transcript fragments; (3) replay десяти реальных применений `run_fan`/child-spawn против durable barrier, warm reuse, task/worktree/branch/merge; (4) физическая изоляция; (5) обязательный учёт; (6) машинный model/budget gate.

## Гипотезы и фальсификаторы

1. **H1 — Workflow является универсальным конструктором и lossless заменяет `run_fan`/child spawn.** Фальсификатор: хотя бы одно реальное применение требует durable barrier после рестарта, reuse тёплой сессии, task/worktree/branch или merge, которых нет у short-lived `agent()`.
2. **H2 — Workflow экономичен благодаря общему кешируемому префиксу между leaf agents.** Фальсификатор: первые provider requests в каждом leaf преимущественно создают кеш заново; cache-read доминирует только на последующих tool rounds того же leaf.
3. **H3 — `started → result` journal и один owner commit достаточны для безопасной параллельной работы.** Фальсификатор: WAL не сохраняет проверяемое intent или несколько agents пишут одни и те же working-tree paths до owner commit.
4. **H4 — `bwrap --ro-bind repo + --bind output + --unshare-net` есть дешёвая золотая середина.** Фальсификатор: оболочка блокирует и provider transport либо оставляет доступ к сети/секретам/ресурсам.
5. **H5 — prompt-level model choice способен запретить Fable.** Фальсификатор уже наблюдён: два запуска исполнились на Fable; запрет должен стоять перед единственной функцией запуска leaf runtime.

## Метод и правило подсчёта

Главный корпус: `~/.claude/projects/-mnt-data-Projects-Python-orchestra/bd702267-a0db-42f2-8808-b0d43e37ced3/subagents/workflows/<run>/agent-*.jsonl`, `journal.jsonl`, сохранённые workflow scripts и завершённые state JSON.

Важное различение:

- **raw assistant record** — строка JSONL `type=assistant` с ненулевой Claude usage; именно это воспроизводит числа карточки (365/1717 и 45.4M/203.5M).
- **provider request** — уникальный `requestId`. Один provider response дробится на несколько assistant rows (thinking, tool use, text), причём каждая строка повторяет usage. Для денег и токенов берётся последняя usage snapshot на `requestId`. Во всех трёх runs входные/cache fields внутри одного `requestId` были постоянны (`request_context_variations=0`); рос только output snapshot.
- Цена пересчитана как в `app/backend_claude.py`: input × 1.0, cache-create × 1.25, cache-read × 0.1, output по current `app/models.py`. Это API-equivalent, не реальные деньги подписки.

Воспроизводимая команда:

```bash
python3 docs/tasks/427/analyze_workflow_logs.py
```

## 1. Механика Claude Workflow по живым логам

### Вызов и возврат

Parent вызывает один tool `Workflow` с обычным JS `script`. Tool возвращает сразу, не результат:

```text
Workflow launched in background. Task ID: wu6x7ywcy
Transcript dir: .../subagents/workflows/wf_0ac5aab5-12d
Run ID: wf_0ac5aab5-12d
You will be notified when it completes.
```

В результате tool также дословно выдаёт ручной recovery contract:

```text
Workflow({scriptPath: "...orchestra-dynwf-research-wf_0ac5aab5-12d.js",
resumeFromRunId: "wf_0ac5aab5-12d"}) — completed agents return cached results
```

То есть parent получает: immediate receipt → background execution → один completion result/notification. Agent outputs не возвращаются отдельными parent turns.

### Топология

- `phase('Map')`/`phase('Fix')` и `phase` в options группируют progress; сами по себе они не создают barrier.
- `await parallel([...thunks])` создаёт barrier. Утренний research: 5 Map одновременно → после полного join 3 Design одновременно → после полного join 1 Stress.
- Текущий script использует реальный `pipeline(groups, fix, review)`: Review конкретной ownership group запускается сразу после её Fix, пока Fix других groups ещё идут. В script это названо дословно: `pipeline: each group reviews as soon as its fix lands`.
- Перед построением `byGroup` текущий script делает явный global barrier Verify: `const verified = await parallel(...)`, затем `const toFix = ...`.
- На 12 CPU наблюдаемый maximum active leaf agents равен 10; это согласуется с заявленным `min(16, CPUs-2)`. Lifetime ceiling 1000 в этих трёх runs не достигался и по логам не проверен.

### Передача задания и результата

Каждый leaf JSONL начинается одной user строкой с готовым task prompt; например:

```json
{"type":"user","message":{"role":"user","content":"Map app/quota_gate.py admission rules ..."},"isSidechain":true,"agentId":"a3b24e07c6bd4b9c2","cwd":"/mnt/data/Projects/Python/orchestra","gitBranch":"main"}
```

Результат записывается в `journal.jsonl`. Реальная пара:

```json
{"type":"started","key":"v2:4a24c74b2e66d66b010b75e0f7fd317699f14205c064e7644df8a252ea4c1aa6","agentId":"ac8b4aa51e032e59e"}
{"type":"result","key":"v2:4a24c74b2e66d66b010b75e0f7fd317699f14205c064e7644df8a252ea4c1aa6","agentId":"ac8b4aa51e032e59e","result":"# Критика трёх дизайнов Dynamic Workflows ..."}
```

У failed/in-flight calls остаётся `started` без `result`. В завершённом `wf_4dac...` — 78 started, 32 results, 46 без результата; 45 Verify и Critic упёрлись в weekly limit, но workflow state всё равно `status=completed`. Следствие: completed workflow не означает, что все agents успешны; consumer обязан проверять per-call terminal state/coverage.

`journal.jsonl` — минимальный WAL, но не достаточный аудит: строка `started` содержит только opaque key + agentId, без seq, prompt/options, requested/resolved model, phase, label, timestamp и dispatch state. Полный script лежит отдельно; state JSON с progress появляется для завершённых runs, а у текущего `wf_d609...` на момент среза state JSON ещё отсутствовал.

### Системный префикс: что доказано, а что нет

Литеральный `system` prompt в agent JSONL **не сериализуется**: во всех трёх runs есть только `user`, `assistant`, `attachment`; ни одной `system` row. Поэтому назвать скрытый текст по логам нельзя.

Наблюдаемый effective prefix перед первым model answer одинаково содержит:

```json
{"attachment":{"type":"deferred_tools_delta","addedNames":[...]}}
{"attachment":{"type":"skill_listing","content":"- 3d-frontend: ...","skillCount":77,"isInitial":true,...}}
```

- У двух утренних runs каждый из 87 agents получил 44 deferred tools + список 77 skills длиной 30,005 символов.
- На срезе 22:20:19 каждый из 53 agents получил 45 deferred tools + 78 skills / 30,009 символов; финальные 60 observed JSONL имеют ту же attachment signature.
- Assistant metadata дословно маркирует `"attributionAgent":"workflow-subagent"`; в новой версии также `"attributionSkill":"workflow-authoring"`.
- User task, cwd, branch и attachments видимы; скрытые Claude Code/workflow-subagent instructions и точная доля `CLAUDE.md`/tool schemas в токенах не видимы. Первичная cache usage даёт только общий размер, не компонентную раскладку.

### Structured output

Schema не является просьбой «ответь JSON». Runtime добавляет отдельный tool. Agent физически вызывает:

```json
{"type":"tool_use","name":"StructuredOutput","input":{"items":[...]}}
```

Runtime отвечает:

```json
{"type":"tool_result","content":"Structured output provided successfully"}
```

При ошибке tool возвращает validator feedback:

```json
{"type":"tool_result","content":"Output does not match required schema: root: must have required property 'refuted'","is_error":true}
```

После этого тот же agent повторяет `StructuredOutput`. Наблюдения:

- `wf_0ac...`: 3/3 schema agents приняты с первой попытки.
- `wf_4dac...`: 32/32 agents, дошедших до ответа, приняты с первой попытки; 46 не дошли до schema из-за quota failure.
- `wf_d609...` на срезе: 43 accepted structured results; analyzer проверяет порядок **по каждому agent**: `agents_with_schema_error=10`, `agents_recovered_after_schema_error=10`. Все десять сначала получили schema error и позже success receipt. First-pass compliance 33/43 = 76.7%, eventual compliance среди завершивших 43/43.
- `wf_d609...` в финале: 59 accepted structured results; `agents_with_schema_error=17`, и те же 17 имеют более поздний success. First-pass compliance 42/59 = 71.2%, eventual compliance среди final-state agents 59/59; отдельный interrupted orphan результата не дал.

Это подтверждает tool-layer validation/retry у Fable и Opus. **Данных о Luna нет.** Переносить 59/59 на Luna нельзя.

## 2. Что именно стоит денег

### Raw карточки верен как transcript metric, но не как billing metric

Два JSONL assistant fragments одного provider response имеют один `requestId`; пример из Opus leaf:

```json
{"requestId":"req_011CecupFKcZgu2cSzGfcQNv","content":[{"type":"thinking",...}],"usage":{"input_tokens":2,"cache_creation_input_tokens":2954,"cache_read_input_tokens":87403,"output_tokens":5}}
{"requestId":"req_011CecupFKcZgu2cSzGfcQNv","content":[{"type":"tool_use",...}],"usage":{"input_tokens":2,"cache_creation_input_tokens":2954,"cache_read_input_tokens":87403,"output_tokens":211}}
```

Сумма обеих строк повторно считает один input/cache. Исторические `$548` из карточки относятся к более раннему live snapshot третьего run (20 agents) и **не воспроизводимы текущим append-only корпусом без точного cutoff того снимка**. Два завершённых raw плеча дают $94.18 + $385.34; арифметически карточка приписывала тогдашнему третьему срезу около $68.48. Это inference из карточки, не независимо замороженный замер. Текущий timestamped cutoff ниже считается отдельно.

| Run / отметка времени | Observed agent JSONL | Journal result / no-result | Raw assistant records | Raw tokens | Unique requestIds | Unique tokens | Cache create | Cache read | Raw-row API-equiv $ | Unique-request API-equiv $ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `wf_0ac...` final | 9 | 9 / 0 | 365 | 45.436M | 170 | 21.560M | 1.245M | 20.175M | 94.18 | 42.73 |
| `wf_4dac...` final | 78 | 32 / 46 | 1,717 | 203.530M | 805 | 98.127M | 4.827M | 92.615M | 385.34 | 187.11 |
| `wf_d609...` **срез 01.09 22:20:19 +07** | 53 | 43 / 10 | 2,324 | 256.798M | 1,047 | 118.039M | 5.771M | 111.744M | 230.69 | 104.99 |
| `wf_d609...` **финал 01.09 23:06:45.982 +07** | 60¹ | 59 / 1 | 3,511 | 437.291M | 1,654 | 213.602M | 7.613M | 205.064M | 357.15 | 173.17 |

¹ Final workflow state считает 59/59 done agents; шестидесятый JSONL — реально оплаченный, затем `[Request interrupted by user]` leaf, отсутствующий в final progress. Поэтому он включён в spend/token columns, но не объявлен успешным result.

### Кеш не общий в той форме, на которой держалась гипотеза

| Run / phase | First-request cache-read share | Later-request cache-read share | Вывод |
|---|---:|---:|---|
| `wf_0ac` Map | 0.0% | 98.10% | пять параллельных cold leaves создали prefix каждый |
| `wf_0ac` Design | 4.08% | 95.57% | только частичный cross-leaf reuse |
| `wf_0ac` Stress | 0.0% | 95.91% | новый phase/long prompt снова cold |
| `wf_4dac` Find | 14.35% | 97.98% | общая малая prefix-часть, остальное create |
| `wf_4dac` Verify | 15.20% | 97.83% | то же на 67 leaves |
| `wf_d609` срез 22:20:19 | 18.73% | 98.12% | Opus повторяет тот же механизм |
| `wf_d609` финал 23:06:45.982 | 18.39% | 98.37% | финал остаётся внутри прежней вилки 0–18.7% |

**CONFIRMED:** деньги внутри leaf действительно держатся на cache-read последующих tool rounds (≈98%).

**REFUTED:** общий prefix не делает cold fan дешёвым автоматически. На первом request 81–109K tokens у ранних Fable leaves и около 85K у первого Opus leaf преимущественно создавались заново. В Opus wave последующие leaves обычно читали только 16,285 tokens и создавали около 69.5K каждый. Это **совместимо** с различающимися per-call cache keys и/или parallel cold-start stampede; причинный механизм по одним usage fields не разделён.

Следствие для Orchestra: экономия должна приходить из **срезания prefix** (lean role, no inherited `CLAUDE.md`, no skill catalog, узкий tool set), а не из надежды, что 10 cold processes поделят cache. Удаление worktree само по себе экономит lifecycle и риск, но не гарантирует model cost.

## 3. Универсальный конструктор: механическая проверка на нашей истории

Срез боевой БД на 2026-09-01:

- Ровно 3 `run_fan` tool calls.
- 45 child `spawn_worker` attempts из non-orchestrator sessions; после сведения повторных попыток — 20 уникальных children в 7 parent applications.

### Все реальные `run_fan`

| Применение | Реальная форма | Выражается short-lived workflow? | Потерянное свойство |
|---|---|---|---|
| `camera-spec` 08:20 | 3 Luna research workers, отдельные owned dirs, каждый пишет/commit, затем owner merge | Смысл исследования — да, если agents возвращают structured result или пишут в отдельные output dirs | child commit/worktree/task/merge исчезают; нужен owner WAL+commit |
| `pitch-game` 08:37 | 3 Luna research workers, отдельные dirs/commits | Аналогично | Аналогично; также реальный cross-repo `repo_path` важен для merge |
| `camera-spec` 10:03 | `reuse` тех же 3 idle workers для второго прохода | **Нет** для чистого one-shot | накопленный context, живой task/branch/worktree, session identity и durable fan barrier |

### Все семь classes child-spawn applications

| Parent application | Attempts / unique | Реальная работа | Merge/task свойство | Lossless workflow verdict |
|---|---:|---|---|---|
| `feat-learning-skill` | 9 / 4 | 3 research slices + independent review | task #32, worktrees; session reuse/retries | review/research expressible; session identity не сохраняется |
| `research-cdn-ru` | 6 / 2 | две таблицы CDN evidence | оба child branches merged | только через owner artifact+commit; не как drop-in |
| `research-face-pipelines` | 9 / 3 | три research slices | отдельные owned dirs и 3 merges | artifact workflow возможен; merge semantics остаётся с worker path |
| `research-quota-map-sol` | 3 / 3 | три implementation tickets | red tests, code branches, 3 merges | **нет** без worktree/task/merge leaf |
| `research-ram-32gb` | 6 / 3 | три research slices | отдельные branches, выборочные merges | artifact workflow возможен, но exact branch recovery теряется |
| `audit-style-blind` | 10 / 4 | 3 research slices + 1 code executor | research merges + code ticket/worktree | смешанный: research да, code нет |
| `research-agent-memory` | 2 / 1 | code child, который не должен был спавниться | auto-created #420, отдельная branch, остановлен без merge | workflow не должен превращать ошибочный code spawn в дешёвый обход ownership |

### Вердикт гипотезы

**H1 REFUTED в строгом смысле.** Текущий short-lived Workflow не является lossless replacement: в живой истории есть warm `reuse`, restart-surviving `fan_barrier`, task/worktree/branch/merge и code-ticket acceptance.

Есть две честные трактовки «универсального конструктора»:

1. **Сосуществование.** `agent()` — ephemeral read/research/schema leaf; `run_fan`/`spawn_worker` остаются для persistent/warm/code/merge. Самый дешёвый и узкий вариант.
2. **Универсальный DSL над двумя leaf types.** `agent()` вызывает дешёвый one-shot, `worker()` композиционно использует существующие spawn/fan/task/worktree/merge primitives. Тогда workflow универсален как язык, но не заменяет underlying worker machinery.

Полное удаление `run_fan` и права spawn возможно только если новый engine сам повторит task binding, worktree lifecycle, durable barrier/wake, warm-session reuse и merge saga. Это уже full workflow engine, не `wf_run` v0.

## 4. Золотая середина по изоляции

### Что подтверждено измерением

Пять чередующихся A/B пар при loadavg 0.93/0.91/0.97:

| Run | `true`, ms | `bwrap --ro-bind / / --unshare-net true`, ms |
|---:|---:|---:|
| 1 | 1.465 | 5.991 |
| 2 | 1.056 | 5.377 |
| 3 | 0.757 | 4.701 |
| 4 | 0.789 | 4.649 |
| 5 | 0.743 | 4.963 |

Это namespace-only microbenchmark, не end-to-end CLI benchmark. Pairwise overheads: 4.526, 4.321, 3.944, 3.860, 4.220 ms; их median = **4.220 ms**. Сама namespace оболочка практически бесплатна относительно 7+ second model call; полные binds, auth/env setup и CLI здесь не измерялись.

### Почему стартовую формулу нельзя применять буквально

`--unshare-net` вокруг `claude --print`/`codex exec` отрезает не только web tools, но и provider transport самого CLI. Рабочая `NETWORK_DENIED` проба #422 доказывает именно этот запрет; совместимость с subscription CLI из неё не следует.

Развилки:

| Изоляция | Что физически гарантирует | Что не ловит | Цена |
|---|---|---|---|
| **I1: CLI внутри bwrap, shared network**; minimal ro runtime binds + ro repo, отдельный rw output dir, clean env | code/repo не записывается, git index read-only | CLI требует auth: engine создаёт dedicated per-run runtime home и монтирует только provider auth material + отдельный writable state/cache. Agent process всё равно может прочитать credential и вывести его в shared network; это защита от случайной записи, **не secret boundary**. Также не ловит CPU/RAM/fork/provider/web spend | namespace-only +4.220 ms; ориентир 1–2 agent-days интеграции/fixtures (ESTIMATE), точный Claude credential/write contract — implementation spike |
| **I2: existing host backend/model transport снаружи; только custom tool broker внутри `bwrap --unshare-net`** | Orchestra backend владеет subscription auth вне sandbox; builtin Bash/Read/Write/Web tools не выдаются, leaf получает только safe read/rg/shell/emit tools; broker видит ro repo + rw output, без сети и без credentials | online research требует отдельный allowlisted `safe_fetch` host tool; broker становится новым security seam | +5–8 agent-days к I1 (ESTIMATE) |
| **I3: existing worktree worker** | isolated writable code tree, task/branch/merge/recovery | cold prefix/session cost и lifecycle | уже существует; применять только к code/warm/persistent |

Нельзя использовать удобный `--ro-bind / /`: он делает host secrets read-only, но читаемыми. В I1 нужен dedicated runtime home вместо всего `~/.claude`/`~/.codex`; в I2 credentials вообще не монтируются. Bwrap сам не лимитирует RAM/CPU/process count; нужны parent-side semaphore, timeout, pidfd group kill и MemAvailable gate.

**Предлагаемая середина зависит от threat model:** I1 + I3 — самый дешёвый вариант, если цель ровно «не портить code», а leaf не считается hostile. I2 + I3 — единственный из перечисленных вариантов, который одновременно оставляет subscription transport рабочим и не отдаёт credentials/network tool executor; он дороже на broker. Решение остаётся за пользователем.

## 5. Коммиты и write-ahead journal

Вывод «leaf agents не коммитят; owner прогона коммитит один раз» подтверждается текущим live script и остаётся правильным для общего output tree:

- все workflow agents имеют `cwd=/mnt/data/Projects/Python/orchestra`, `gitBranch=main`;
- script дословно запрещает agent commits и делит paths через `GROUP_OF`/`OWNED`;
- owner получает results, затем может проверить общий diff и сделать один commit.

Это убирает гонку за Git index и 20 commits, но **не** убирает гонку за working-tree files. Без disjoint ownership два agents могут перезаписать друг друга до owner commit. Для v0 безопасны только:

- read-only repo + отдельный `output/<call-id>/` на каждый leaf; либо
- доказанно непересекающиеся owned paths; либо
- existing separate worktrees для code.

Claude journal подтверждает нужную write-ahead форму, но его запись слишком бедна для Orchestra. V0 call intent должен до dispatch содержать минимум:

```text
run_id, seq, call_key, prompt_hash, options_hash, label, phase,
requested_model, resolved_model, state=QUEUED, created_at
```

Дальше `DISPATCHING → SUCCEEDED | FAILED_BEFORE_SUBMIT | OUTCOME_UNKNOWN`; result path и usage event IDs записываются до terminal. Это позволяет отличить «не звали» от «звали, исход неизвестен». Owner commit идёт только после reconciliation всех terminal calls.

## 6. Перенос на существующие швы Orchestra

### Переиспользуется без новой семантики

- `bg_create(type="run")` + pidfd process-group — host для one-shot runner.
- `codex_review` — живой precedent sessionless `codex exec` в bg run.
- `/api/usage/readiness` — тот же admission decision, что worker/review.
- `turn_usage_add` + `app/codex_review_artifact.py` — sessionless accounting pattern.
- `_codex_cost`/`CODEX_TOKEN_PRICES` и Claude `total_cost_usd`/usage.
- `fan_barrier` manifest/wake/rearm — образец exactly-once completion delivery.
- Harness JSONL — fsync/tolerant-tail pattern, но не его unreliable free provider.

### Строить обязательно

- workflow run/call WAL с seq/hash/states/usage/result paths;
- one-shot Claude/Codex adapters и lean prompt/tool profiles;
- mandatory model-policy gate перед leaf launch;
- parent-side concurrency/token/cost/pool/depth governor;
- bwrap wrapper и secret/env masking;
- restart policy: manual replay или first-class recovery (развилка ниже).

### Что заменяется

| Граница | `run_fan` | Право worker spawn children |
|---|---|---|
| Sidecar v0 | остаётся для durable/persistent/warm/code; workflow забирает ephemeral research | остаётся только для code/warm/persistent; research fan должен идти workflow |
| Hybrid universal DSL | остаётся внутренним primitive под `worker()`; внешний caller видит один workflow API | прямой spawn можно закрыть после того, как DSL доказал обе leaf semantics |
| Full replacement | удаляется только после parity по task/worktree/reuse/barrier/merge | workflow engine становится единственным owner lifecycle; максимальная цена/риск |

## 7. Маршрутизация Luna / Sol / Opus

| Роль | Default | Эскалация | Основание |
|---|---|---|---|
| loader/extractor по точной таблице/schema | Luna | Sol после одного terminal schema/AC failure | closed, mechanically checkable |
| skeptic с конкретным claim+falsifier+named files | Luna | Sol при ambiguity/cross-file mechanism | bounded binary verdict vs open causal trace |
| fixer | **не one-shot v0**; existing Luna worker с frozen RED | Sol one attempt after Luna failure | code требует worktree/test/merge |
| reviewer | Luna first pass на compact/closed | Sol на blocker/high-risk/uncertainty с authorization | совпадает с current `codex-debate` gate |
| mechanical reducer/dedupe | Luna | none или Sol при unresolved contradiction | schema + deterministic checks |
| architecture synthesis | Sol | Opus только special ambiguity/cross-family по явному owner choice | открытый join не является closed Luna task |

**Luna schema compliance — UNCERTAIN.** В трёх workflow runs были только Fable и Opus. Нужен отдельный, пользователем одобренный pilot; в #427 его не запускали.

Предлагаемый pilot после одобрения: 20 frozen closed items × роли loader/skeptic/reducer (без code writes), одна immutable JSON Schema, first-pass и eventual acceptance, semantic AC grader и wrong-but-valid JSON отдельно. Gate: ≥19/20 eventual schema-valid, ≥18/20 semantic AC, 0 confident fabrication на false-premise controls; иначе Luna остаётся только text leaf с Sol verify. Порог — proposal, не измеренный факт.

## 8. Учёт трат — обязательный v0

### Claude arm

`claude --print --output-format json` даёт aggregate `total_cost_usd` + input/output/cache-read/cache-create. На **каждую попытку** пишется `turn_usage`:

```text
event_id = wf:<run_id>:<seq>:<attempt>
session_id = owner/caller session
scope/task_id = owner attribution
runtime/model/ok/stop_reason + exact usage + total_cost_usd
```

Failed attempt тоже строка. Если процесс умер до terminal usage, parser не разобрал usage или `turn_usage_add` не подтвердил insert/replay existing row, call переходит в `OUTCOME_UNKNOWN` с `cost_unaccounted=true`. Оплаченный result file сохраняется, но **карантинится и не поступает downstream**; следующий dispatch блокируется. Reconciliation повторно парсит raw provider JSONL и делает idempotent insert с тем же event_id; только существующая/вставленная ledger row открывает barrier. Учётная ошибка не уничтожает результат, но и не позволяет workflow продолжить с невидимой тратой.

### Codex arm

Человекочитаемый `codex exec` печатает только `tokens used`, но `codex exec --json` уже даёт `thread.started` и **один `turn.completed.usage`** с:

```text
input_tokens, output_tokens, cached_input_tokens, cache_write_input_tokens
```

Это не гипотеза: `app/codex_review_artifact.py:_record_usage` парсит именно эти поля и пишет их в `turn_usage`. Цена вычисляется существующим `_codex_cost(model, input, cached, cache_write, output)` по `CODEX_TOKEN_PRICES`; оценивать цену из одного total token count не нужно. Для неизвестной цены — `cost_unaccounted=true`, никогда `$0`.

## 9. Fable: физически неизбежный code gate

Утренние workflow state/JSONL содержат `defaultModel="claude-fable-5"`; leaf meta не задаёт model. Текущий script делает `const M='opus'` и передаёт `{model:M}` в **каждый** `agent()`: meta JSON содержит `"model":"opus"`, JSONL — `"model":"claude-opus-5"`. Значит prompt/phase description не управляет leaf model; управляет executable agent option/default.

Нужны два слоя, владелец один:

1. **Load-time fail-fast:** lane/default config не загружается, если alias разрешается в Fable/Terra/Spark/unknown.
2. **Непроходимый runtime gate:** единственная `dispatch_leaf()` после `resolve_model`, перед subprocess/API adapter, вызывает общий `ensure_agent_model_allowed(resolved, surface="workflow")`; `anthropic_fable`/Fable model IDs дают terminal `REFUSE_DISABLED_MODEL` до launch. Adapter не принимает произвольную model string — только validated typed record.

Главное: workflow JS не получает `child_process`/shell/direct provider credentials. Иначе script обойдёт gate командой `claude --model fable`. Этот dispatch seam — физически неизбежная точка. Существующий `ensure_spawn_allowed` проверяет catalog flag, но сам по себе не запрещает Fable; его надо завести на тот же hard policy owner, чтобы session workers и workflow leaves не разошлись.

## 10. Машинные потолки для workflow, запускаемого worker

Предлагаемый v0 contract (числа — architecture proposal, не готовое решение):

| Ограничение | Default / hard | Откуда число и цена ошибки |
|---|---|---|
| Agents/run | 12 / 32 | полезный run = 9; 78-agent run дал только 32 results и 46 quota failures; 12 даёт небольшой запас, 32 обрубает explosion |
| Concurrent CLI | 3 total, max 2 одного runtime | input design + laptop 16GB/~6GB available; reference 10 — API concurrency, не безопасный потолок отдельных CLI processes |
| Unique provider tokens | 25M / 50M только с explicit owner override | 9-agent useful run = 21.56M unique tokens; raw transcript rows не считать |
| Per-leaf bound | 3M tokens reserve, 20 tool rounds, 600s | делает overshoot run budget ограниченным одной leaf попыткой |
| API-equivalent virtual cost | $5 default / $10 explicit owner | это Luna-first guard, а не перенос Fable baseline: token shape полезного 9-agent run стоил $42.73 на Fable, но **counterfactual** по текущей Luna price table = $0.883 (Sol = $17.09). Реальная Luna usage неизвестна; ledger считается до следующего dispatch |
| Codex pool safety | stop before every call on readiness block; additionally stop if fresh global Codex utilization вырос на 2 pp от run-start | global delta contaminated другими consumers, поэтому это conservative safety brake, не attribution |
| Models in worker-started run | Luna default; Sol ≤2 leaves/run + authorization receipt; Opus 0; Fable/Terra/Spark hard deny | дословное требование «на лунах, солах немного» + current routing policy |
| Nesting | depth=1 | worker может запустить workflow; workflow leaf не получает workflow/spawn tools и не запускает новый workflow |
| Memory | refuse new leaf below MemAvailable 2GB; pidfd kill on timeout | уже принятый laptop safety gate |

Точный subscription percentage одной leaf из token count вывести нельзя; global readiness snapshot смешивает все машины/consumers. Поэтому pool delta — только аварийная остановка, а честная per-run величина — recorded tokens/API-equivalent cost.

## 11. Развилки с ценой — решение пользователя

Это не повтор трёх старых designs; это граница замены после живой проверки.

### A — Sidecar `wf_run` только для ephemeral work

- `run_fan` и `spawn_worker` остаются для persistent/warm/code/merge.
- Worker может запускать workflow под потолками выше.
- Manual resume после Orchestra restart: bg `run` умирает, owner получает INTERRUPTED и повторяет `--resume`.
- Изоляция I1; owner-only commit; обязательный WAL/accounting/Fable gate.
- **Build estimate:** 6–9 agent-days, ~1.4–1.8K LOC + tests (старый ориентир 4–6 дней/1.18K LOC поднят за обязательные accounting/isolation/policy pieces).
- **Цена ограничения:** не универсален; direct worker primitives пока остаются.

### B — Hybrid universal DSL

- Один script API, два leaf types: `agent()` one-shot и `worker()` persistent.
- `worker()` внутри вызывает существующие task/spawn/fan/merge sagas; warm reuse не симулируется.
- First-class run/call persistence и recovery, иначе единый DSL врёт о durability.
- **Build estimate:** 10–15 agent-days, ~2.5–3.5K LOC + migration/recovery/tests.
- **Цена ограничения:** user-facing универсальность есть, underlying сложность не исчезает.

### C — Полное вытеснение `run_fan`/child spawn

- Новый engine становится owner task/worktree/branch/warm session/barrier/merge/reconciliation.
- Требует recovery parity до rollout; bg-run/manual resume недостаточен.
- **Build estimate:** не меньше 15–20 agent-days/~4K LOC из уже проверенного Score-ориентира, вероятно выше после live parity requirements.
- **Цена риска:** новый lifecycle owner рядом с боевой SQLite и git; самый большой blast radius. Удалять старые primitives до measured parity нельзя.

## Findings с confidence

1. **CONFIRMED:** topology, journal, schema tool/retry, model choice и cache fields описаны по primary live JSONL/state/script.
2. **CONFIRMED:** raw-card и unique-request accounting считают разные predicates; одинаковый `requestId` повторяет usage fields. Исторические `$548` — user-provided earlier-cutoff snapshot; точный cutoff не был сохранён, поэтому independently UNCERTAIN.
3. **CONFIRMED:** cross-leaf first-request cache reuse низок (0–18.7%), within-leaf later reuse ≈96–98%; H2 в сильной форме refuted.
4. **CONFIRMED:** strict universal replacement refuted реальными `reuse`, durable barrier, code/merge cases.
5. **CONFIRMED:** bwrap namespace-only pairwise overhead median 4.220 ms на пяти interleaved A/B; security/runtime integration price остаётся estimate.
6. **LIKELY:** sidecar A — минимальный безопасный перенос. Причина: все low-level seams существуют, но сам runner ещё не построен.
7. **UNCERTAIN:** Luna structured/semantic compliance; ни одного Luna Workflow leaf в корпусе.
8. **UNCERTAIN:** точные build-day/LOC и pool percentage per run; это design estimates, не measurements.

## Counter-evidence и края

- Claude Workflow действительно умеет code-changing pipeline на общем main с ownership groups и owner commit; это сильнее простого «только research». Но он не даёт task/worktree/merge/restart parity и потому не опровергает границу.
- Journal обеспечивает manual replay по hash и сохраняет finished results; его нельзя назвать «не durable вообще». Недостаток уже: audit intent беден и active runner не восстанавливается автоматически через Orchestra `bg run` restart.
- Completed Fable schema agents дали 35/35 first-pass success, а Opus final-state agents eventual 59/59; schema mechanism зрелый. Это не evidence о Luna semantic correctness.
- Global 2 pp pool brake может остановить workflow из-за расхода другой машины; это намеренно fail-safe, не attribution.
- Bwrap overhead измерен только для empty process namespace setup, не для полноценного CLI with binds/tooling/auth. Он доказывает, что сама оболочка дешева, но не цену adapter integration.

## Затрагиваемые файлы и риски будущей реализации

Возможные owners после отдельного архитектурного решения: `app/bg_jobs.py`, `app/mcp_stdio.py`, `app/models.py`, `app/quota_gate.py`, `app/db.py`, `app/codex_review_artifact.py`, новый workflow runner/adapters, tests. В Phase 1 ни один из них не изменён.

Главные risks: restart kills `bg run`; различающиеся cache keys/possible cold-start stampede; shared-main write races; schema-valid/semantically-wrong Luna output; accounting reconciliation deadlock; model alias bypass; direct JS `child_process` bypass; secret-readable I1 credential bind; nested fleet explosion; global quota delta misattribution.

## Review decision inputs

- Changed files: `docs/tasks/427/research.md`, `docs/tasks/427/analyze_workflow_logs.py`; consumer — пользователь/Phase 2 architecture choice.
- Author metadata: session `research-dynwf`, `model=gpt-5.6-sol`, `backend_type=codex`, `role=full-cycle` (read-only `sessions` row).
- AC: ответить на 6 вопросов карточки + 4 уточнения; live-log quotes; third-run timestamped remeasurement; no new swarm; writes only `docs/tasks/427`; branches with cost; stop after Phase 1.
- Named checks: `python3 docs/tasks/427/analyze_workflow_logs.py`; `git diff --check`; scope check `git status --short` contains only `docs/tasks/427/`.
- Review route by `codex-debate`: high-consequence architecture without deterministic oracle technically asks Sol, but auxiliary Sol was not authorized. Использованы два допустимых Luna rounds по изменённой прозе; no Sol call.

## Review outcome

- Round 1: 2 blocking (online credential path; fail-closed accounting) + 6 precision/completeness findings.
- Все 8 проверены и исправлены: I1/I2 threat boundary, accounting quarantine/reconciliation, Luna-first cost interpretation, historical `$548` scope, per-agent schema order, namespace-only microbenchmark, pairwise median, cache-cause confidence.
- Round 2: `CLEAN — все предыдущие findings FIXED; новых блокирующих проблем нет.`
- Completed-verdict evidence проверено локально: нормализованная reviewer quote `Без disjoint ownership два agents могут перезаписать друг друга до owner commit.` найдена в `research.md`.
- Один follow-up envelope был отвергнут MCP до model call из-за отсутствующего literal `PROJECT CONTEXT`; это tool attempt, не review round.
- Полный artifact: `docs/tasks/427/review-research-luna.md`.

## Источники

[1] Task #427 full card via `task_get("427")`, fetched 2026-09-01.

[2] `docs/tasks/dynwf/research.md` — accepted prior design/code map input, commit named in task card.

[3] Live agent JSONL and journals under `~/.claude/projects/-mnt-data-Projects-Python-orchestra/bd702267-a0db-42f2-8808-b0d43e37ced3/subagents/workflows/` — primary runtime records.

[4] Saved scripts/state under the sibling `workflows/` directory — primary topology/progress/model records.

[5] `/mnt/data/Projects/Python/orchestra/data/orchestra.db`, read-only SQL over `logs`/`sessions` — three `run_fan` calls and seven child-spawn applications.

[6] Current source: `app/mcp_stdio.py`, `app/fan_barrier.py`, `app/bg_jobs.py`, `app/models.py`, `app/codex_review_artifact.py`, `app/backend_codex.py`, `app/db.py`.

[7] Local interleaved A/B command output for bwrap, recorded in this document; loadavg printed on every arm.
