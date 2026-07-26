## Summary

Naturally, the “no copies” plan leaves the unconditional copy path alive 🙃 The direction is sound, but five blocking contract gaps remain around runtime isolation, ordering, source safety, and failure handling.

## Findings

### blocking: Gate worktree injection by runtime

The plan leaves `SessionManager` unchanged and promises no Sol-specific copies ([plan.md:79](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/docs/tasks/89/plan.md:79), [plan.md:131](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/docs/tasks/89/plan.md:131)). However, [`create_session`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/app/manager.py:521) computes the backend type but [injects pipeline skills](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/app/manager.py:572) for every worktree runtime. Existing [manager tests](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/tests/test_manager.py:238) enforce that unconditional behavior. Add `app/manager.py` and `tests/test_manager.py` to scope, gate copying to Claude, and test both Claude-copy and Codex-no-copy paths.

### blocking: Reconcile manifest order with resolved-role ordering

The plan promises manifest order ([plan.md:56](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/docs/tasks/89/plan.md:56), [plan.md:106](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/docs/tasks/89/plan.md:106)), but `_codex_factory` receives `ResolvedRole.skills`, and [`_merge_list`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/app/pipeline.py:324) sorts the union. The default manifest’s `html-artifacts, codex-debate` order is already reversed before the proposed builder sees it. Either adopt deterministic lexical order in the design/AC, or include `app/pipeline.py` and preserve order during resolution.

### blocking: Reject skill paths that escape the active pipeline

The resolver joins manifest-controlled names into `prompts/skills/<name>.md` ([plan.md:56](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/docs/tasks/89/plan.md:56)), but [`Defaults.skills`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/app/pipeline.py:144) and [`RoleSpec.skills`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/app/pipeline.py:177) accept arbitrary strings. Absolute names or `..` components can make the resolver read and advertise files outside the canonical skill directory. Specify containment validation for pipeline names and skill names, with absolute/traversal tests.

### blocking: Bind the index to the bytes Sol will actually read

The one-time `git diff --quiet HEAD` gate ([plan.md:58](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/docs/tasks/89/plan.md:58)) does not make a progressively loaded path safe. A clean regular file can change after index construction, leaving stale metadata pointing to new body content; a tracked symlink can be “clean” while its target is mutable or outside the repository. Reject symlinks and either provide an immutable snapshot or revalidate at point of use. The current “absolute mutable path” and “no copies” constraints cannot guarantee committed content simultaneously.

### blocking: Use different failure policies for required and ambient skills

The shared builder skips missing or malformed files with a warning ([plan.md:26](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/docs/tasks/89/plan.md:26)). That is reasonable for ambient project discovery, but an explicitly selected pipeline skill is part of the role contract; silently omitting it starts Sol with wrong instructions. The policy also needs to cover read/decode failures occurring before the existing frontmatter parser runs. Require pipeline-selected skills to fail loudly, while project files may warn and skip.

### suggestion: Exercise `skills: all` through `_codex_factory`

The TDD list tests `skills: all` resolution separately from factory wiring ([plan.md:89](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/docs/tasks/89/plan.md:89), [plan.md:93](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/docs/tasks/89/plan.md:93)). Current [`_codex_factory`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/app/runtime_registry.py:209) explicitly discards non-list values, so helper tests could pass while production still drops `"all"`. Add a factory-level non-default-pipeline test with `role.skills == "all"`.

## Verdict

❌ **Changes required.** The plan is not implementation-ready because several stated acceptance criteria cannot hold against the current manager and pipeline behavior, and the clean-source guarantee does not survive progressive loading.

Right now it’s a pristine catalog stapled to mutable pages—surely nothing could drift.

## Round (2026-07-26T10:20:29Z)

## Summary

Well, annoyingly for review drama, round two closes the loop 🙃 All six prior findings are fixed, including the clarified live-source threat model. No new blockers or suggestions found.

## Findings

- **FIXED — Runtime-gated injection.** T1 now changes `SessionManager.create_session`, preserves Claude copying, prevents Codex copying, and adds both test cases ([plan.md:106](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/docs/tasks/89/plan.md:106)).

- **FIXED — Resolved skill ordering.** The plan now correctly adopts the lexical order produced by `_merge_list` instead of promising unrecoverable manifest order ([plan.md:66](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/docs/tasks/89/plan.md:66)).

- **FIXED — Pipeline path containment.** Absolute/traversing pipeline and skill names are rejected before unsafe reads, with canonical-root containment and explicit tests ([plan.md:72](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/docs/tasks/89/plan.md:72)).

- **FIXED — Live-source integrity contract.** Threat-model argument acknowledged. The plan now accurately limits the HEAD check to construction-time stale-copy filtering, rejects symlinks/root escape, and explicitly accepts authorized live mutation without claiming TOCTOU protection ([plan.md:77](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/docs/tasks/89/plan.md:77)). Under the user-approved direct-read design, no concrete in-scope attacker or unacknowledged correctness guarantee remains.

- **FIXED — Source-specific failures.** Required pipeline skills fail backend construction on every specified read/parse/metadata failure; ambient project skills warn and skip ([plan.md:32](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/docs/tasks/89/plan.md:32)).

- **FIXED — Factory-level `skills: all` coverage.** The plan now tests a non-default pipeline through `_codex_factory`, covering the current list-only guard regression ([plan.md:127](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/docs/tasks/89/plan.md:127)).

## Verdict

✅ **APPROVED.** The plan is scoped, testable, and consistent with the current manager, resolver, and runtime contracts.

The catalog now admits the shelves are live instead of pretending the library is frozen—scandalously honest.
