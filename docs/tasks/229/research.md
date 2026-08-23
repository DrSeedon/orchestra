# #229 — текущая end-to-end логика выбора reviewer и worker model

## Вопрос и границы

Контекст: текущий checkout Orchestra на 2026-08-23, где выбор reviewer проходит через MCP `codex_review`, а создание worker — через MCP `spawn_worker` и HTTP/manager session path.

Изменение под проверкой: не изменение policy, а восстановление фактического поведения и расхождений между code, canonical Markdown, pipeline manifest, historical research и observed use.

Baseline: исторический Sol-default для review и прежний prompt-only routing, которые могли быть переписаны последующими commits.

Измеримый исход: для каждого surface зафиксированы текущий owner, decision-maker, omitted/default, accepted/rejected models, quota/admission, effort source и proof command/output.

Метод: сначала прочитан KB (`docs/kb/README.md`, `docs/kb/codex-runtime.md`, `docs/kb/prompt-delivery.md`, `docs/kb/evidence-methods.md`), затем current code/manifest/prompts, полный corpus hit-scan, git history/blame и WAL-safe SQLite snapshot через `sqlite3.Connection.backup()`. Raw prompts, secrets и full log contents не сохранялись.

## Corpus protocol и размер

Команда полного scan:

```text
rg -l -i --glob 'docs/tasks/**/*.md' 'codex review|codex_review|reviewer model|Luna|Sol|model-routing|spawn_worker.*model|model.*spawn_worker' docs/tasks | sort
```

Результат после создания этого артефакта: **752 Markdown-файла** с хотя бы одним hit. Классификация по типу артефакта дала:

| Класс | Правило классификации | Файлов |
|---|---|---:|
| canonical/foundational research | `research.md` или `audit.md` | 163 |
| implementation reports | `report.md` | 131 |
| individual review artifacts | basename/путь с `codex-review` или `review-` | 231 |
| unrelated incidental mentions | остальные файлы | 227 |

Классификация — счёт файлов с hit, а не число строк или claims; один файл относится ровно к одному классу по указанному порядку.

Минимально требуемые load-bearing материалы прочитаны: #289, #304, #199, #208, #187, #176, #177, #118, `docs/kb/codex-runtime.md`, `docs/kb/prompt-delivery.md`. Исторические claims не считаются current без проверки git blame/history и current code.

## Evidence matrix — только факты

| surface | current canonical MD owner + exact line | current code owner + exact line | decision-maker | omitted/default behavior | accepted/rejected models | quota/admission behavior | effort source | contradiction/staleness | proof command/output |
|---|---|---|---|---|---|---|---|---|---|
| `codex_review` fresh: signature/default | `pipelines/default/prompts/skills/codex-debate.md:8-11` называет skill owner; `:70-83` описывает explicit reviewer | `app/mcp_stdio.py:2407-2427` signature/docstring; `_CODEX_REVIEW_DEFAULT_MODEL` `:798-800` = `gpt-5.6-luna` | Server default + `_resolve_codex_review_model()` | Omitted Python arg binds Luna (`:2413`); no caller-side selection required | Resolver canonicalizes alias; non-Codex and Spark rejected (`:803-852`) | Readiness checked before worker lookup/bg job (`:2441-2444`) | No effort argument or effort flag in review command; `:2479` builds only `codex -m <review_model>`; CLI/config default is outside this code path | Skill says the omitted call remains Sol at `pipelines/default/prompts/skills/codex-debate.md:82-83`, stale after commit `9a1e2d10` | `nl -ba app/mcp_stdio.py \| sed -n '798,852p;2407,2444p'` → Luna constant, resolver, fresh preflight |
| `codex_review` explicit model | Skill examples `pipelines/default/prompts/skills/codex-debate.md:70-75` use aliases `gpt5.6luna` / `codex` | `app/mcp_stdio.py:815-852`; aliases in `app/models.py:154-194` | Server resolver, not prompt | Explicit value replaces default; aliases resolve before runtime/quota checks | Registered `runtime=codex` and `quota_bucket_for_model == codex`; Spark (`codex_spark`) rejected; Claude/Grok/unknown rejected (`:823-850`). Other registered Codex models (Terra, GPT-5.5/5.4/mini) pass this resolver | Model-specific readiness is queried after validation (`:880-890`) | None selected by MCP review code | Skill narrows prose to Luna/Sol, while code accepts every registered non-Spark Codex model | `nl -ba app/models.py \| sed -n '84,113p;154,194p'; nl -ba app/mcp_stdio.py \| sed -n '803,852p'` → registry/aliases/resolver |
| `codex_review` resume and stale fallback | Skill says repeat same model on resume (`pipelines/default/prompts/skills/codex-debate.md:122-124`) | `app/mcp_stdio.py:2463-2466` loads UUID only for `resume`; `:2479`, `:2495-2513`, `:2522-2552` use same `review_model` for resume and fresh fallback; `:2583-2589` persists same model | Server uses requested model again on each call | `resume=True` with no stored UUID becomes fresh (`:2465-2466`); stale UUID shell fallback starts fresh with same model (`:2503-2510`, `:2542-2552`) | Same resolver acceptance/rejection as fresh | Same `_quota_refusal(review_model)` before session lookup/job (`:2441-2444`) | No review effort selected in fresh or resume shell command | Historical #304 correctly asserted propagation, but its Sol default is superseded | `nl -ba app/mcp_stdio.py \| sed -n '2463,2552p;2572,2592p'` → UUID/fallback/usage-model paths |
| `spawn_worker` MCP omitted | `pipelines/default/prompts/modules/model-routing.md:2-20` tells agent to choose class; `pipelines/default/prompts/modules/orchestration.md:81,117` says keep manifest default / call tool | `app/mcp_stdio.py:893-917` | Caller agent is instructed to choose; server enforces presence | Empty string or omitted `model` raises `ApiToolError invalid_argument` before HTTP (`:912-917`) | No model registry resolution occurs in MCP function; explicit raw value is forwarded (`:918-926`) and later manager/API validates | `planned_initial_turn=True` is forwarded; manager performs admission for non-orchestrator (`app/manager.py:694-714`) | Manager resolves role effort after model is canonical (`:736-740`); omitted cannot reach this stage | Prompt says “or omit model” at module `:8-10`, directly contradicted by code rejection | `nl -ba app/mcp_stdio.py \| sed -n '893,926p'` → required-model error |
| `spawn_worker` MCP explicit | Module is sole prompt owner for routing class (`model-routing.md:1-21`) | `app/mcp_stdio.py:918-970` forwards `model` to `POST /api/sessions`; no model selection branch | Caller chooses alias/id; HTTP/manager chooses whether valid/allowed | Explicit string required; alias may be passed | Manager/API canonicalizes via `resolve_model`; accepted if registered and agent availability flag permits; unknown/disabled rejected in manager/API | Initial admission is requested via `planned_initial_turn=True`; no prompt can bypass server gate | Pipeline role map after canonical model; `resolve_effort` exact model → runtime → default | No code router maps task class to Luna/Sol/Opus; prompt policy is advisory only | `nl -ba app/mcp_stdio.py \| sed -n '918,970p'` → body includes caller model |
| Manager `_create_session_locked` | `app/pipeline.py:1-9` says manifest is role/prompt source; `pipelines/default/pipeline.yaml:4-5` has `defaults.model: opus` | `app/manager.py:565-585` canonicalizes passed model and applies `ensure_spawn_allowed` for `parent_name`; `:604-623` resolves role/pipeline; `:687-714` validates spawn/admission | Manager enforces passed model; it does not choose from `defaults.model` | Manager method requires positional `model`; no omission/default branch | `resolve_model(model)` (`:579`); agent-side availability gate for child (`:583-585`); runtime chosen by `backend_for_model` (`:736-737`) | For planned non-orchestrator only: unknown quota is allowed; only `require_worker_admission` blocked state raises (`:694-714`) | `get_role(...).effort` + `resolve_effort(raw_effort, model, bt)` (`:738-740`) | Manifest `defaults.model` is catalog/default data, not consumed here as fallback | `nl -ba app/manager.py \| sed -n '565,623p;687,740p'` → passed model is resolved before role/effort |
| HTTP manager session creation / root orchestrator | `pipelines/default/pipeline.yaml:36-41,52-57,68-73,84-96,110-115` gives role model fields; `skills/orchestra-agents.md:52-71` describes API creation and role default | `app/routes/sessions.py:121-155` `CreateSessionRequest.model` defaults to `claude-sonnet-5[1m]`; validator resolves it; `:244-271` passes it unchanged to manager | Pydantic request default, then manager | Omitted HTTP model becomes Sonnet, not manifest `defaults.model=opus` and not role model; explicit `model` wins | Any registered model passing `validate_model`; manager then applies dashboard visibility when no parent (`manager.py:583-585`) | `planned_initial_turn` controls manager admission; root orchestrators skip worker admission (`manager.py:694-695`) | Same role effort map after request model | `skills/orchestra-agents.md:69-71` says omit versioned id and role default; code’s omitted request default is Sonnet. Pipeline role model is not an automatic API fallback | `nl -ba app/routes/sessions.py \| sed -n '121,155p;244,271p'` → default Sonnet and unchanged forwarding |
| Pipeline role manifest/defaults | `pipelines/default/pipeline.yaml:1-20` says manifest owns role defaults and effort mapping | `app/pipeline.py:493-521` merges `defaults` into `ResolvedRole`; `:524-538` resolves effort only | Manifest resolver supplies role catalog/model/effort; manager consumes role effort, not model fallback | `defaults.model=opus`; orchestrator/sub-orchestrator/worker/full-cycle role model = `claude-opus-5[1m]`; reducer = `gpt-5.6-luna` (`pipeline.yaml:36-41,52-57,68-73,84-96,110-115`) | Manifest validates model key if present (`pipeline.py:245-250`) | Manifest does not itself admit quota; manager/session gate does | Exact role model → runtime → `default` effort (`pipeline.py:524-538`) | `defaults.model=opus` and role `model=...` look like selection defaults but are informational unless caller/API supplies model; direct manager path has no fallback | `/mnt/data/Projects/Python/orchestra/.venv/bin/python -c ... resolve_role(...)` → role models/effort cards recorded below |
| Prompt-only worker policy | `pipelines/default/prompts/modules/model-routing.md:3-20` | No corresponding task-class router in `app/mcp_stdio.py`/`app/manager.py`; `spawn_worker` only checks non-empty model (`mcp_stdio.py:912-917`) | Prompting agent | Prompt says Luna default, Sol only complex/Luna-inadequate, Opus special, Terra/Fable forbidden, Spark narrow | Prompt text recommends aliases/classes; server accepts/rejects by registry/flags, not by task class | Prompt references quota consequences but receives no live utilization; manager admission only checks chosen model | Worker effort is code/manifest, not prompt choice | Prompt’s “or omit model” and “manifest default” claims are false for MCP spawn; “Terra/Fable do not use” is not code enforcement (Terra is accepted if registered and enabled) | `rg -n 'model-routing|def spawn_worker|ensure_spawn_allowed|resolve_effort' pipelines/default/prompts app/mcp_stdio.py app/manager.py` → policy and enforcement are separate seams |
| Assembled orchestrator/sub-orchestrator prompt | `pipelines/default/pipeline.yaml:36-67` modules include `model-routing`; `roles/sub-orchestrator.md:1-11` is role text; `modules/orchestration.md:223-225` refers to single block | `app/pipeline.py:568-590` assembles layers/modules; dynamic manager additions in `app/manager.py:324-354` | `build_system_prompt` composes; manager adds dynamic catalog/models/workers for orchestrator | Static build contains model-routing; skill files are a separate connect-time projection, not part of `build_system_prompt`. Sub-orchestrator role file exists as tracked pipeline prompt | Same prompt-only recommendations; no runtime model selection | Dynamic `available_models_block()` lists enabled agent models (`app/models.py:769-784`), not quota utilization | Role effort card in manifest | Role prompt does not override manager model passed at creation | `/mnt/data/Projects/Python/orchestra/.venv/bin/python` measurement: orchestrator 56,714 B; sub-orchestrator 51,730 B; both `model-routing=True`, marker `codex-debate=True` only because base text mentions the skill, `codex_review=False` (full prompt not printed) |
| Assembled worker/full-cycle/reducer prompt | `pipeline.yaml:68-123`; worker role contains no model-routing module (`:74-75`), full-cycle contains it (`:97-98`); reducer has no modules (`:115-117`) | `app/pipeline.py:568-590` | Static composer; manager/session injects prompt | Worker/full-cycle skill files are projected separately; worker has no model-routing module, full-cycle has it, reducer has neither module nor skill | Prompt-only content differs by role; server model acceptance remains shared | Reducer has no worker routing prompt but role model is Luna; admission is manager-side if planned and non-orchestrator | Same manifest effort map for all roles | String markers in assembled text do not prove skill injection; role manifest model is not enforced fallback | Measurement: worker 26,724 B (`model-routing=False`, `codex-debate=True` marker only); full-cycle 58,188 B (`model-routing=True`, `codex-debate=True` marker); reducer 10,521 B (`model-routing=False`, `codex-debate=True` marker only; `skills=[]`, `modules=[]`) |
| Skill projection: tracked owner vs `.codex` | Tracked owner is `pipelines/default/prompts/skills/codex-debate.md`; `docs/kb/prompt-delivery.md` documents pipeline source | `app/prompting.py:195-217,222-267`; `app/session.py:1330-1375`; `app/workspace.py:400-446` | Pipeline source + runtime injector; tracked repo files win | `.codex/skills/.../SKILL.md` is generated/ignored, not owner; Codex gets native project skill on connect; tracked destination is never overwritten | Skill content copied only if destination untracked; Claude uses `.claude`, Codex `.codex` (`prompting.py:204-217`) | No quota selection in projection | No effort selection in projection | A copy can be stale until backend connect; current copy was byte-identical in this checkout | `git ls-files pipelines/default/prompts/skills/codex-debate.md .codex/skills/codex-debate/SKILL.md; git check-ignore -v .codex/skills/codex-debate/SKILL.md; cmp -s ...; echo $?` → tracked owner listed; `.codex` ignored; `cmp` exit 0 |
| Immediate delegation / DIY gate | `pipelines/default/prompts/modules/orchestration.md:19-22` says research spawns without asking; `:49-60` says research/report artifacts delegate and unclear scope is not DIY; `:62-82` routes research to `full-cycle`; `:256-262` workflow starts by deciding workers vs DIY; `roles/orchestrator.md:4-7` says DIY only through exact gate, delegate the rest | No code owner for ordering: `app/backend_claude.py:61-69,447-455,914-918` blocks Agent/Task and scheduling, but does not block Bash/read before `spawn_worker`; `app/backend_codex.py:2235-2238` disables native multi-agent but does not enforce first-action delegation | Prompt asks orchestrator to decide; runtime only mechanically blocks selected tools, not this decision | Current prompt does not require an immediate spawn before any discovery command; `base.md:57` says large exploration “may delegate” | N/A to model acceptance; parent still must select a model if it spawns | No admission until the spawn request reaches manager; no pre-spawn quota gate | Parent’s managed-session effort comes from role map; current parent DB row is Sol/xhigh | The prompt was delivered but is not fully operational: research-specific lines require delegation, while “may delegate” and workflow “decide if need workers” leave timing to model judgment; no code guard exists | Live DB proof (no prompt/log body): parent `Orchestra-orchestrator` = `gpt-5.6-sol`, `role=orchestrator`, `effort=xhigh`, prompt 69,550 B; prompt markers DIY/research/model-routing all present. From 10:26–10:35 parent made 21 Bash scans with `rg`/`docs/tasks`, 264 unique marked Markdown paths and 2,257 result lines; first `spawn_worker` was 10:36:35 |

The matrix’s shorthand proof cells for role assembly and skill projection point to the exact commands and byte-only outputs in `§ Reproducible evidence probes`; no prompt body is used as evidence.

## Reproducible evidence probes (output excludes prompt/log bodies)

### Assembled role prompts

Exact command:

```text
/mnt/data/Projects/Python/orchestra/.venv/bin/python - <<'PY'
from app.pipeline import build_system_prompt, load_pipeline, resolve_role
for role in ['orchestrator','sub-orchestrator','worker','full-cycle','reducer']:
    p = build_system_prompt('default', role)
    rr = resolve_role(load_pipeline('default'), role)
    markers = {x: (x in p) for x in ('<model-routing>', 'codex-debate', 'codex_review', 'spawn_worker')}
    print(role, len(p.encode()), markers, rr.model, rr.effort, rr.modules, rr.skills)
PY
```

Output (role model, effort map, modules and skills are metadata; prompt text is not printed):

```text
orchestrator 56714 {'<model-routing>': True, 'codex-debate': True, 'codex_review': False, 'spawn_worker': True} claude-opus-5[1m] {'claude-opus-5[1m]': 'high', 'gpt-5.6-sol': 'xhigh', 'gpt-5.6-luna': 'high', 'default': 'high'} ['model-routing', 'git-workflow', 'orchestration', 'worker-lifecycle', 'background-jobs', 'task-management', 'self-improvement', 'memory-search'] ['codex-debate', 'eli5', 'grill-me', 'html-artifacts', 'orchestra-agents', 'vps-deploy']
sub-orchestrator 51730 {'<model-routing>': True, 'codex-debate': True, 'codex_review': False, 'spawn_worker': True} claude-opus-5[1m] {'claude-opus-5[1m]': 'high', 'gpt-5.6-sol': 'xhigh', 'gpt-5.6-luna': 'high', 'default': 'high'} ['model-routing', 'git-workflow', 'orchestration', 'worker-lifecycle', 'background-jobs', 'task-management', 'self-improvement', 'memory-search'] ['codex-debate', 'eli5', 'orchestra-agents']
worker 26724 {'<model-routing>': False, 'codex-debate': True, 'codex_review': False, 'spawn_worker': True} claude-opus-5[1m] {'claude-opus-5[1m]': 'high', 'gpt-5.6-sol': 'xhigh', 'gpt-5.6-luna': 'high', 'default': 'high'} ['code-quality', 'git-workflow', 'report-format', 'self-improvement', 'memory-search'] ['codex-debate', 'html-artifacts']
full-cycle 58188 {'<model-routing>': True, 'codex-debate': True, 'codex_review': False, 'spawn_worker': True} claude-opus-5[1m] {'claude-opus-5[1m]': 'high', 'gpt-5.6-sol': 'xhigh', 'gpt-5.6-luna': 'high', 'default': 'high'} ['model-routing', 'research-method', 'code-quality', 'git-workflow', 'worker-lifecycle', 'report-format', 'self-improvement', 'memory-search'] ['codex-debate', 'html-artifacts']
reducer 10521 {'<model-routing>': False, 'codex-debate': True, 'codex_review': False, 'spawn_worker': True} gpt-5.6-luna {'claude-opus-5[1m]': 'high', 'gpt-5.6-sol': 'xhigh', 'gpt-5.6-luna': 'high', 'default': 'high'} [] []
```

`codex-debate=True` is only a substring marker in assembled static text; skills are injected separately, as stated in the matrix.


### Skill owner/projection

Exact command:

```text
set +e
printf 'owner='; git ls-files --error-unmatch pipelines/default/prompts/skills/codex-debate.md
printf 'generated_tracked='; git ls-files .codex/skills/codex-debate/SKILL.md
printf 'ignore='; git check-ignore -v .codex/skills/codex-debate/SKILL.md
cmp -s pipelines/default/prompts/skills/codex-debate.md .codex/skills/codex-debate/SKILL.md; printf 'cmp_rc=%s bytes_owner=' "$?"
wc -c < pipelines/default/prompts/skills/codex-debate.md | tr -d ' '
printf ' bytes_projection='
wc -c < .codex/skills/codex-debate/SKILL.md | tr -d ' '
echo
```

Output:

```text
owner=pipelines/default/prompts/skills/codex-debate.md
generated_tracked=ignore=.gitignore:15:.codex\t.codex/skills/codex-debate/SKILL.md
cmp_rc=0 bytes_owner=28399 bytes_projection=28399
```

### Local SQLite watermark and aggregate query

Snapshot file watermark: `/mnt/data/orch229-live-backup.db` mtime `2026-08-23 17:45:53.080345083 +0700` = `2026-08-23T10:45:53.080345083Z`; `PRAGMA integrity_check` returned `ok`.

Exact redacted aggregate query:

```sql
SELECT tool_name, COUNT(*) AS n, MAX(id) AS max_id, MAX(ts) AS max_ts
FROM logs
WHERE type='tool'
  AND tool_name IN ('mcp__orchestra__codex_review','mcp__orchestra__spawn_worker')
  AND ((tool_name='mcp__orchestra__codex_review' AND ts >= '2026-08-17T14:29:00Z')
    OR (tool_name='mcp__orchestra__spawn_worker' AND ts >= '2026-08-14T10:56:00Z'))
GROUP BY tool_name;
```

Output from the same backup:

```text
mcp__orchestra__codex_review | 3 | 462215 | 2026-08-23T10:04:14.054298+00:00
mcp__orchestra__spawn_worker | 31 | 463052 | 2026-08-23T10:43:07.014783+00:00
```

Model grouping used those exact filtered rows, parsed each JSON argument object, counted model key/value, and canonicalized values with `app.models.resolve_model`; no prompt or raw log body was emitted.

## Current routing flow (after the evidence table)

### A. Reviewer model

1. Caller invokes `codex_review`; Python default supplies `gpt-5.6-luna` when `model` is omitted (`app/mcp_stdio.py:2413`, constant `:800`).
2. `_resolve_codex_review_model` resolves aliases through `app.models`, requires runtime `codex`, and rejects the Spark quota bucket (`:803-852`).
3. `_quota_refusal` asks `/api/usage/readiness` for that exact canonical model. Unknown/malformed/readiness transport errors pass; only `state == blocked` with numeric utilization yields refusal (`:855-890`).
4. Fresh, resume, and stale-session fallback all use the same canonical `review_model` in `codex -m`, artifact/usage metadata, and background-job message (`:2479`, `:2505-2510`, `:2534-2552`, `:2575-2587`, `:2621-2631`).
5. No Luna/Sol/Opus policy classifier runs in this function. The reviewer model is chosen by the caller only when explicit; omitted review is server-default Luna. Opus means Claude and is rejected by this Codex-only resolver.

### B. Worker model

1. Prompt policy asks the orchestrator/parent agent to classify task as Luna/Sol/Opus/Spark/etc. (`model-routing.md:3-20`).
2. MCP `spawn_worker` requires a non-empty model and sends that exact string to HTTP (`mcp_stdio.py:912-926,964-970`). There is no server task-class model selection.
3. HTTP validates/canonicalizes the model (`routes/sessions.py:121-155`), manager resolves it again and enforces agent availability for child sessions (`manager.py:579-585`).
4. Role and pipeline are resolved after the model is already supplied (`manager.py:604-624`); spawn rights and ownership are checked; planned non-orchestrator sessions run quota admission (`manager.py:687-714`).
5. Backend runtime and effort are derived from the supplied canonical model and resolved role effort map (`manager.py:736-755`, `pipeline.py:524-538`).
6. Therefore the prompt chooses the requested class, code validates/ad admits it, and code does not independently choose Luna/Sol/Opus.

## Effort selection

Worker effort is code-owned and model-specific:

- `pipelines/default/pipeline.yaml:17-34` documents the map; all five roles currently carry `{"claude-opus-5[1m]": high, "gpt-5.6-sol": xhigh, "gpt-5.6-luna": high, "default": high}` (`:41,57,73,96,115`).
- `app/pipeline.py:524-538` resolves exact canonical model first, then runtime, then `default`, then `None`.
- `app/manager.py:736-740` computes initial `effort`; `app/session.py:1419-1452` re-reads the manifest at the next turn boundary and reconnects only when effort changes.
- Backend receives `effort` in `BackendBuildContext` (`app/session.py:800-837`).
- `codex_review` has no effort parameter and its shell command has no `model_reasoning_effort` override (`app/mcp_stdio.py:2474-2479`); reviewer effort is therefore the Codex CLI/config default, not the pipeline role card.
- **Reviewer effort is intentionally unmeasured in this audit.** The effective Codex CLI/config value and CLI version were not read from the live reviewer process; the report excludes it from `CONFIRMED` current conclusions and records it as `LIKELY/OPEN` only.

## Historical supersession map

| Date/commit | Claim/behavior introduced | Current status and evidence |
|---|---|---|
| `2a5ae8b3` (#203, 2026-08-12) | Added prompt `<model-routing>` with Opus open-task default, Luna closed-task route, Sol open-task route, Opus orchestrator exemption | Superseded by `9442bc38` and then `580c425d`; current module is `pipelines/default/prompts/modules/model-routing.md:3-20` |
| `9442bc38` (#221) | Rewrote prompt to Luna universal default, Sol complexity exception, Opus special, Spark narrow; removed old explicit default structure | Foundational current policy text; later removed versioned IDs via `580c425d` |
| `580c425d` (#209, 2026-08-14) | Removed copied versioned IDs from routing prose and told callers they may omit model/use manifest default | The no-ID wording remains, but its omission claim is contradicted by current MCP required-model check (`mcp_stdio.py:912-917`) |
| `5c346ffd` (#227) | Added server-side worker model policy plumbing while retaining required explicit `spawn_worker(model=...)` | Superseded/removed by `0707d925`; current manager still validates chosen model/admission but has no task-class router |
| `bd4f6e61` (#304, 2026-08-16) | Added explicit `codex_review(model=...)`; omitted default set to Sol; propagated selected model through fresh/resume/fallback/accounting | Default superseded by `9a1e2d10`; propagation logic remains current. #304 report’s “omitted = Sol” is historical, not current |
| `9a1e2d10` (#314, 2026-08-17) | Changed omitted Codex review default to Luna and briefly wired quota-controller routing | Luna default remains; quota-controller routing was removed in `0707d925` |
| `98ae5885` (2026-08-19) | Made review optional when Codex unavailable; removed Opus replacement reviewer and changed skill route to Luna/Sol only | Current skill lines `49-83`; code also rejects Claude/Opus for `codex_review` |
| `0707d925` (#343, 2026-08-19) | Removed legacy quota controller/runtime router/model policy; centralized admission in `app/quota_gate.py`; preserved Luna review default | Current quota path is manager + readiness/refusal (`manager.py:694-714`, `mcp_stdio.py:855-890`) |
| `dc09cc23` (#366, current history) | Added model catalog/agent availability flags | Current spawn path calls `ensure_spawn_allowed`; review resolver does not call agent availability flags, only registry/runtime/quota bucket |

## Contradictions and staleness

1. **Reviewer omitted default:** `codex-debate.md:82-83` says the omitted call remains Sol; current executable default is Luna (`mcp_stdio.py:798-800,2413`). This is a direct stale claim, superseded by #314.
2. **Reviewer accepted set:** skill says `codex_review` launches Luna/Sol and “other reviewer” is absent (`codex-debate.md:8-10,70-83`), while code accepts all registered non-Spark Codex models, including Terra/GPT-5.5/GPT-5.4/GPT-5.4-mini (`mcp_stdio.py:823-850`, `models.py:84-113`).
3. **Worker omission:** `model-routing.md:8-10` and `orchestration.md:81` say omit model/use manifest default; MCP rejects omission (`mcp_stdio.py:912-917`). This is not merely stale prose: it makes the documented call fail.
4. **Manifest/API fallback:** `pipeline.yaml:5` says `defaults.model: opus`; `skills/orchestra-agents.md:69-71` says role default applies when versioned id is omitted; HTTP request default is Sonnet (`routes/sessions.py:124`) and manager does not consult `ResolvedRole.model` for a missing model. The actual omitted API model is Sonnet.
5. **Prompt-vs-code enforcement:** model-routing says Terra/Fable are forbidden and quota should influence selection, but no task-class/quota classifier selects a model in spawn code. Code enforces registry/availability/admission only; Terra is accepted if registered and enabled, while quota blocks only after caller chose a model.
6. **Effort scope:** #289’s A/B description says `high` effort, but current `codex_review` shell does not select effort; the manifest effort card belongs to manager-created sessions, not review CLI jobs. Historical benchmark effort facts do not prove current reviewer effort.
7. **Skill copy owner:** `.codex/skills/...` is ignored/generated. The tracked owner is pipeline skill source; any local copy is projection at connect time, even if `cmp` is currently green.
8. **Immediate delegation is not a delivery miss:** the current parent session is Codex Sol and its stored prompt contains the DIY gate, research route, `model-routing`, and delegation markers (`length(system_prompt)=69,550`; all marker checks true). The same parent nevertheless made 21 Bash scans before its first `spawn_worker` at `2026-08-23T10:36:35Z`; the evidence supports a non-operational/ignored ordering rule, not absence of the rule. The exact internal reason for the model’s choice is not recorded and remains unknown.

## Additional contract requested by the user — desired policy, not current fact

| Desired contract | Current evidence | Status |
|---|---|---|
| Any nontrivial user task goes to a worker immediately; orchestrator keeps classification, acceptance and final result | Prompt routes research to `full-cycle` and says research/report artifacts delegate (`orchestration.md:19-22,49-66`), but also leaves “decide if you need workers or can do it yourself” (`:256-262`) and has no code ordering guard. Current parent scan-before-spawn is measured above | **Not current behavior; desired contract is only partly stated and not enforced** |
| Simple/closed task should normally be Luna worker | `model-routing.md:3-4,14-15` recommends Luna/default and closed-task Luna; `spawn_worker` requires explicit model and does not select Luna (`mcp_stdio.py:912-926`) | **Prompt recommendation; not code default** |
| Sol only for especially complex work | `model-routing.md:4-6,15` states the exception; code accepts explicit Sol for any task and has no task-complexity classifier | **Prompt-only; not enforced** |
| Orchestrator does classification, acceptance and final result | `orchestration.md:73-90` assigns review/approval/merge to orchestrator; `app/manager.py` can validate/admit/merge, but no generic “must delegate before reading” state machine exists | **Partly current role contract; acceptance is operational, immediate delegation is not** |

### Why the parent read hundreds of Markdown files first

The evidence separates delivery from execution:

1. **Delivery succeeded.** The live parent is a Codex `gpt-5.6-sol` orchestrator. Its persisted prompt is 69,550 bytes and contains the DIY gate, research route, delegation wording and model-routing markers. The Codex project document is separately mirrored, but the relevant delegation contract is already in the assembled role prompt.
2. **The contract is not mechanically enforced.** Code blocks built-in Agent/Task and native Codex multi-agent, but no code seam checks “spawn first” before Bash/read. Bash therefore remains available to the orchestrator.
3. **The prompt leaves a timing loophole.** Research is explicitly a spawn-without-asking route, yet the general workflow says first “decide if you need workers or can do it yourself,” and base guidance says large exploration “may delegate.” Those lines make delegation a model judgment rather than an immediate invariant.
4. **Observed behavior matches a policy execution failure.** The parent’s current session made 21 Bash scans, marked 264 unique Markdown paths and emitted 2,257 result lines before its first worker spawn. This proves the order; it does not reveal the hidden rationale, so “ignored/non-operational rule” is **LIKELY**, while “missing prompt” is **REFUTED**.

## Minimal cleanup proposal (proposal only)

- Add one unambiguous first-action rule to the orchestration module: “For every nontrivial task (research, multi-file/unknown scope, or report artifact), spawn exactly one appropriately routed worker before reading the corpus or implementation; the orchestrator may inspect only enough metadata to classify and write the task brief. Keep classification, acceptance and final synthesis.” Remove/qualify `base.md:57` “may delegate” and `orchestration.md:256-262`’s DIY-first wording so they cannot override this order.
- State the model consequence in the same owner block: closed task → pass `model="luna"`; complex research/architecture/measurement → pass `model="sol"`; special exceptional task → explicit Opus. Do not say “omit model” while `spawn_worker` rejects omission.
- If “immediate” must be a hard invariant rather than a prompt contract, a separate code task is required for a pre-tool state guard that denies orchestrator Bash/read until the first accepted `spawn_worker`; this research does not implement that guard.

## Observed-use counts (local live DB)

Source: `/mnt/data/Projects/Python/orchestra/data/orchestra.db`; opened read-only and copied with `sqlite3.Connection.backup()` to a temporary SQLite DB. Backup reported **91,058 pages**, `PRAGMA integrity_check = ok`. Query filtered exactly `logs.type='tool'`, the requested `tool_name`, and the requested UTC cutoff. JSON arguments were parsed from the tool-call payload; only model key presence/value was counted. No raw prompt/log body was output.

| Tool/window | rows | explicit model | omitted key | empty/non-string | malformed JSON | requested values | canonical values |
|---|---:|---:|---:|---:|---:|---|---|
| `mcp__orchestra__codex_review`, `>=2026-08-17T14:29:00Z` | 3 | 3 | 0 | 0 | 0 | `codex=2`, `sol=1` | `gpt-5.6-sol=3` |
| `mcp__orchestra__spawn_worker`, `>=2026-08-14T10:56:00Z` | 31 | 31 | 0 | 0 | 0 | `claude-opus-4-6[1m]=1`, `gpt-5.6-sol=5`, `sol=6`, `opus=7`, `claude-opus-5[1m]=9`, `luna=3` | `claude-opus-4-6[1m]=1`, `gpt-5.6-sol=11`, `claude-opus-5[1m]=16`, `gpt-5.6-luna=3` |

Observed-use is caller behavior, not proof of what omission would do: both samples have zero omitted calls. VPS/Contabo counts are **unmeasured**; no safe read-only database route was established in this session.

## Counter-evidence and confidence

- **CONFIRMED — current executable reviewer default is Luna.** Direct code default and current blame (`9a1e2d10` introduced the value; `0707d925` retained it) outweigh #304’s historical report.
- **CONFIRMED — current MCP worker spawn requires explicit model.** The empty-model branch raises before HTTP; no server fallback exists in the path.
- **CONFIRMED — manager/API do not use pipeline model as omission fallback.** HTTP Pydantic default is Sonnet and manager receives a concrete model before role resolution.
- **CONFIRMED — effort is model-specific for managed sessions.** Manifest map, resolver precedence, manager construction, and session boundary reread agree.
- **CONFIRMED — current review acceptance is broader than the prompt’s Luna/Sol prose.** Resolver checks runtime and quota bucket, not a two-model allowlist.
- **LIKELY — reviewer effort is Codex CLI/config default.** No effort flag exists in `codex_review` command construction; the external CLI/config value was not read in this research, so its exact effective level remains open.
- **COUNTER-EVIDENCE:** historical #289 and #304 describe Sol-default review and high-effort A/B; git history places those claims before #314 and current code has since changed the default. Historical observations remain valid for their dates/cohorts, not for current omitted behavior.
- **COUNTER-EVIDENCE:** #187 proposed a server quota-router and documented the prompt/code gap; #343 later removed the runtime router. Current admission still enforces blocked chosen models, but it does not choose among models.

## Review evidence

The selected Luna review job `bg-6a1d8934c8` exited non-zero (`/tmp/codex_review_research-review-routing-luna_codex-review-research.rc` = `2`) and the platform marked the artifact blind/execution failed. Its recovered text is preserved in `docs/tasks/229/codex-review-research.md` with a recovery note. It surfaced no blocking finding in its text, but that is **not a completed/verifiable verdict**: the output lacked the required artifact-grounded proof. Actionable findings were applied here: stale citation corrected to `codex-debate.md:82-83`, exact role/projection probes and SQLite watermark/query added, and reviewer effort explicitly marked unmeasured. Per the runtime rule, the failed round was not restarted.

## Exact cleanup proposal (proposal only; no runtime/prompt changes made)

1. Make one current reviewer default statement authoritative: update `codex-debate.md` to Luna, or change code back to Sol only by an explicit decision; remove the stale opposite sentence.
2. Separate “model selection policy” from “model admission”: either implement a server selector or change prompt wording to say caller must provide an explicit model and code only validates/ad admits it.
3. Decide whether pipeline role `model` is a real API fallback. If yes, use it in HTTP/manager omission handling; if no, rename/document it as catalog metadata and align `orchestra-agents.md`.
4. State the accepted reviewer set accurately: registered non-Spark Codex models, or add a code allowlist for Luna/Sol if that is the intended contract.
5. Document reviewer effort separately from managed-worker effort; add an explicit review effort only if the desired contract requires it.
6. Keep `pipelines/default/prompts/skills/codex-debate.md` as the owner and treat `.codex/skills/...` as generated projection; verify projection on backend connect.

These are cleanup options, not implementation decisions.

## Concise retell

For reviews, the server now picks Luna when the caller omits `model`; an explicit alias such as `sol` resolves to Sol, then the server checks that it is a registered non-Spark Codex model and that the chosen quota is not currently `blocked`. Resume and stale fallback keep that same model. Review effort is not selected by the pipeline card: the review shell passes only `-m`, so the Codex CLI/config decides its effort.

For workers, the parent agent is supposed to choose Luna/Sol/Opus from Markdown, but that choice is not made by code. `spawn_worker` rejects an omitted model, forwards the explicit value, and manager/API validate it, apply agent-availability and quota admission, then derive backend and effort from the role’s manifest effort map. The manifest’s `opus` default and the prompt’s “omit model” advice do not currently provide a fallback. The main stale claims are the skill’s Sol reviewer default, the prompt’s omission advice, and prose saying the role manifest supplies an API default.

## Sources opened

1. `app/mcp_stdio.py:798-917,2406-2647` — reviewer default/resolver, spawn MCP contract, fresh/resume/fallback command construction.
2. `app/manager.py:324-354,565-755` — prompt/dynamic role assembly, model resolution, spawn admission, effort.
3. `app/routes/sessions.py:121-155,244-288` — HTTP session model default and forwarding.
4. `app/pipeline.py:1-9,220-355,493-590` — manifest schema, role merge, effort resolution, prompt assembly.
5. `app/session.py:800-837,1419-1452` — backend effort context and hot manifest reread.
6. `app/models.py:45-113,154-194,449-455,769-784` — registry, aliases, agent availability, prompt catalog.
7. `app/quota_gate.py:1-20,238-256` — quota bucket mapping and central policy owner.
8. `app/prompting.py:195-317` and `app/workspace.py:371-446` — skill projection, tracked-file guards, AGENTS mirror.
9. `pipelines/default/pipeline.yaml:1-123` — role models, effort cards, modules, skills.
10. `pipelines/default/prompts/modules/model-routing.md:1-21` — worker routing prose.
11. `pipelines/default/prompts/skills/codex-debate.md:1-190` — reviewer routing prose and stale omission statement.
12. `pipelines/default/prompts/skills/orchestra-agents.md:50-87` — API/session creation prose.
13. `docs/tasks/289/research.md` — measured Luna/Sol review experiment and historical policy basis.
14. `docs/tasks/304/report.md` — explicit reviewer model implementation; historical Sol default.
15. `docs/tasks/199/research.md`, `docs/tasks/208/research.md` — historical model/effort measurements.
16. `docs/tasks/187/research.md`, `docs/tasks/176/research.md`, `docs/tasks/177/research.md`, `docs/tasks/118/audit.md` — historical prompt/code gaps, model attribution, review-loop and routing contradictions.
17. `git blame`/`git show` for `2a5ae8b3`, `9442bc38`, `580c425d`, `5c346ffd`, `bd4f6e61`, `9a1e2d10`, `98ae5885`, `0707d925`, `dc09cc23` — supersession map.
