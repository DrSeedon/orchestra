# Self-improvements in modern agentic systems: что применимо к Orchestra

**Источник:** Zhe Ren et al., *Self-Improvements in Modern Agentic Systems: A Survey*,
arXiv:2607.13104v1, 14 июля 2026 [1].
**Дата анализа:** 18 июля 2026.
**Scope:** только Phase 1 — исследование и рекомендации; реализация не выполнялась.

## Короткий вывод

Orchestra уже содержит почти все **субстраты** self-improvement из статьи — prompts,
explicit memory, tools, control logic, worktrees, tests и human approval. Но это пока набор
полезных компонентов, а не замкнутый self-improvement loop. Не хватает трёх связок:

1. **измеримого сигнала** о том, что именно стало лучше или хуже;
2. **верифицируемого update operator**, который превращает сигнал в минимальный candidate patch;
3. **promotion gate** с held-out/regression-проверкой, версионированием и rollback.

Поэтому следующий шаг — не более автономный генератор правил и не Darwin Gödel Machine.
Сначала нужен маленький evaluator-gated цикл для prompt/skill updates. Без него автоматизация
лишь быстрее записывает ошибки в CLAUDE.md, worker memory или tool documentation.

Главное уточнение к исходному mapping пользователя:

- **RAG — не весь Memory Improvement.** Он закрывает memory objects, indexing и Read, но почти
  не закрывает outcome-driven Create/Update/Delete, credit assignment и maintenance.
- **`📝 RULE` — валидный минимальный сигнал для prompt improvement, но модуль сам по себе ещё
  не self-improvement operator.** Пока правило только предложено, долговременная конфигурация
  агента не изменилась. Human-approved запись превращает flow в human-in-the-loop qualitative
  prompt refinement.
- **Skill Creator и MCP — инфраструктура tool creation/integration, не tool self-improvement.**
  Нет автоматического сигнала «tool docs/схема/обёртка вызвали повторяющийся сбой» и gated
  refinement по этому сигналу.
- **Full-scaffold update уже частично присутствует организационно:** агент может изменить код
  Orchestra в worktree, прогнать тесты и Codex review, после чего человек мержит patch. Но trigger,
  benchmark и promotion остаются человеческими; непрерывного self-induced loop нет.

## 1. Что именно исследовалось

### 1.1 Полнота чтения

PDF скачан напрямую с arXiv. Файл содержит **97 PDF-страниц**: основной текст и conclusion
занимают печатные страницы 1–57, далее идут references. Полностью прочитаны Sections 1–10;
библиография просканирована для разрешения ссылок и названий методов. Визуально проверены первая
страница пользователя и отрендеренные страницы с Table 2 (prompt paradigms), Table 4 (memory
CRUD/governance), Figure 10 (full scaffolding) и Section 8.1 (evaluation). Это не анализ abstract
или чужого summary.

### 1.2 Framed question

- **Context:** Orchestra — Python/FastAPI оркестратор persistent Claude/Codex agents с prompt
  pipeline, semantic RAG, MCP tools, git worktrees, тестами и human merge.
- **Change under test:** добавить bounded self-improvement на scaffold-level.
- **Baseline:** текущие ручные CLAUDE.md/skills/MCP edits, prompt-only `📝 RULE`, RAG и
  per-task `self-analysis`.
- **Outcome:** меньше повторных ошибок и tool misuse на held-out задачах при фиксированном
  token/tool/time budget, без regression ранее решённых задач и без роста safety violations.

### 1.3 Гипотезы и falsifiers

**H1 — Orchestra уже является self-improving system.** Она верна, если реальное выполнение
само порождает signal, durable update и проверяемое улучшение следующей версии scaffold без
ручного переноса между стадиями. Falsifier: хотя бы одна из стадий отсутствует или update не
измеряется.

**H2 — Orchestra имеет хорошие scaffold primitives, но не closed loop.** Она верна, если prompts,
memory, tools и patch isolation существуют, однако promotion зависит от человека и отсутствуют
held-out/regression metrics. Falsifier: код содержит outcome-driven update/promotion pipeline с
историей версий и regression gate.

**H3 — следующий лучший шаг — open-ended self-modifying agent.** Она верна, если evaluator уже
надёжен, task distribution репрезентативен, candidate exploration окупается, а rollback/safety
доказаны. Falsifier: evaluator и attribution ещё не построены либо дешёвые component-level updates
закрывают тот же bottleneck.

**Результат:** H1 и H3 **REFUTED**, H2 **CONFIRMED**. Это следует из сопоставления survey definition
с кодом и из отсутствия измеримого promotion loop.

## 2. Система координат статьи

Статья задаёт agent state как `A_t = (theta_t, Sigma_t)`, где `theta` — параметры foundation
model, а `Sigma = (prompt, memory, tools, control logic)` — operational scaffold. Self-improvement
требует не просто transient reflection, а **durable update** `A_t -> A_(t+1)` на основе сигналов
собственного исполнения [1, §§3–4].

Два основных пути:

1. **Foundation Model Improvement:** обновление weights через self-generated demonstrations,
   intrinsic evaluative feedback или extrinsic experience [1, §5].
2. **Scaffolding Improvement:** frozen FM, но durable updates prompts, memory, tools или whole
   control program [1, §6].

Для Orchestra применим почти исключительно второй путь. При этом сигналы из FM-раздела — tests,
verifiers, critiques, successful/failed trajectories — можно использовать для scaffold updates,
не меняя weights.

## 3. Полная карта применимости к Orchestra

### 3.1 Foundation Model Improvement

| Идея статьи | Статус для Orchestra | Что всё же можно переиспользовать | Confidence |
|---|---|---|---|
| Intrinsic generative demonstrations + SFT | **Не применимо:** closed FM subscriptions, доступа к weights/training loop нет | Исторические successful/failed traces использовать как eval cases для prompts/skills | **CONFIRMED** — project policy + [1, §5.1] |
| Intrinsic rubric/preferences/critique + RL/DPO | **Не применимо на weight-level** | Rubric/Codex critique как signal для candidate scaffold patch | **CONFIRMED** — [1, §5.2] |
| Consistency/self-certainty rewards | **Не внедрять как единственный gate** | Disagreement использовать как uncertainty trigger для human review | **CONFIRMED** — survey прямо отмечает confident-wrong/correlated-error risk [1, §5.2] |
| Grounded exploratory experience + RL | **Weights — нет** | Pytest, compile errors, tool errors и task outcomes — лучшие сигналы для scaffold evaluator | **CONFIRMED** — [1, §§5.3, 7.1] |
| Simulated world models | **Не применимо сейчас** | Только для будущих browser/GUI sandboxes; core Orchestra не нуждается в learned simulator | **LIKELY** — [1, §5.3.2] + текущий scope |
| Parametric distillation scaffold skills -> model | **Не применимо** | Сохранять explicit skills/playbooks; это единственный доступный durable substrate | **CONFIRMED** — [1, §9.1] |

Практический вывод: FM-раздел — не roadmap реализации, а каталог signal types и failure modes.
Особенно полезны quality filtering, external verification, generator/evaluator separation и
сохранение regression anchors.

### 3.2 Prompt Improvement

Статья различает четыре режима [1, §6.1, Table 2].

| Режим | Что уже есть | Gap | Рекомендация | Confidence |
|---|---|---|---|---|
| Scalar-feedback search | Ручные prompt edits; тесты отдельных задач | Нет prompt benchmark, fixed budget, baseline/candidate comparison | Сделать evaluator для role/module prompts; оптимизировать pass rate **и** token/tool/time cost | **CONFIRMED** — [1, §§6.1.1, 8.1] |
| Qualitative-feedback refinement | `📝 RULE`, Codex review, `self-analysis`, retros | Нет structured proposal registry, dedup, promotion outcome | Сохранить human gate; добавить structured candidate + source signal + lifecycle | **CONFIRMED** — код + [1, §6.1.2] |
| Population-based evolution | Ничего; обычные ветки дают несколько альтернатив вручную | Нет дешёвого evaluator, дорого и легко overfit | Не делать сейчас; допустить маленький 2–3 candidate sweep только после evaluator | **LIKELY** — [1, §6.1.3] |
| Textual gradients | Codex findings и retro root causes уже являются directional feedback | Feedback не преобразуется автоматически в минимальный patch и не валидируется | Weakness -> minimal delta -> regression gate -> human merge | **CONFIRMED** — [1, §§6.1.4, 9.1] |

Две особенно практичные идеи:

1. **MAPS / Prompt Alchemist:** failure cases превращаются в reusable natural-language rules для
   model-specific prompt optimization [1, §6.1.2; 3]. Для Orchestra полезен сам pattern
   «кластер ошибок -> минимальное правило», а не его domain-specific test-generation pipeline.
2. **ACE:** context следует обновлять incremental deltas через Generator–Reflector–Curator, а не
   переписывать целиком. Авторы отдельно указывают на brevity bias и context collapse при iterative
   rewriting [2]. Это прямо относится к CLAUDE.md, role prompts и worker memory.

### 3.3 Memory Improvement

#### Что уже есть

- Explicit processed trails: `docs/tasks/**`, retros и reports.
- Curated project state: CLAUDE.md, BUGS.md, worker memory.
- Raw episodic evidence: SQLite logs.
- Vector + lexical retrieval: bge-m3 int8 + sqlite-vec + FTS5 + RRF в
  `app/rag.py:629-674`.
- Project isolation: `search_memory` берёт scope из env, а не из аргумента агента
  (`app/mcp_stdio.py:729-757`).
- Файловый corpus сознательно ограничен `.md` (`app/rag.py:50-56`); source code RAG не заявлен.

Это сильнее «просто RAG», но survey loop `Create -> Organize -> Read -> Act -> Evaluate ->
Update/Delete` закрыт лишь частично [1, §§6.2.1–6.2.3].

#### Gap matrix

| Memory dimension | Orchestra сейчас | Gap / действие | Confidence |
|---|---|---|---|
| Object | raw logs + explicit distilled docs + embeddings | Сохранять связь distilled lesson -> raw evidence/log ids | **CONFIRMED** — [1, §6.2.1] |
| Structure | flat files/logs + vector/FTS hybrid; естественная directory hierarchy | Graph memory и отдельная semantic hierarchy пока не оправданы | **LIKELY** — текущий corpus + [1, §6.2.2] |
| Create | files/logs индексируются автоматически | Нет saliency/utility score; почти всё полезное создаётся человеком/agent report | **CONFIRMED** — код + [1, §6.2.3] |
| Read | RRF hybrid search | Нет result id, use feedback, recency/importance, measured retrieval precision | **CONFIRMED** — `RagMemory.search()` возвращает content/path, не feedback handle |
| Update | reindex по sha и изменение файла | Нет outcome-driven strengthening, conflict resolution, scheduled review | **CONFIRMED** — код + [1, §6.2.3] |
| Delete | исчезнувший file prunes index; ручная чистка docs | Нет безопасного evidence-preserving forgetting policy | **CONFIRMED** — код + [1, §6.2.3] |

Критическая контр-проверка: отдельная работа 2026 года показала, что repeated LLM consolidation
может сначала повысить utility, затем опустить её ниже no-memory baseline; episodic-only control
оказался конкурентоспособным, а forced consolidation — хуже [8]. Поэтому survey-рекомендацию CRUD
нельзя трактовать как «дать агенту авто-delete/rewrite». Для Orchestra безопасный вариант:

- raw episode/source остаётся immutable evidence;
- curator предлагает incremental merge/supersede;
- auto-delete shared memory запрещён;
- promotion требует held-out utility/regression check;
- stale/contradictory entry помечается, а не физически стирается до human audit.

**Итог по Memory:** RAG — **частично CONFIRMED memory scaffold**, но self-improving memory loop —
**REFUTED как уже реализованный**.

### 3.4 Tool Improvement

Статья делит tool governance на routing, refinement и creation [1, §6.3].

| Идея | Orchestra сейчас | Практический вывод | Confidence |
|---|---|---|---|
| Dynamic tool routing | Skills статически назначаются role через `pipeline.yaml`; MCP pool задаётся spawn/config | Сначала telemetry. Vector routing/pruning не нужен при маленьком curated pool | **LIKELY** — `pipeline.yaml:17-79` + [1, §6.3.1] |
| Iterative refinement | Ошибки видны в logs; wrappers/docs правятся вручную; Codex review есть | Агрегировать повторные tool errors и делать one-shot minimal doc/schema/wrapper patch | **CONFIRMED** — [1, §6.3.2] |
| Interface alignment | MCP docstrings и schemas являются agent-facing API | Это наиболее дешёвый и полезный tool improvement для Orchestra | **CONFIRMED** — DRAFT [4] |
| Autonomous creation | Skill Creator, plugin/skill files и MCP servers создаются по запросу | Оставить on-demand + tests + Codex/human gate; не разрешать live self-install | **CONFIRMED** — [1, §6.3.3] + security constraints |
| Protocol integration | MCP уже стандартный transport/interface | Сильная сторона; улучшать registration/validation, а не изобретать новый protocol | **CONFIRMED** — код + [1, §6.3.3] |

DRAFT показывает практический loop: collect tool interaction trails -> analyze failures -> rewrite tool
documentation [4]. Для Orchestra не нужен постоянный evolutionary loop. Достаточно срабатывать на
повторяемый signature: wrong argument, unknown affordance, ordering error, timeout/misleading return.
Candidate меняет сначала docstring/schema; wrapper code — только если execution evidence показывает
реальный bug.

### 3.5 Full Scaffolding

Survey описывает bounded full-scaffold update как candidate program patch, который принимается только
если verifier пропускает его [1, §6.4, Eq. 25].

**Что уже есть в Orchestra:** git worktrees, отдельные branches, tests, Phase gates, Codex review, human
merge/rollback. Когда agent меняет сам Orchestra или её prompts/tools, это уже human-governed
full-scaffold improvement pipeline.

**Чего нет:** execution traces не запускают weakness mining автоматически; нет stable scaffold benchmark;
candidate не сравнивается с current version под одинаковым budget; acceptance не измеряет transfer и
regressions.

DGM подтверждает, что archive + empirical benchmark может улучшать coding-agent scaffold, но его
open-ended tree search затратен и применял sandbox/human oversight [5]. Более близкий к Orchestra
шаблон дают supplementary 2026 papers:

- GRASP принимает bounded skill edit только при net gain на balanced held-out probe и hard regression
  budget; абляция авторов связывает gain именно с gate, а не с skill writing [6].
- Self-Harness использует Weakness Mining -> minimal Harness Proposal -> held-out Regression Validation
  [7].

**Рекомендация:** позже пилотировать один bounded role prompt/skill library, не весь codebase. Никаких
автоматических merge, restart или production deployment.

### 3.6 Evaluation и critic governance

Это самый важный раздел статьи для Orchestra [1, §§8–9]. Любой self-improvement claim должен иметь:

- baseline и полную performance trajectory, не только лучший финальный score;
- fixed token/tool/time/human budget;
- held-out tasks, не использованные для генерации patch;
- regression set ранее решённых случаев;
- несколько повторов/seed там, где model variance существенна;
- safety/tail-risk indicators;
- отдельный final evaluator, если другой judge использовался для optimization;
- version history, rejection log и rollback.

Статья отдельно называет critic attack surface: generator не должен сам принимать собственный patch;
изменения critic/tests должны быть monotone/additive и human-audited [1, §9.1].

Здесь у Orchestra есть новый конкретный риск: default `worker` и `full-cycle` сейчас используют
`gpt5.6sol` (`pipeline.yaml:48-70`), а MCP `codex_review` тоже запускает GPT-5.6 Sol. Для Claude worker
это cross-family critic; для Codex worker — только отдельная session того же model family. Это лучше
ничего, но **не обеспечивает evaluator independence**. Для self-improvement acceptance нужен
diversified critic routing:

- proposer Claude -> Codex critic;
- proposer Codex -> Claude Opus/Fable critic;
- programmatic tests остаются первичным oracle там, где они возможны.

Cross-family LLM critique уменьшает correlated-error risk, но не является независимым oracle: оба judge
могут иметь общие данные и сходные biases. Реальную независимость дают executable checks, frozen held-out
cases и разделение proposal/promotion authority; LLM cross-review — дополнительный critic, не gate истины.

**Confidence: CONFIRMED** — актуальная конфигурация кода + evaluator-separation requirement [1, §§8.1.2,
9.1].

### 3.7 Идеи из Applications и Future Directions

Остальные практически применимые идеи статьи не требуют отдельных подсистем:

- **Software engineering as arena:** использовать repository sandbox, pytest/linters/CI и reversible
  worktrees как основной executable oracle; это лучший domain для первого pilot [1, §7.1].
- **Web/GUI drift:** для dashboard и computer-use изменений держать Playwright smoke cases с изменёнными
  viewport/state и запрещать irreversible actions вне sandbox [1, §§7.2, 7.6].
- **Active exploration:** приоритизировать случаи с частыми failures или verifier disagreement, а не
  генерировать случайные «улучшения» [1, §§3.3, 9.2].
- **Resource-constrained improvement:** дешёвый deterministic invariant/regex filter должен стоять перед
  дорогим LLM judge; improvement budget включает tokens, tool calls, wall time и human review [1, §§8.1,
  9.2]. Это совпадает с AI Efficiency principle Orchestra.
- **Multi-agent co-evolution:** agents могут обмениваться только versioned artifacts — regression tests,
  approved skills, tool wrappers и patches — через git/docs registry. Свободное распространение
  unverified memories создаёт cascade risk [1, §9.2].
- **Distribution drift:** при смене model version, MCP schema или UI повторно запускать held-out smoke suite;
  старый pass нельзя считать вечным доказательством [1, §9.2].

## 4. Что на самом деле делает текущий `self-improvement` module

`pipelines/default/prompts/modules/self-improvement.md:1-29` загружается во все четыре роли. Он:

1. просит LLM распознать явную correction;
2. сформулировать одно обобщаемое `📝 RULE`;
3. предложить, куда его записать;
4. запрещает silent write и требует human approval.

### Классификация по статье

Это **reactive, agent-decided, human-gated qualitative-feedback prompt refinement**. В терминах
survey signal `S_t` уже возник, но `U_Sigma` ещё не завершён:

- не одобрено/не записано -> feedback artifact, не durable self-improvement;
- человек одобрил и patch применён -> human-in-the-loop scaffolding improvement;
- само правило «заметил correction -> предложи rule» является meta-level skill, но оно не изменяет
  tools, model weights или whole scaffold.

Поэтому ответ на вопрос «примитивный scaffolding improvement или больше?»:

> **Это хороший минимальный front-end scaffolding improvement loop, но не complete self-learning
> system.** Он умнее простой заметки, потому что выполняет abstraction и routing proposal, однако
> не имеет structured persistence, dedup, evaluator, promotion, regression и maintenance.

### Сопоставление с `self-analysis`

`self-analysis` заметно ближе к статье: он берёт Codex/test/retry/correction signals, требует root cause,
пишет Tier-1 retro/worker memory и только предлагает Tier-2 prompt edits
(`pipelines/default/prompts/skills/self-analysis.md:13-45`). Но он тоже:

- не сравнивает behavior before/after;
- не проверяет worker-memory append на held-out tasks;
- не делает periodic cross-task consolidation/forgetting;
- не гарантирует evaluator independence для Codex workers; отдельная same-family session — только
  diversified critique.

Эти два механизма надо сохранять раздельно: `📝 RULE` — дешёвый реактивный capture; `self-analysis` —
artifact-grounded per-task analysis. Над ними нужен общий registry/curator/evaluator, а не третий
параллельный формат правил.

## 5. Что доказали #84 и #85 — и что не доказали

### Проверенные факты

- #85: loose regex gate дал precision **0.42** (TP=21, FP=29); single-stage regex -> Haiku
  pipeline был **REFUTED**: только 47% полезных outputs [I2].
- На genuine corrections Haiku extraction был полезен в **14/14**, correct-null ещё в 4/4;
  `confidence` не отделял полезные правила от hallucinated [I2].
- Поэтому technical fallback — tight regex prefilter -> correction classifier -> extractor -> human
  gate, а не regex -> extractor [I2].
- После этого comparative analysis #85 рекомендовал сначала prompt-only A, затем structured tool B,
  если A покажет >=70% detection recall на live corrections [I3]. Именно A сейчас реализован.
- #84 прошёл Research и Plan gate; user approved DB table design для Phase 2 planning. **Phase 3
  implementation approval не найден**. В анализируемом checkout `5d72eb2` нет запланированных
  `app/self_learning.py`, `learnings` table и `SELF_LEARNING_ENABLED`; команды и exit codes сохранены в
  [I7]. Это доказывает отсутствие именно planned pipeline в этом checkout, но не делает утверждений об
  unmerged branches или внешних repositories. Формулировка «plan ready but implementation not approved»
  для текущего кода остаётся корректной.

### Новый live-log замер

**Гипотеза до запроса:** prompt-only A пригоден, если на genuine corrections recall >=70%; proposal
precision должна быть измерима.
**Read-only выборка:** production SQLite logs после commit, вынесшего module в отдельный файл
(2026-06-27 18:10 +07), до 2026-07-18 16:20 +07.

- user messages: **1,441**;
- rows с literal `📝 RULE:`: **12**;
- breakdown: `tool_result=6`, `user_message=3`, `tool=3`, `text=1`.

Этот corpus **не позволяет вычислить recall или precision**: нет structured event «correction detected»,
proposal id, approve/reject и source user-message id; tool/tool_result могут быть чтением документа или
duplicate transport, а не proposal. Менять pass criterion после просмотра данных нельзя.

**Вывод: UNCERTAIN.** Prompt-only A установлен, но его detection reliability до сих пор не доказана.
Следующий шаг — observability/labeling, а не возврат к автоматическому Haiku pipeline и не auto-write.

## 6. Конкретный action plan

Оценка сложности: **S** = до 1–2 инженерных дней, **M** = 3–5 дней, **L** = 1–2 недели,
**XL** = более 2 недель/исследовательская программа. Это estimate, не measurement.

### P0 — зафиксировать evaluation contract и измерить prompt-only слой (S, 1–2 дня)

**Что сделать:** до проектирования storage зафиксировать offline benchmark и promotion contract над
logs и историческим #85 dataset:

- связать correction/user message -> следующий agent response;
- фиксировать structured `proposal_id`, source log id, trigger/action/avoid/target;
- вручную разметить небольшой held-out набор real corrections/non-corrections;
- метрики: detection recall, proposal precision/usefulness, duplicate rate, approval rate, time-to-decision;
- сохранить исходный threshold #85: >=70% recall, не подгонять после результата;
- определить immutable case format, held-in/held-out split, fixed token/tool/time budget, hard regression
  budget и decision states `pass/reject/inconclusive`;
- version каждого evaluator run должен включать dataset, rubric/oracle, model и budget.

**Зачем первым:** сейчас невозможно отличить «модуль работает» от «инструкция почти всегда игнорируется»;
без frozen contract registry преждевременно закрепит случайное поле `evaluator_result`.

### P1 — минимальный scaffold regression evaluator (M, 4–5 дней; blocked by P0)

Сделать общий evaluator skeleton для prompt/skill/tool-doc candidates:

- baseline vs candidate на одинаковых cases и budgets;
- held-in cases дают evidence для patch, held-out решают promotion;
- hard regression budget на ранее решённых cases;
- executable checks первичны; LLM judge только при отсутствии oracle;
- judge model/rubric/budget логируются, `inconclusive` не превращается в pass;
- Claude/Codex cross-family routing используется как **diversified critic**, не как independent oracle;
- candidate/rejected outcome сохраняется; rollback — git/version pointer.

**Это главный dependency** для registry schema и любого auto-promotion. Он прямо следует из survey
[1, §§8–9], GRASP [6] и Self-Harness [7].

### P2 — единый `learnings` registry в observe-only mode (M, 3–4 дня; blocked by P0–P1)

Восстановить полезную часть плана #84 без auto-extraction:

- SQLite `learnings`: id, source log/session/agent, kind, target, trigger, action, avoid, status,
  created/decided timestamps, supersedes/duplicate-of, evaluator run/version/result;
- MCP `propose_improvement` и role-gated approve/reject;
- agent-decided detection остаётся; никаких Haiku calls на каждый message;
- approval пока только меняет status, не патчит shared prompt автоматически;
- хранить source pointer/hash и минимальный excerpt, не raw prompt/session dump;
- project-scoped access; secret/PII redaction до durable write; untrusted source provenance не может
  стать executable instruction без promotion;
- pending/rejected получают явный TTL/archive policy; approved evidence сохраняется по version history;
  должны быть deletion/export semantics для project data.

**Acceptance evidence:** proposal связан с raw source; duplicate не создаёт второе active правило;
неавторизованный worker не может approve shared change; secrets/raw dumps отсекаются; expiry/export/delete
проверяются тестами; никакое registry event само не меняет production prompt.

### P3 — Curator и gated promotion (M/L, 4–6 дней; blocked by P1–P2)

ACE-like low-frequency job:

- Generator извлекает candidate deltas из approved proposals и recurring retro signals;
- Reflector проверяет contradiction/scope/evidence;
- deterministic Curator делает incremental merge, не whole-file rewrite;
- raw evidence сохраняется; stale entries получают `superseded`, не silent delete;
- shared Tier-2 changes проходят regression evaluator + human approval;
- прошедший offline candidate сначала идёт в shadow mode или на одну ограниченную role/model cohort;
  canary failure автоматически возвращает current version до следующего human decision;
- n=1 остаётся local/observational; promotion требует recurrence или severe verified signal.

Не запускать после каждого turn. Периодический offline batch снижает cost и context churn.

### P4 — RAG governance telemetry, без auto-delete (M, 3–5 дней)

- вернуть result ids и scores из `search_memory`;
- логировать query, candidates, selected/unused, latency, source age/type;
- добавить explicit low-friction feedback только если agent реально может его соблюдать;
- построить offline report: miss/noise/stale/conflict/duplicate;
- сначала curator proposals; physical deletion только после human approval;
- benchmark: held-out memory questions + poisoning/privacy/regression cases.

Graph memory, latent memory и новый vector DB не нужны. Bottleneck сейчас — utility feedback, не
embedding quality.

### P5 — tool-documentation refinement из повторных ошибок (M, 3–5 дней)

- агрегировать tool call failures по tool + error signature + argument mismatch;
- после >=N повторов предложить **один** minimal doc/schema patch;
- replay на stored calls + targeted tests;
- Codex/Claude cross-review + human merge;
- wrapper code менять только когда replay доказывает bug, а не misunderstood docs.

Это cheap DRAFT-like loop [4]. Dynamic top-k tool routing отложить до доказанного overload tool pool.

### P6 — bounded Self-Harness pilot на одной роли (L, 1–2 недели; blocked by P1–P3)

Выбрать один узкий target, например full-cycle prompt или `search_memory` usage policy:

1. weakness mining по traces;
2. 2–3 diverse minimal patches;
3. held-out regression evaluation под fixed budget;
4. shadow replay, затем canary на одной role/model cohort с automatic fallback;
5. human selection/merge;
6. performance trajectory и rollback.

Цель пилота — проверить evaluator и attribution, не «самоэволюцию Orchestra».

### P7 — только после доказанного пилота

- small population prompt search;
- cross-agent sharing of verified skills/tests/tool wrappers;
- active exploration по verifier disagreement/frequent failures;
- limited dynamic tool routing при сотнях доступных tools;
- candidate scaffold archive.

Open-ended codebase evolution, automatic merge/restart/deploy и self-modifying critic — **не включать**.

## 7. Что явно не применимо или не стоит внедрять сейчас

| Направление | Вердикт | Причина |
|---|---|---|
| FM fine-tuning, SFT, RLHF/RLAIF/RLVR, DPO | **Не применимо** | Нет weights/training API; subscription-only policy; другой product scope |
| Parametric consolidation в local model | **Не сейчас** | Нет validated dataset/evaluator; инфраструктура и regression risk несоразмерны |
| Latent/KV-cache memory | **Не применимо** | Closed inference runtimes; хуже inspectability/auditability |
| Learned world model | **Не сейчас** | Core environment уже исполнимый и наблюдаемый; pytest/log replay дешевле и точнее |
| Graph memory | **Не сейчас** | Maintenance complexity, structural drift; текущий corpus закрывается hybrid retrieval |
| Aggressive memory CRUD/auto-delete | **Не внедрять** | Counter-evidence о degradation при repeated consolidation [8] |
| Dynamic routing по огромному tool pool | **Не сейчас** | У Orchestra маленький role-curated set; сначала telemetry |
| Fully autonomous tool creation/install | **Не внедрять** | Supply-chain, permission и persistence risks; оставить worktree/tests/human gate |
| Population prompt evolution | **Отложить** | Compute-heavy, evaluator ещё не построен, высок риск benchmark overfit |
| DGM/open-ended full scaffold evolution | **Не сейчас** | Нужны robust benchmark, archive economics, isolation, regression/safety proof [5] |
| Games, robotics, scientific-lab loops | **Не применимо core Orchestra** | Application domains статьи, не текущий product environment |

## 8. Риски и counter-evidence

1. **Self-critique может ухудшать outputs.** Survey фиксирует noisy critiques, correlated blind spots и
   confident wrongness [1, §§5.1–5.2]. Поэтому `self-analysis` правильно требует external signal.
2. **Context collapse:** repeated full rewrite теряет детали; ACE предлагает incremental curation [2].
3. **Memory degradation:** repeated consolidation может уничтожить полезную episodic evidence [8].
4. **Judge gaming/Goodhart:** optimizer и final judge нельзя оставлять одной конфигурацией [1, §8.1.2].
5. **Benchmark overfit:** prompt/skill может улучшить training cases и ухудшить transfer [1, §§8.1, 9].
6. **Human approval — не measurement.** Он защищает от очевидного мусора, но человек не воспроизводит
   десятки held-out tasks на каждый rule.
7. **Model specificity:** один prompt/skill может помогать Opus и вредить Sol. Evaluator должен хранить
   target model/version; ACE и Self-Harness отдельно подчёркивают model-specific behavior [2, 7].
8. **Security persistence:** prompt injection в memory/tool docs превращает transient exploit в durable
   scaffold vulnerability [1, §9.1]. Нужны provenance, permission tiers и immutable raw evidence.
9. **Cost:** improvement loop может стоить дороже предотвращённых ошибок. Поэтому fixed budget и
   cheap invariant/regex gates перед LLM judge обязательны [1, §§8–9].

## 9. Affected files для будущего plan (не реализация)

Вероятный минимальный surface:

- `app/db.py` — learnings/evaluation schema;
- `app/mcp_stdio.py` — propose/approve/reject и reviewer routing;
- `app/session_turns.py` — только telemetry hook, если agent-decided tool недостаточен;
- `app/rag.py`, `app/rag_service.py`, `app/routes/memory.py` — retrieval ids/telemetry/feedback;
- новый `app/scaffold_eval.py` — baseline/candidate/held-out/regression runner;
- новый `app/routes/learnings.py` — human decision API;
- `pipelines/default/prompts/modules/self-improvement.md` — structured tool call вместо свободного
  текста только после P0 measurement;
- `pipelines/default/prompts/skills/self-analysis.md` — output в общий registry, не новый формат;
- `pipelines/default/prompts/skills/codex-debate.md` или новый generic cross-review policy — diversified
  reviewer по backend family;
- `tests/` — correction detection, permissions, dedup, evaluator regression, memory poisoning,
  tool-doc replay.

Не трогать до отдельного plan approval: production restart/deploy, FM backends, automatic shared-prompt
write, automatic delete, automatic code merge.

## 10. Confidence summary

- **CONFIRMED:** Orchestra имеет scaffold primitives, но не durable evaluator-gated closed loop.
- **CONFIRMED:** RAG реализует explicit objects + hybrid Read, но не outcome-driven full memory loop.
- **CONFIRMED:** `📝 RULE` — qualitative prompt-refinement proposal; durable self-improvement появляется
  только после commit approved change.
- **CONFIRMED:** evaluator/regression gate — приоритет выше нового generator.
- **CONFIRMED:** FM improvement недоступен в текущей closed-weight/subscription архитектуре.
- **LIKELY:** tool-doc refinement даст больше value, чем dynamic routing на текущем размере tool pool.
- **UNCERTAIN:** current prompt-only module надёжно замечает corrections; live logs не имеют нужной
  observability для recall/precision.
- **REFUTED для checkout `5d72eb2`:** planned pipeline #84 был реализован. В tracked code отсутствуют
  заявленные service/table/flag; Phase 3 implementation approval не найден [I7].
- **REFUTED:** prompt-only `📝 RULE` и RAG уже образуют полноценную self-learning system.

## 11. Adversarial second opinion

Codex получил local-only задачу опровергнуть выводы, не используя web summaries. Первый раунд признал
карту применимости и приоритет evaluator-gate обоснованными, но поставил один blocking: отсутствие
planned implementation #84 было описано по невоспроизводимому repository search. Он также потребовал
поставить evaluator contract до registry schema, не называть cross-family LLM judge независимым, добавить
shadow/canary и определить data governance registry.

Исправления внесены в Sections 3.6, 5–6 и отдельный [I7] manifest. В Round 2 Codex отметил все шесть
findings как `FIXED`, новых blockers не нашёл и дал verdict `APPROVED`. Полный след сохранён в
`docs/tasks/self-improve-survey/codex-review-research.md`.

Ограничение review: это diversified model session, не независимый executable oracle. Штатный MCP
`codex_review` дважды не завершился (context overflow после лишнего web search; затем неверный checkout
для `.codex/config.toml`); использован read-only direct CLI fallback, а platform bug зарегистрирован.

## Sources

### Primary/external — все страницы открыты в этой research session

1. Ren et al. (2026), *Self-Improvements in Modern Agentic Systems: A Survey* —
   https://arxiv.org/abs/2607.13104 ; full PDF https://arxiv.org/pdf/2607.13104
2. Zhang et al. (2026), *Agentic Context Engineering: Evolving Contexts for Self-Improving
   Language Models* — https://arxiv.org/abs/2510.04618
3. Gao et al. (2025), *The Prompt Alchemist: Automated LLM-Tailored Prompt Optimization for Test
   Case Generation* — https://arxiv.org/abs/2501.01329
4. Qu et al. (2024/ICLR 2025), *From Exploration to Mastery: Enabling LLMs to Master Tools via
   Self-Driven Interactions (DRAFT)* — https://arxiv.org/abs/2410.08197
5. Zhang et al. (2026 v3), *Darwin Gödel Machine: Open-Ended Evolution of Self-Improving Agents* —
   https://arxiv.org/abs/2505.22954
6. Moll et al. (2026), *GRASP: Gated Regression-Aware Skill Proposer for Self-Improving LLM Agents* —
   https://arxiv.org/abs/2605.29668
7. Zhang et al. (2026), *Self-Harness: Harnesses That Improve Themselves* —
   https://arxiv.org/abs/2606.09498
8. Zhang et al. (2026), *Useful Memories Become Faulty When Continuously Updated by LLMs* —
   https://arxiv.org/abs/2605.12978

### Internal evidence

- **[I1] Current reactive module:** `pipelines/default/prompts/modules/self-improvement.md:1-29`.
- **[I2] Experiment #85:** численные результаты в `docs/tasks/85/experiment-results.md:1-77`;
  полный внутренний отчёт — `docs/experiments/85/report.md`.
- **[I3] A-vs-B decision:** `docs/tasks/85/approach-comparison.md:152-204`.
- **[I4] Current per-task mechanism:** `pipelines/default/prompts/skills/self-analysis.md:13-45`.
- **[I5] RAG implementation:** `app/rag.py:50-56`, `app/rag.py:629-710`,
  `app/mcp_stdio.py:729-757`.
- **[I6] Role/model/skill routing:** `pipelines/default/pipeline.yaml:17-79`,
  `app/prompting.py:54-84`, `app/prompting.py:183-210`.
- **[I7] #84 approval trace and checkout manifest:** `docs/experiments/85/results.jsonl`
  (source record `log_id=195392`) and reproducible commands/output in
  `docs/tasks/self-improve-survey/local-evidence.md`.
