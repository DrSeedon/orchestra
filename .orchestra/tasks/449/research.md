# #449 — PROJECT CONTEXT как данные проекта

## Question

- **Context:** `codex_review` запускает внешний Codex CLI из worker worktree, а severity calibration
  сейчас собирается вызывающим агентом из prompt-шаблона.
- **Change under test:** заменить ручную передачу проектной основы на один машинно-читаемый owner
  проекта, сохранив задачную калибровку отдельно.
- **Baseline:** `codex_review(context=...)` принимает смешанную строку и требует, чтобы в ней был
  текст `PROJECT CONTEXT`; текущий template находится в `pipelines/default/prompts`.
- **Outcome:** каждый review получает контекст именно проверяемого проекта; caller может добавить
  факты задачи, но не заменить project fields; отсутствующий источник не маскируется заглушкой и не
  кладёт весь парк агентов обязательным недоступным шагом.

## Hypotheses considered

### H1 — project-owned data loaded by the existing review tool

`codex_review` читает один project-owned structured file, сериализует только разрешённые поля,
добавляет caller task instructions отдельным участком и передаёт обе части Codex CLI. This should
remove manual repetition while preserving a single data owner.

**Falsifier:** Git identity cannot deterministically resolve the repository for either a normal
worktree or a cross-repository worker, or the project file cannot separate immutable fields from task
text without allowing caller overrides.

### H2 — keep prompt template and improve the manual contract

The template remains in `pipelines/`, and agents are merely instructed to copy current values into
each call. This avoids a schema/migration, but does not make the data project-owned.

**Falsifier:** the current path already has a project-owned structured source that contains all six
calibration fields and is consumed by `codex_review` without caller text; static inventory below
finds no such source.

### H3 — central Orchestra/SQLite project registry owns the fields

Project fields are stored outside the repository and looked up centrally, avoiding edits from a
worker branch.

**Falsifier:** the central project identity cannot distinguish the repository being reviewed from the
parent session namespace when `repo_path` points elsewhere, or central storage would duplicate a
repository-owned project source without adding a required property.

## Findings

### 1. Consumer and actual effect

1. `app/mcp_stdio.py:3561-3566` only checks that the caller string contains the marker; this is a
   precondition, not the review effect [1].
2. `app/mcp_stdio.py:3567-3569` places the caller string into `review_context`, and
   `app/mcp_stdio.py:3662-3675` embeds it in the fresh `review` prompt passed through stdin to
   `codex exec review`; `app/mcp_stdio.py:3695-3733` does the same for `exec` and resume/fallback
   paths [1]. The block therefore changes Codex's severity calibration, not just tool acceptance.
3. The existing `_REVIEW_RUBRIC` at `app/mcp_stdio.py:3453-3457` adds only generic blocking/suggestion/
   nit labels; it does not supply project scale, users, stack, or project philosophy [1].
4. Active tests use a manually authored block in `tests/test_mcp_codex_review.py:9-16`; the focused
   regression command passed **5 tests, 12 deselected, 3.26 s**. The test also verifies the caller
   text reaches the generated Codex command (`high-load multi-project orchestration`) [2].

**Confidence:** CONFIRMED — direct source trace plus executable test output.

### 2. Current ownership and absence of a project data source

1. The sole active template is the `PROJECT CONTEXT` section in
   `pipelines/default/prompts/modules/orchestration.md:92-107`; the skill repeats the requirement and
   examples at `pipelines/default/prompts/skills/codex-debate.md:103-137,252-258` [3]. The same
   structured block is therefore represented in prompt guidance and caller/test strings.
2. A literal inventory outside prompts/tests/history found no structured project-context keys. Current
   candidate files are `CLAUDE.md`/`AGENTS.md` (181,149 bytes each), `README.md` (12,734 bytes), and
   `pyproject.toml` (4,824 bytes); only `CLAUDE.md` has a Stack sentence, while no file has the six
   calibration keys as a structured record [4].
3. H2 is therefore not a project-data solution: it preserves the existing manual owner and leaves
   drift/omission detectable only after the review call is rejected.

**Confidence:** CONFIRMED — literal inventory and opened prompt/source files. The inventory does not
claim that no prose contains any related fact; it shows that no existing structured source owns all
required fields.

### 3. Repository identity with worktrees and foreign `repo_path`

1. `codex_review` resolves the requester through `GET /api/sessions/{WORKER_NAME}?scope=SCOPE`, then
   chooses `cwd = worktree_path or cwd or scope` at `app/mcp_stdio.py:3576-3589` [1]. The generated
   shell changes into this `cwd` before invoking Codex at lines 3671-3674 and 3717-3721 [1].
2. `SCOPE` is not a reliable repository identity for a foreign worker: `spawn_worker` sets
   `scope = SCOPE or repo_path` but sends `repo_path` separately at `app/mcp_stdio.py:950-981`, and
   `_cross_repo_note` explicitly states that tasks/numbers remain in the parent project while the
   worker commits in the other repository at `app/mcp_stdio.py:920-948` [1].
3. The session detail exposes `worktree_path`/`cwd` but the create response adds `repo_path` and
   `git_common_dir` only when creating a worktree (`app/routes/sessions.py:292-307`); the detached
   `AgentSession.to_dict()` keeps `worktree_path` and `scope` (`app/session.py:5261-5275`) [1].
4. A scratch Git linked-worktree probe printed:

   ```text
   worktree=/tmp/tmp.cMQsl7Skgw/wt
   /tmp/tmp.cMQsl7Skgw/wt
   /tmp/tmp.cMQsl7Skgw/.git
   common-parent=/tmp/tmp.cMQsl7Skgw
   ```

   Thus `git rev-parse --show-toplevel` returns the worktree, while resolving
   `git rev-parse --git-common-dir` and taking its repository parent identifies the shared project
   root. This is the identity the loader should use for a review launched from a worker worktree;
   it remains correct when parent `SCOPE` names another project [5].

**Confidence:** CONFIRMED — source trace plus direct Git measurement.

**Boundary:** for an orchestrator with no worktree, the loader must apply the same Git probe to its
`cwd`; a non-Git cwd has no repository-owned context source and must enter the missing-source policy.

### 4. Missing-file policy and cost

The current hard failure is real: blank/no-marker context raises `invalid_argument` before readiness
or background-job creation (`app/mcp_stdio.py:3559-3575`), and the focused test confirms no API calls
occur in that case [1][2]. The alternatives have asymmetric costs:

| Policy | Benefit | Cost / failure mode |
|---|---|---|
| Refuse review | Never invents scale; protects severity calibration and makes missing setup visible | A mandatory review step becomes unavailable. #256's first review attempt was rejected before a model started because the block was absent; #361 records a foreign orchestrator receiving `503 knowledge_not_configured` on a mandatory prompt step, forcing rollback. |
| Fixed/default project values | Review remains available | A guessed default can understate severity. #172 confirmed the old fixed `small team, MVP stage` context was sent to every review and contradicted the current-project rule; high-load projects can be miscalibrated. |
| Warning + explicit unknown/conservative sentinel | Avoids a park-wide hard outage while exposing missing configuration; reviewer can treat unknown as high-risk | Review quality is lower until configured; a fallback representation must not become a second permanent project-data owner. It also needs an explicit, testable policy for what “unknown” means. |

The measured outage cost is not hypothetical: the knowledge mandatory-step incident affected foreign
orchestrator delivery across projects, while the old default caused silent miscalibration [6][7].
The likely safe transition is an explicit warning and conservative unknown state during migration,
followed by a documented refusal only if the project cannot be identified at all; whether that
sentinel is acceptable is an architecture decision for Phase 2, not a Phase-1 implementation choice.

**Confidence:** CONFIRMED for the three observed costs; UNCERTAIN for the best policy because no
controlled review-quality comparison of unknown versus refusal has been run.

### 5. Project foundation versus task calibration

The current API has one free-form `context` string, so it cannot enforce ownership: a caller can place
its own `Scale`, `Users`, or `Stack` beside task instructions, and only a marker check runs [1]. A
clean contract has two separately serialized regions:

- **Project foundation:** loaded by the tool from the project owner, with a fixed allowlist of fields
  (`Scale`, `Users`, `Stack`, `Philosophy`, `What matters`, `What does NOT matter`) and explicit
  delimiters; caller text is never parsed as these fields.
- **Task calibration:** caller-supplied task, diff, acceptance, and round-change facts appended under
  a separate task heading. The tool should reject or quarantine a caller-supplied reserved project
  block rather than merge it, so the task can add a sentence without rewriting project fields.

This means the likely API direction is `task_instructions` (or a semantically equivalent renamed
argument) plus an internal project loader; retaining the name `context` is only safe if its contract
changes to task-only and reserved project keys are rejected. Keeping mixed `context` and asking agents
to “not override” is a soft convention, not ownership enforcement.

**Confidence:** LIKELY — contract consequence follows directly from current free-form input and the
required separation; exact compatibility shape needs Phase-2 design and red tests.

### 6. Freshness and staleness

Project scale, users/load, stack, and philosophy can change independently of code. A file timestamp
alone is weak for linked worktrees, and a fixed TTL would create validation debt rather than prove
truth: the knowledge architecture explicitly treats TTL as “stale-needs-validation” while retaining
history, not as deletion or truth [8].

The lowest-cost useful marker is provenance, not a claim of semantic freshness:

- content digest of the project data file;
- repository identity from resolved Git common-dir;
- reviewed repository `HEAD` (and, if available, the commit that last changed the context file);
- generated-at/requested-at metadata in the review receipt.

The tool can warn when the source is absent or malformed, and optionally when the file's last-change
commit is old relative to `HEAD`; it must not silently treat “old” as “wrong”. A mandatory human
`valid_until` would add maintenance cost and can still miss a sudden change; the choice of warning
versus gate needs Phase-2 acceptance evidence.

**Confidence:** LIKELY — provenance claims are mechanically available from Git and the receipt path;
the useful age threshold is UNMEASURED.

### 7. New file/tool check and architecture options

**Without a new file:** parse `README.md`, `pyproject.toml`, and `CLAUDE.md`. This can recover some
stack prose (`CLAUDE.md:39`) and package metadata, but not a reliable structured scale/users/load or
the project philosophy; it also makes a 181,149-byte operational rule file the accidental owner.
The measured absence of all six keys outside prompts/tests supports that this route is incomplete [4].

**Without a new MCP tool:** extend the existing `codex_review` implementation with a private loader.
No separate `get_project_context` call is needed: an extra tool would add a round trip and a second
agent-visible seam without simplifying the action. The internal loader is not a new MCP surface.

Candidate ownership models for Phase 2:

1. **Repository file, likely `.orchestra/project-context.toml`:** portable with the code, structured
   allowlist/validation, naturally follows foreign `repo_path` after Git identity resolution. Cost:
   each repository needs initial data and the current worktree can edit it unless the loader reads a
   pinned base revision or the project file is protected by a separate ownership rule.
2. **Central project registry:** worker cannot rewrite fields in its branch. Cost: current `SCOPE`
   is the parent namespace in cross-repo spawns, `portfolio_projects` has no repository identity
   field, and central lookup would need a new stable repo-to-project mapping plus migration/replica
   semantics. This risks a second owner if a repository file is also retained.
3. **Existing prompt/CLAUDE text:** minimal code, but fails the single-owner and structured-data
   requirements; H2 is rejected as the answer.

No new MCP tool is justified by the “without it” check. A new repository data file is justified only
if the user chooses repository ownership; a central registry is a different architecture choice and
must be discussed before implementation.

## Counter-evidence and open risks

- A repository file can itself be changed in the review diff. Reading the current worktree makes the
  block reflect the reviewed state but permits a task to alter its calibration; reading a pinned base
  revision protects calibration but can hide a legitimate project-context change. This is unresolved
  and is the main H1/H3 design fork.
- A conservative unknown sentinel avoids the measured park-wide outage but may still bias a reviewer
  toward over-severity; no quality measurement exists. A hard refusal is cleaner but repeats the
  mandatory-step blast radius.
- The current `codex_review` output/docs examples point to `docs/tasks/<id>` while this task's
  storage policy is `.orchestra/tasks/<id>`; any implementation must update active examples without
  touching historical evidence.
- Review route: one fresh Luna pass was attempted after this artifact was written, but the service
  restart interrupted it before a model response or review artifact was produced. The only matching
  live artifact is absent (`.orchestra/tasks/449/review-luna.md` does not exist); a stale unrelated
  `/tmp/codex_review_...` fixture mentions `artifact.py` and was not used as evidence. Verdict: no
  completed review, no findings to fold in; the conclusions below remain self-reviewed against the
  cited source/measurement evidence.
- The repository KB validator is currently hard-coded to `docs/kb`: running the required command with
  `--root .orchestra/kb --diff /tmp/kb449.patch` rejects every changed `.orchestra/kb` path with
  `changed KB file does not exist`. This is tooling/path debt caused by the new `.orchestra/tasks`
  layout, not evidence against the project-context design; Phase 2 must either make the validator
  path-aware or explicitly retire it for the new owner.

## Affected files and likely implementation surface (not changed in Phase 1)

- `app/mcp_stdio.py` — loader, project identity, context composition, missing-source diagnostics.
- `pipelines/default/prompts/modules/orchestration.md` — remove ownership of block text after live
  loader exists; keep only the contract that review receives tool-owned project data.
- `pipelines/default/prompts/skills/codex-debate.md` — update `codex_review` signature/examples and
  remove duplicated block template; preserve review routing rules.
- `tests/test_mcp_codex_review.py` plus a focused new test module — project identity, immutable
  project/task separation, missing/malformed file, freshness metadata, and exact command plumbing.
- `.orchestra/project-context.toml` in each repository that opts into the design — one owner of the
  six project values; exact schema and base-revision policy require user choice.

## Sources

1. `app/mcp_stdio.py:3453-3815` — validation, context composition, CLI prompt construction,
   worktree lookup, receipt and command paths.
2. `tests/test_mcp_codex_review.py:9-111,246-289` — caller context, rejection, schema tests; command:
   `uv run python -m pytest -q tests/test_mcp_codex_review.py -k 'caller_context_and_declares_success_contract or missing_project_context_before_any_api_call or tool_schema_requires_project_context'`
   → `5 passed, 12 deselected in 3.26s`.
3. `pipelines/default/prompts/modules/orchestration.md:92-107` and
   `pipelines/default/prompts/skills/codex-debate.md:103-137,252-258` — active template and required
   caller contract.
4. Read-only inventory command:
   `wc -c CLAUDE.md AGENTS.md README.md pyproject.toml .env.example` →
   `181149 181149 12734 4824 5066`; `rg` for structured keys outside prompts/tests/history → no
   matches.
5. Read-only scratch Git probe using `git worktree add` and
   `git rev-parse --show-toplevel`/`--git-common-dir` — raw output is recorded in Finding 3.
6. `.orchestra/tasks/173/report.md:25-31,70` and `.orchestra/tasks/172/research.md:312-327` — prior
   removal of the hardcoded default and confirmation that it miscalibrated review severity.
7. `.orchestra/tasks/361/plan.md:184-195` and `.orchestra/tasks/256/review-luna.md:1-8` — measured
   mandatory-step outage and review rejection before model start.
8. `.orchestra/kb/knowledge-base-architecture.md:16-35` — freshness/TTL semantics and
   project-registry limitations.
