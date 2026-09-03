# Plan — Self-Analysis skill (Mechanism A, per-task retro)

> Phase 2. Scope locked by orchestrator:
> 1. **Mechanism A only** (per-task retro). Mechanism B (cross-session patterns) = separate future task.
> 2. Skill = SKILL.md format (quick-skill style, frontmatter + body).
> 3. Simple — trigger conditions, template, output location. No over-engineering.
> 4. **Tier-1 auto only** (worker's own `docs/workers/<name>.md`). Tier-2 (prompt/CLAUDE.md edits) = always **propose**, never auto-write.
> 5. Trigger = **prompt self-trigger** (option A) + manual `/self-analysis`.
>
> **Revised after Codex review** (`codex-review-plan.md`): a blocking wiring bug was found and verified in code —
> see T0. Ticket slices made vertical. Memory-write anchoring AC added. Tier-2 default = "logged, not promoted".
> Attach to **full-cycle first**, `worker` deferred (Codex question, accepted — see Scope).

## Verified wiring facts (read from code, Codex-confirmed)
- `manager.py:544-549` resolves a role's skills from **`pipeline.yaml`** via `get_role(pipeline, role).skills`
  (a `ResolvedRole`, `app/pipeline*.py:250`), then gates injection on `_skills != "all"` and calls
  `inject_skills_to_worktree(role, wt.path)` — **passing only the role name, not the resolved list.**
- `inject_skills_to_worktree()` (`prompting.py:183-190`) then **re-derives** skills by reading
  `roles/<role>.md` **frontmatter**. But role bodies are intentionally frontmatter-free
  (`test_role_files_have_frontmatter_stripped`, `tests/test_default_pipeline.py:274`). So
  `meta.get("skills", [])` → `[]` → **nothing is copied.**
- **Consequence (latent bug):** pipeline `skills:` lists (incl. today's `codex-debate`) are NOT injected into
  worktrees at all. Adding `self-analysis` to `pipeline.yaml` alone would do nothing. T0 fixes the injector so
  it consumes the resolved pipeline skills. Without T0, the entire feature is a no-op.
- Skills, once injected, land at `worktree/.claude/skills/<name>/SKILL.md` and the worker invokes them via the
  `Skill` tool. `skills_catalog()` (`prompting.py:103`) lists **all** `skills/*.md` regardless of role, so it
  is **not** a valid check that a role received a skill (Codex: catalog check is too weak).
- Worker memory `docs/workers/<name>.md` is auto-injected on spawn/resume (`manager.py:474`,
  `_load_worker_memory`) — Tier-1 target, already wired.

## What changes
1. **Fix** `app/prompting.py` + `app/manager.py` — inject the **resolved** pipeline skills (T0). Small, targeted.
2. **New file** `pipelines/default/prompts/skills/self-analysis.md` — the skill.
3. **Edit** `pipelines/default/pipeline.yaml` — add `self-analysis` to `full-cycle.skills`.
4. **Edit** `pipelines/default/prompts/roles/full-cycle.md` — trigger step + `retro.md` in artifacts tree.

## What NOT to touch
- `modules/self-improvement.md` — the reactive layer stays exactly as-is (proven in #85). Not merged/edited.
- Mechanism B, cross-session aggregation, any model/module reassignment.
- `worker` role — **deferred** (see Scope). Orchestrator / sub-orchestrator roles — not attached.

## Scope decision — full-cycle first (Codex question, accepted)
Attach `self-analysis` to **`full-cycle` only** for the first cycle. Rationale: full-cycle already produces task
artifacts, runs Codex reviews, and writes `report.md` — the retro has real signals to anchor to, and volume is
low (full-cycle is used for substantial tasks, not one-shots). Generic `worker` fires on many small tasks →
noisy `retro.md`/memory writes with weak signals. Add `worker` in a follow-up once real retros prove useful.
(The T0 injector fix still benefits all roles — it fixes `codex-debate` injection too.)

## Output & scope contract (skill runtime behavior)
- **Writes (Tier-1, auto, allowed):**
  - `docs/tasks/<task-id>/retro.md` — the retro report. No `<task-id>` ⇒ `docs/tasks/adhoc-retro-<YYYYMMDD-HHMM>.md`.
  - `docs/workers/<name>.md` — append **worker-scoped, distilled** lessons only. **A memory line may be written
    only if it derives from an anchored retro entry** (cites the concrete signal), is generalizable, and is
    directly actionable for this worker. n=1 weak observations are logged in the retro, NOT written to memory.
    Append/merge, never overwrite, no secrets, short lines.
- **Proposes only (Tier-2, never auto-write):** any change to `CLAUDE.md`, `pipelines/**`, `pipeline.yaml`.
  Go into the retro's "Proposed changes (awaiting approval)" table as text; surfaced in the DONE report. Default
  row status = **"logged, not promoted"** unless the signal is severe (e.g. Codex HIGH traced to a prompt
  cause) or recurrence is already known. The skill MUST NOT edit these files.

## Trigger design (best-effort prompt gate — option A, honestly labeled)
Per Codex: the gate is **prompt-driven and self-reported**, not code-enforced — call it best-effort MVP, not
"deterministic". Mechanism that closes the missed-trigger hole: the role prompt says **"before the final DONE
report, invoke `self-analysis`; the skill itself skips immediately unless it can cite ≥1 concrete signal."** So
the skill always runs on substantial tasks and self-gates on signal presence — no reliance on the worker
pre-counting its own history.

Gate signals the skill checks for (skip if none present):
- Codex review returned CRITICAL/HIGH, or a test run failed at any point
- ≥5 files touched or a visibly long task (≥10 tool calls) — best-effort from turn history
- The user corrected/rephrased the task mid-flight
- A single command retried ≥3×
- Explicit `/self-analysis` — always runs (bypasses skip)

The gate list lives in the **skill** (single source of truth); the role prompt just says "invoke self-analysis
before DONE; it self-skips if no signal" — no gate duplication, no chicken-and-egg (Codex point addressed).

---

## Tickets

### T0 — Fix native skill injection to use resolved pipeline skills  ⚠️ prerequisite
- **Problem:** `inject_skills_to_worktree(role, path)` reads skills from frontmatter-free role files → injects
  nothing. Pipeline `skills:` are silently dropped for every role.
- **Files:** `app/prompting.py` (`inject_skills_to_worktree`), `app/manager.py` (call site ~544-549),
  `tests/test_manager.py` (`TestInjectSkillsGating`).
- **Change:** change the injector signature to accept the resolved skill list —
  `inject_skills_to_worktree(skill_names: list[str], worktree_path: str)` — and drop the role-frontmatter read.
  In `manager.py`, when `_skills` is a concrete list, pass it through: `inject_skills_to_worktree(_skills, wt.path)`.
  Keep the `_skills == "all"` skip. Update `test_skills_list_injects` to assert the injector is called with the
  resolved list (`["foo","bar"]`).
- **AC:**
  - After `create_session` with a role whose `pipeline.yaml` `skills:` = `[codex-debate]`, a temp worktree
    contains `.claude/skills/codex-debate/SKILL.md` (real copy assertion, not a catalog check).
  - `skills="all"` still skips injection (existing test green).
  - Injector no longer reads `roles/<role>.md` frontmatter.
  - Full suite green: `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q`.
- **blocked-by:** none

### T1 — Skill file + full-cycle wiring (end-to-end vertical slice)
- **Files:** `pipelines/default/prompts/skills/self-analysis.md` (new); `pipelines/default/pipeline.yaml`
  (`full-cycle.skills`); `pipelines/default/prompts/roles/full-cycle.md` (trigger + artifacts tree).
- **Change:**
  - Skill: frontmatter (`name: self-analysis`; description with triggers `/self-analysis`, `/retro`, "do a
    retro"; `roles: [full-cycle]`; `integrations: []`) + body: (a) **When** — "run before DONE; skip
    immediately unless ≥1 gate signal is present" + the gate list; (b) **How** — collect metrics block from own
    turn history; list each problem **anchored to a concrete signal** — *no signal ⇒ no entry* (hard rule
    blocking the Huang intrinsic-correction failure mode); (c) **Template** (metrics-first, from research §6.1);
    (d) **Scope** — Tier-1 write targets + the memory-anchoring rule (memory line only from an anchored entry) +
    Tier-2 propose-only with "logged, not promoted" default + safety (append/merge, no overwrite, no secrets);
    (e) **Output location** rules (`retro.md` / adhoc fallback). ≤ ~75 lines.
  - `pipeline.yaml`: `full-cycle.skills` → `[codex-debate, self-analysis]`.
  - `full-cycle.md`: Phase-3 new step 8 — "Before final DONE, invoke `self-analysis` (writes
    `docs/tasks/<id>/retro.md`; self-skips if no signal); include any Tier-2 proposals in the report." Add
    `retro.md` to the `<artifacts>` tree. ≤2 added lines beyond the tree entry.
- **AC:**
  - `self-analysis.md` frontmatter parses via `parse_role_frontmatter` (no error); has `name/description/roles/integrations`.
  - Body contains: the gate list; the verbatim-in-spirit "no signal ⇒ no entry" rule; a fenced template with
    **Metrics** first, then root-cause, then a "Proposed changes (Tier-2, awaiting approval)" table; the explicit
    statement that the skill may write `retro.md` + `docs/workers/<name>.md` and MUST NOT edit
    `CLAUDE.md`/`pipelines/**`/`pipeline.yaml`; the memory-anchoring rule; "logged, not promoted" default.
  - No mention of Mechanism B / cross-session aggregation.
  - `full-cycle.skills` contains `self-analysis`; YAML parses.
  - After a `create_session` for role `full-cycle` (with T0 applied), the worktree contains
    `.claude/skills/self-analysis/SKILL.md` (real copy assertion).
  - `full-cycle.md` Phase 3 references invoking `self-analysis` before DONE; `<artifacts>` tree lists `retro.md`;
    changes are ≤ a few lines, no unrelated edits.
- **blocked-by:** T0

### T2 — Verify end-to-end + suite green
- **Files:** none (verification) — results recorded in `report.md`.
- **Checks:**
  - Real injection assertion for **both** `codex-debate` and `self-analysis` on the `full-cycle` role (temp worktree copy check).
  - `parse_role_frontmatter` reads `self-analysis.md`.
  - `test_default_pipeline` manifest check passes — every `skills:` entry in `pipeline.yaml` has a matching file
    (this is why T1 creates the file and attaches in the same slice).
  - Full suite: `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q` — no NEW failures vs the pre-existing
    known ones noted in CLAUDE.md.
- **AC:**
  - Injection copy assertion passes for full-cycle; frontmatter parses; manifest test green; no new test failures.
- **blocked-by:** T0, T1

## Test / risk notes
- **T0 is load-bearing** — without it the feature is a silent no-op AND `codex-debate` stays broken. It also
  means this task incidentally fixes a real latent bug. Flag in report as a breaking-adjacent change (injector
  signature) — but the only caller is `manager.py` and the mocked test.
- Manifest test (`test_default_pipeline`) validates `skills:` entries have files → T1 bundles file+attach.
- Adherence risk (prompt self-trigger skipped) — mitigated by "always invoke, skill self-skips on no signal" +
  manual `/self-analysis`. Measuring real fire rate = follow-up.
- Blast radius: full-cycle only; injector fix affects skill delivery for all roles (net positive — currently
  zero skills delivered). Reversible: revert injector, remove skill file + `skills:` entry.

## Ticket order
T0 → T1 → T2. (Strictly sequential — T1 depends on the injector fix to verify delivery; T2 verifies both.)
