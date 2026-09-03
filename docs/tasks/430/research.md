# #430 — SKILL.state против append-only истории на задачах Orchestra

Дата среза: 2026-09-01. Фаза: 1, research + benchmark construction. Production-реализация не начиналась.

## Вопрос

- **Context:** единственный управляемый нами agent loop — `app/harness/loop.py`; Claude SDK и Codex CLI владеют диалогом сами и не дают честно заменить его память.
- **Change under test:** вместо полной истории на каждом model step передавать только skill specification, текущее изменяемое JSON-state и последнее observation; ответ — JSON ровно с `state_patch` и `action`, после патча reasoning не сохраняется.
- **Baseline:** нынешняя OpenRouter Harness-механика накапливает OpenAI messages, включая assistant reasoning blocks и tool results, пока context guard не удалит старые complete assistant/tool units.
- **Outcome:** парное изменение provider-reported total tokens и качество решения на frozen эпизодах из реальных задач Orchestra; provider availability измеряется отдельно и не считается ни успехом, ни ошибкой модели.

## Короткий ответ

**Выигрыш на наших задачах пока НЕ ИЗМЕРЕН.** Механика потенциально режет растущий prompt, но два замороженных пилота на единственном format-valid бесплатном route дали **0/3 полностью сопоставимых случаев каждый**. Поэтому минимальная экономия токенов и допустимая деградация качества остаются `null`; выводить числа из неполных шагов было бы подгонкой [5][6].

Benchmark-конструкция определена ниже. Она отвечает именно на вопрос о представлении памяти, а не на общий вопрос «какая модель лучше». Следующий одобряемый план должен сначала закрыть calibration gate на стабильном route и исправить case action vocabulary; production `AgentLoop` менять до этого нельзя.

## Гипотезы и фальсификаторы

### H1 — SKILL.state выигрывает

**Гипотеза:** mutable structured state уменьшит повторно передаваемый prompt, потому что старые observations и reasoning заменяются bounded working set, не ухудшая сохранение решений.

**Фальсификатор:** на frozen full benchmark верхняя односторонняя 90% граница отношения total tokens не проходит noise-derived порог либо нижняя 90% граница качества ниже noise-derived non-inferiority margin; любой `critical_reason_loss` также отвергает H1.

### H2 — экономия меньше шума

**Альтернатива:** patch/output overhead и вариативность reasoning съедят уменьшение prompt; observed delta окажется не больше same-arm A/A шума.

**Фальсификатор:** paired state-arm saving на полном корпусе имеет верхнюю 90% границу ratio ниже `1 - η_tokens`, где `η_tokens` заморожен из пилотного A/A.

### H3 — state опасно теряет причинную историю

**Альтернатива:** mutable patch сохранит текущий ответ, но потеряет причины принятых решений и отвергнутых вариантов; качество просядет прежде всего на research/architecture/incident/high-risk задачах.

**Фальсификатор:** в каждой опасной stratum state-arm имеет `critical_reason_loss=0` и не хуже append-arm по frozen reason fields в пределах `η_quality`.

### H4 — простой append baseline уже достаточно защищён

**Альтернатива:** нынешний context guard, который сохраняет все system/user anchors и новые complete assistant/tool units, предотвращает практическую деградацию; state даст лишь небольшую экономию.

**Фальсификатор:** state-arm проходит token threshold и одновременно не хуже baseline по quality/critical reasons на эпизодах, реально доходящих до guard-shaped длины.

## Findings

### F1 — production baseline не бесконечно append-only

`AgentLoop.run()` дописывает user, guard, assistant и tool messages в общий `history`; `_one_round()` возвращает в следующую посылку provider `reasoning_details`. При 85% context budget `_fit_context()` оставляет все system/user anchors и самые новые полные assistant/tool units, а `SessionStore.replace_messages()` атомарно заменяет persisted snapshot [2].

**Confidence: CONFIRMED — tier 2 primary source, текущий код открыт и прочитан.**

Следствие: честный baseline полного бенчмарка — «append до guard, затем текущая structural truncation», а не бесконечная строка. Пилот ниже guard проверяет только ранний режим.

### F2 — внешний prior положительный, но не переносимый без замера

По проверенным пользователем первичным числам статьи публичные задачи на Gemini-3-Flash дали state-arm экономию 23–60% и +6–11 п.п. качества; простой prose-summary control на τ-Retail упал до 29.9% против 48.2% ReAct [1]. В нашей базе отдельный замер также показывает, что стоимость хода в основном растёт от round trips и повторной передачи context, а не от длины финального ответа [3].

**Confidence: LIKELY для направления эффекта, UNCERTAIN для Orchestra — paper facts supplied as verified, но наш runtime/model/corpus отличаются и локального A/B нет.**

### F3 — transport canary недостаточен

Живой canary дал HTTP 200 и `cost=0` на всех 3 exact-free routes: Nano, Cohere North Mini Code и Dots 3 Note. На идентичном exact-two-key format canary только Nano вернула валидный JSON; Cohere и Dots исчерпали `max_tokens=700` с invalid JSON [4].

**Confidence: CONFIRMED — tier 1 direct measurement, `availability-canary.json` и `format-canary.json`.**

Следствие: future preflight обязан иметь два гейта: provider transport и task-shaped schema completion. «HTTP 200 на `OK`» не доказывает пригодность измерительного пути.

### F4 — оба пилота непригодны для оценки эффекта

Первый pilot сделал 33 HTTP requests: 26 дали non-empty `choices`, 7 — HTTP-200 без `choices`; ни один из трёх cases не завершился во всех `append/state/append_repeat` arms. Второй заранее ограниченный pilot сделал 21 request: 12 с `choices`, 9 HTTP-200 payloads с embedded code 502 `ResourceExhausted`; все 9 episode arms в итоге попали в provider bucket и полных троек снова 0. Вместе: **54 requests, 38 request-level provider successes, 16 malformed/provider-error responses, 0 comparable cases** [5][6].

**Confidence: CONFIRMED — tier 1 direct measurement; raw JSONL, агрегат `pilot-audit.json` и per-case/per-arm `pilot2-episode-outcomes.json`.**

`minimum_total_token_saving=null` и `quality_noninferiority_margin=null` — не недописанные поля, а правильный результат pre-registered правила «нет completed A/B/A control → нет threshold» [6].

### F5 — HTTP status нельзя использовать как provider-success predicate

Во втором pilot все 9 ResourceExhausted пришли с outer HTTP 200, `payload.error.code=502` и без `choices`. Проверка только `status_code < 400` переклассифицировала бы их в model outcomes и повторила дефект #422 [6][7].

**Confidence: CONFIRMED — tier 1 direct measurement плюс независимый исторический counterexample #422.**

### F6 — первая версия deterministic judge дала ложные model errors

Pilot manifest показывал модели только `final_action_keys`, но gold ожидал нераскрытые enum-like строки. В P01 append-arm корректно вернул «remove data/vec.db», сохранил `current.db/search_memory`, объяснил, что `current.db` — FTS, и правильно дал 0/6 wins; exact grader поставил `field_score=0.4`, потому что ожидал скрытые коды `DELETE_DATA_VEC_DB`, `KNOWLEDGE_CURRENT_DB_AND_SEARCH_MEMORY`, `CURRENT_DB_IS_FTS_NOT_VECTOR` [5].

**Confidence: CONFIRMED — tier 1 artifact comparison; фактический action и gold лежат в `pilot-summary.json`/`pilot_cases.json`.**

Следствие: full cases обязаны до первого response раскрывать тип и полный enum vocabulary каждого action field. Семантический judge не нужен; deterministic judge сравнивает объявленные коды/нормализованные sets. Первый pilot навсегда исключён из quality/noise calibration.

### F7 — опасный класс задач существует у нас, а не только в статье

Опасный класс: **research/architecture, incident diagnosis и shared-runtime/security/persistence решения, где rejected option с причиной является safety invariant.** Три pilot cases взяты из реальных примеров:

- #419: «удалить `current.db`» отвергнуто, потому что это FTS, а не vector store; потеря причины повторяет удаление не того файла;
- #422: 5/30 отозвано из-за grading after failed call; потеря причины возвращает ложный результат;
- #416: «worker branch пуст» отвергнуто после очистки dirty target; потеря причины снова направляет диагностику в здоровую ветку [8][9][10].

**Confidence: CONFIRMED для наличия класса — tier 2 task artifacts; UNCERTAIN для частоты/дельты качества до full benchmark.**

Mutable state сам по себе не защищает ledger: recursive merge может заменить array или удалить ключ. Поэтому reason retention — отдельный oracle, не доверие формату JSON.

### F8 — боевой контур не затронут

`sessions` в `/home/kesha/orchestra/data/orchestra.db` read-only: **467 → 467** между 17:05:22 и 17:48:05 Europe/Berlin. Pilot scripts не импортируют DB/application storage и пишут только в owned task paths [11].

**Confidence: CONFIRMED — tier 1 direct measurement.**

## Frozen full benchmark design

### 1. Population и N

**N=30 episodes, 6 из каждой stratum:**

1. research/architecture with competing hypotheses;
2. shared-runtime/auth/persistence/high-risk;
3. incident diagnosis with causal reversals;
4. closed behavioral code change;
5. read-only extraction/docs/delivery control.

Population: Git-tracked completed Orchestra tasks before frozen cutoff, with accepted artifact plus enough timestamped evidence to build 8–12 observations. Exclude cases needing live provider/quota/production DB or external writes. Classifier runs top-down; within stratum choose first six by `sha256("skillstate430-v1:" + task_id)`.

N=30 is screening, not a precise estimate of a 6–11 p.p. effect. It is the largest balanced 5-stratum matrix whose worst-case 12-step two-arm run is 720 requests; pilot/canary/control budget stays below the already used 900-attempt safety ceiling. Before sampling, publish a population ledger with eligible count, each exclusion reason/count, per-stratum count and the selected/eligible fraction. Report broad cluster intervals; do not market N=30 as representative or as equivalence proof without that ledger.

### 2. Episode construction

- Source only chronological observations supported by accepted `research.md/plan.md/report.md`, raw evidence, or current KB fact.
- Preserve corrections as distinct events; never pre-summarize them into a gold narrative.
- Easy/control strata may have no reversal; dangerous strata require at least one accepted decision with reason and one rejected/superseded option with reason.
- Each case manifest freezes: source hash, observations, action schema, every allowed enum, normalized set fields, gold action, critical keys, forbidden resurrected values.
- Model has no repository, task report, solution diff, DB, network or hidden answer access. Controller action vocabulary is the same in both arms.

Frozen state schema uses keyed objects, not replace-all decision arrays:

```text
objective
current_facts.<fact_id> = {value, status, evidence_event}
decisions.<decision_id> = {status, because, reopen_if, evidence_events}
open_questions.<question_id>
artifacts.<artifact_id>
next_action
```

Patch semantics are exact: a non-object patch replaces its target; an object patches a dict recursively; `null` deletes; arrays/scalars replace. Validator rejects unknown top-level paths, arrays under `current_facts`/`decisions`, deletion of an existing decision, emptying `because`, or changing accepted/rejected directly to the opposite state (only `superseded` is allowed, with a new evidence event). Invalid patch is a model outcome and is never applied partially.

### 3. Arms

**A — current-history control:** same system skill specification, all prior observations, all prior assistant JSON and provider reasoning blocks; current `AgentLoop` guard semantics apply if the episode reaches the guard.

**B — SKILL.state:** same skill specification, current JSON state and latest observation only; controller applies recursive merge patch, discards response reasoning and earlier messages.

Both arms pin exact model route/version, temperature, seed policy, max tokens, action schema and controller. No arm-specific tool or extra hint. Before the first response each rendered request records hashes of the common system specification, disclosed action schema/enums/normalizers, tool/action vocabulary and controller parameters; validator permits only the declared memory payload difference. If a route changes, the whole cohort restarts under a new benchmark revision; arms from different models are never joined.

### 4. Ordering

- Model calls are sequential, not concurrent.
- Within each case: strict A/B/A/B by step; which arm goes first is balanced by frozen hash.
- Cases rotate round-robin instead of completing one arm block at a time.
- Record `loadavg`, timestamp, prompt/completion/total tokens and provider response model on every request.

Task-local audits confirm contiguous recorded sequences and the scheduled rotating primary A/B order on every pilot step where both primary arms reached a request: 3 comparable steps in pilot 1 and 6 in pilot 2. Provider failures explain unequal final arm counts. The pilot did **not** record rendered surface hashes, so identical schema/tool/controller delivery is an explicit full-benchmark preflight, not a claimed pilot proof [12].

### 5. Provider outcome before model outcome

Call buckets are mutually exclusive:

1. `provider_404`;
2. `provider_429`;
3. `provider_timeout`;
4. `provider_upstream_error` — includes outer HTTP 200 with `payload.error` or empty `choices`;
5. `provider_malformed_success` — no error but response envelope unusable;
6. `provider_success` — non-empty `choices`, no payload error, exact requested route.

Only bucket 6 reaches the second, model-output classifier: `model_valid`, `model_invalid_json`, `model_invalid_top_keys`, `model_invalid_patch`, or `model_wrong_action`. Thus valid provider transport plus invalid JSON is a model outcome, while empty `choices`/payload error never is. A task enters paired capability metrics only if both A and B complete all steps through bucket 6. Availability rates and tokens spent before provider failure remain a separate operational table by arm; they are not silently dropped.

### 6. Judge and success

The judge is **deterministic code**, not an LLM:

- every model step parses to an object with exactly `state_patch` and `action`;
- final action has exactly the manifest keys and only disclosed enum/set values;
- every gold field is exact after declared normalization;
- no forbidden withdrawn/rejected value is resurrected;
- all critical decision/rejection reason codes are present.

Task success requires all five. Secondary quality = exact-field score; report critical-reason loss separately. Luna may review manifest-to-source completeness before the freeze, but it never grades outputs and never sees arm labels.

Controls before responses:

- accepted historical answer passes;
- no-op/withdrawn answer fails;
- swapping current and withdrawn codes fails;
- removing one critical reason fails;
- both arms on an empty observation have identical prompt-independent judge result;
- prompt-delivery check parses the exact rendered first request and proves every manifest enum plus every normalization rule is present before the first response;
- case/gold/source hashes stay unchanged after first response.

### 7. Token and quality estimands

- Primary token metric: sum of provider `total_tokens` over a completed episode.
- Decomposition: prompt tokens and completion/reasoning tokens separately.
- Primary quality metric: paired task success on completed provider pairs.
- Secondary quality: paired exact-field score and critical-reason losses, clustered by task.
- Provider availability is its own estimand, by arm and failure bucket.

### 8. Absolute thresholds from pilot noise

Calibration pilot has six frozen 8-step cases (at least one from every stratum), with `append`, `state`, and interleaved `append_repeat` on the same cases/model/seed policy. Fewer than six completed three-arm cases means calibration failure and leaves both thresholds `null`.

For completed pilot case `i`:

```text
token_noise_i = |T_append_i - T_append_repeat_i| / mean(T_append_i, T_append_repeat_i)
quality_noise_i = |Q_append_i - Q_append_repeat_i|
η_tokens = max(token_noise_i)
η_quality = max(quality_noise_i)
```

`max` here is deliberately a **conservative heuristic guard over the completed A/A pilot**, not a 90% estimator of the noise distribution. Publish every A/A discrepancy and the pilot sample count; do not attach a confidence label to `η`. Freeze exact numeric `η_tokens`/`η_quality` before the full run. Full acceptance requires:

1. upper one-sided 90% cluster-bootstrap bound of `T_state / T_append` `< 1 - η_tokens`;
2. lower one-sided 90% bound of `Q_state - Q_append` `>= -η_quality`;
3. `critical_reason_loss_state = 0`;
4. no provider bucket is relabeled as a model result.

Current values are **undefined (`null`)**, not zero: two exploratory 3-case pilots had no completed three-arm case and also predated the six-case calibration minimum. A stable route/stateless model path and a new frozen calibration revision are prerequisites.

## Counter-evidence and limits

- User-supplied public-benchmark results argue that structured state can improve both tokens and accuracy; our failed free-route pilot does not refute the paper [1].
- The state mechanism differs from prose summarization; the bad τ-Retail summary control does not by itself argue against structured state.
- Closed-world replay isolates memory but does not prove end-to-end repository editing, tool error recovery or test quality. A later implementation decision must not generalize beyond this seam.
- Exact JSON/value vocabularies reduce judge ambiguity but make protocol compliance part of quality; disclose all allowed values to avoid the pilot's hidden-code false negative.
- Free Nano has extreme availability/format variance and weak external validity. A Luna run through Codex CLI is not an equivalent substitute because that runtime retains its own history and cannot expose the same memory treatment.
- Mutable state can be smaller while becoming confidently wrong. Total tokens alone never pass without reason-retention and forbidden-resurrection checks.
- Current Harness replays signed/provider reasoning details for tool-round compatibility. A production state loop may need a fresh-call boundary rather than deleting blocks inside an active provider conversation; this remains an implementation risk, not a Phase-1 conclusion.

## Affected files, risks, edge cases

Potential Phase 2 benchmark-only work:

- `scripts/skillstate430/` — case builder, frozen manifest validator, interleaved runner, deterministic grader;
- `docs/tasks/430/` — protocol, raw receipts, calibration and analysis;
- `app/harness/` — **do not change until benchmark gate passes**; later candidates would touch `loop.py`, persistence/session format and tests.

Risks:

- state patch deletes/replaces a decision ledger;
- patch grows without bound and recreates history cost;
- current fact and audit history get conflated;
- provider error envelope masquerades as HTTP success;
- action enum is hidden or changed after freeze;
- current context guard makes A different from the assumed baseline;
- provider availability differs by prompt length and therefore by arm;
- model-specific result fails to transfer to other runtimes.

## Review outcome

One fresh Luna completeness/adversarial pass completed with **no blockers** [13]. Evidence of artifact reading is the exact quote “Mutable state can be smaller while becoming confidently wrong.” Seven non-blocking findings were accepted: request-order evidence, exact patch semantics, envelope-vs-JSON split, population fractions, honest max-noise calibration label, per-arm receipt, and prompt delivery of enums/normalizers. The research was updated accordingly. No second round: only suggestions changed, and `codex-debate` permits follow-up for a verified blocker/dispute, not to seek another approval.

## Sources and measurements

1. **[U1, supplied verified primary-source facts]** User's task statement for arXiv 2608.26263: mechanics, Appendix A.4 and Table 4 numbers. Per instruction, not re-fetched or re-verified.
2. **[S2, tier 2 primary code]** `app/harness/loop.py:69-100,106-192,197-239,360-427`; `app/harness/sessions.py:44-92`.
3. **[S3, tier 1/2 internal measurements]** `docs/kb/token-efficiency.md`, established findings and open local A/B gap.
4. **[M4, tier 1 direct measurement]** `docs/tasks/430/availability-canary.json`; `format-canary.json`; scripts under `scripts/skillstate430/`.
5. **[M5, tier 1 direct measurement]** `docs/tasks/430/pilot-summary.json`; `pilot-raw.jsonl`; frozen cases `scripts/skillstate430/pilot_cases.json`.
6. **[M6, tier 1 direct measurement]** `docs/tasks/430/pilot-protocol.json`; `pilot2-summary.json`; `pilot2-raw.jsonl`; `pilot-audit.json`.
7. **[S7, tier 1 historical measurement]** `docs/tasks/422/report.md`, especially withdrawn 5/30 and corrected 2/30 after provider-success-first reconciliation.
8. **[S8, tier 2 accepted task artifact]** `docs/tasks/419/report.md`; `docs/kb/agent-memory-architecture.md`.
9. **[S9, tier 2 accepted task artifact]** `docs/tasks/422/report.md`; `docs/kb/auto-work.md`.
10. **[S10, tier 2 accepted task artifact]** `docs/tasks/416/research.md`; `docs/tasks/416/report.md`.
11. **[M11, tier 1 direct measurement]** `docs/tasks/430/prod-db-count-before.txt` and `prod-db-count-after.txt`: `sessions 467 → 467` via SQLite read-only URI.
12. **[M12, tier 1 direct measurement]** `docs/tasks/430/pilot-order-audit.json`; `pilot2-order-audit.json`; `pilot2-episode-outcomes.json`. Both order audits pass; both honestly record `rendered_surface_hashes_captured=false`.
13. **[R13, independent Luna review]** `docs/tasks/430/review-research-luna.md`: no blockers, exact artifact quote, seven suggestions folded into this revision.
