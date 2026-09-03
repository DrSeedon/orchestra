# Report — Self-Analysis skill (Mechanism A)

## What shipped
A per-task **self-analysis retro** skill for `full-cycle` workers, plus a fix to a latent skill-injection bug
that Codex found in Phase 2. Retro is metrics-first and **signal-anchored** — every "what went wrong" entry
must cite a concrete signal (Codex verdict, test fail, retry count, correction); no signal ⇒ no entry. This
structurally prevents the open-ended intrinsic self-correction that degrades performance (Huang 2024).

## Tickets
- **T0 — fix native skill injection.** `inject_skills_to_worktree()` read skills from role-file frontmatter,
  but role files are frontmatter-free → it injected nothing (pipeline `skills:` silently dropped for all roles,
  incl. `codex-debate`). Changed signature to take the resolved skill list; `manager.py` passes `_skills`
  through. **This incidentally fixes skill delivery for every role.**
- **T1 — skill + full-cycle wiring.** New `skills/self-analysis.md`; added to `full-cycle.skills`; Phase-3 step 7
  + `retro.md` in artifacts tree.
- **T2 — verification.** Real copy-assertion tests (files actually land in the worktree).

## Files (+107 / −12)
- `app/prompting.py` — `inject_skills_to_worktree(skill_names, worktree_path)`; dropped frontmatter read.
- `app/manager.py` — call site passes resolved `_skills`; guard `_skills and _skills != "all"`.
- `pipelines/default/pipeline.yaml` — `full-cycle.skills: [codex-debate, self-analysis]`.
- `pipelines/default/prompts/roles/full-cycle.md` — Phase-3 retro step + artifacts entry.
- `pipelines/default/prompts/skills/self-analysis.md` — new (the skill).
- `tests/test_manager.py` — strengthened `test_skills_list_injects`; new `TestInjectSkillsRealCopy` (2 tests).

## Scope decisions
- **full-cycle only** (worker deferred) — full-cycle has real artifacts/Codex/report to anchor to; avoids noisy
  retros on small worker tasks. Add `worker` in a follow-up once retros prove useful.
- **Tier-1 auto** = `docs/tasks/<id>/retro.md` + worker memory (memory line only from an anchored entry).
  **Tier-2** (CLAUDE.md / prompts / pipeline.yaml) = propose-only, default "logged, not promoted".
- `modules/self-improvement.md` untouched — the reactive layer stays; this is a separate proactive layer.

## Tests
- Targeted: `TestInjectSkillsGating` (3) + `TestInjectSkillsRealCopy` (2) — **green**. Real copy asserts
  `codex-debate` AND `self-analysis` land at `worktree/.claude/skills/<name>/SKILL.md`.
- `test_default_pipeline`: **5 failures pre-exist** — verified identical on clean HEAD (stash test). They are
  the known session-notes/manifest drift noted in CLAUDE.md, NOT introduced here. My changes: 37→42 passed.
- Full suite not run under the global lock (held by `test-sonnet5` since 2026-07-01 — stale); targeted tests
  cover all changed code paths.

## Breaking
- `inject_skills_to_worktree` signature changed (`role: str` → `skill_names: list[str]`). Only caller is
  `manager.py` (updated) + one mocked test (updated). No external API. Net effect is a **fix** — skills were
  not being injected before.

## Adversarial self-review (2-3 weak spots)
1. **Prompt-trigger adherence** — the worker may skip invoking the skill before DONE. Mitigated by "always
   invoke → skill self-skips if no signal" + manual `/self-analysis`. Real fire-rate is unmeasured → follow-up.
2. **`_skills` truthiness guard** — `_skills and _skills != "all"` correctly skips `None`/`[]`, injects on a
   non-empty list, skips `"all"`. Edge case `"all"` is a truthy string so the second clause handles it. OK.
3. **Skill self-gating is model-judgment** — "≥1 signal present" is the worker's own read of its history, not
   code-enforced. Accepted as best-effort MVP (labeled as such in the plan), consistent with option A.

## TODO / follow-ups (not in scope)
- Mechanism B (cross-session pattern pass) — separate task.
- Attach `self-analysis` to `worker` after full-cycle retros prove useful.
- Measure real trigger fire-rate; if retros don't reduce repeat mistakes, stop at local reports (per research §8).
- Pre-existing `test_default_pipeline` drift (5 fails) — unrelated, worth a separate cleanup.
