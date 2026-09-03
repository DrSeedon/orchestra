## Summary

The plan’s core wiring references are real, and the committed oracle is genuinely RED: all four tests fail because the planned behavior is absent. The claim about #228 is also verified: exactly three tests are already red for the stated missing Bash matcher.

However, the plan/oracle do not secure the session-bound exceptions against path-bearing `task_id`, `session_name`, or `owned_dirs`. A wrong implementation can therefore pass T1 while granting access to another worker’s memory. The Phase 3 regression command also contradicts its claimed baseline.

## Findings

- **blocking** — [plan.md:38](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-fan-research/docs/tasks/238/plan.md:38), [test_write_scope_hook.py:74](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-fan-research/docs/tasks/238/acceptance/test_write_scope_hook.py:74): The supposedly session-bound exceptions accept unsanitized identity values. The plan says:

  > “Исключения привязаны к сессии, а не к шаблону пути.”

  But neither the plan nor oracle requires `task_id` and `session_name` to be single safe path components. For example, an implementation following the specified `Path.resolve()` construction can receive `task_id="../workers"` and treat `docs/tasks/../workers/**` as the worker’s task exception, allowing writes to every `docs/workers/*.md`. Likewise, path separators or `..` in `session_name` can move the nominal memory exception outside `docs/workers`. T1 only tests honest values `"238"` and `"me"`, so that implementation passes. Require rejection/disablement unless each exception identity is nonempty after trimming and contains no separator, `.` or `..`; add adversarial oracle cases, including `task_id="../workers"` attempting `docs/workers/someone-else.md`.

- **blocking** — [plan.md:36](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-fan-research/docs/tasks/238/plan.md:36), [test_write_scope_hook.py:54](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-fan-research/docs/tasks/238/acceptance/test_write_scope_hook.py:54): `owned_dirs` roots themselves are not constrained to `cwd`. Existing `parse_owned_dirs()` strips slashes but retains `..`, so values such as `"../"` or `"app/../../other"` can resolve outside the worktree and become allowed roots. The oracle tests normalization only on the requested file path, not on ownership roots. Require each resolved ownership root to remain under resolved `cwd`, deny/ignore escaping roots, and add a test proving an escaping `owned_dirs` entry cannot authorize an outside path.

- **blocking** — [plan.md:131](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-fan-research/docs/tasks/238/plan.md:131): The Phase 3 command does not include `docs/tasks/228/acceptance`, yet the expected baseline says `41 passed / 3 failed` and identifies the failures as #228. Those failures cannot appear in the written command. Either include #228 in the command or change the expected result. As written, implementation could produce three new failures and have them mistaken for the declared baseline.

- **suggestion** — [test_write_scope_hook.py:39](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-fan-research/docs/tasks/238/acceptance/test_write_scope_hook.py:39): `_write_matchers()` converts matchers into a dictionary, silently collapsing duplicate matchers. Therefore an implementation with two `Edit` matchers can pass despite the plan requiring “ровно четыре” and one matcher per instrument. Assert the raw matcher multiplicities before constructing a mapping.

- **suggestion** — [plan.md:86](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-fan-research/docs/tasks/238/plan.md:86), [test_write_scope_hook.py:102](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-fan-research/docs/tasks/238/acceptance/test_write_scope_hook.py:102): T2’s initial RED is caused by missing T3 constructor wiring, not T2 behavior. This is honest because T2 explicitly declares `blocked-by: T1, T3`, but it weakens the claim that each ticket has its own RED oracle and prevents independently validating T2 before T3. Prefer constructing the backend without new kwargs for default-off checks, or split constructor acceptance from hook behavior. Also correct the oracle header’s “Три теста = три тикета”: the file contains four tests.

## Verdict

**CHANGES REQUIRED.** The RED state and #228 baseline claim were reproduced, and the referenced production seams exist. The exception-binding and ownership-root gaps are blocking because a path-widening implementation could pass the frozen oracle while permitting cross-worker memory corruption.

> ⚠ Codex usage unaccounted: OperationalError: table turn_usage has no column named cost_unaccounted

## Round (2026-08-13T04:51:00Z)

## Re-review status

1. Identity sanitization — **FIXED**. Adversarial cases now cover path separators, `..`, empty/whitespace names, and the concrete cross-worker-memory escape.

2. Ownership roots constrained to `cwd` — **STILL BROKEN at integration level**. The pure decision oracle covers the empty-vs-emptied distinction, but hook installation does not.

3. Regression command/baseline — **FIXED**. Reproduced exactly: `8 failed, 41 passed`, comprising five #238 RED tests and the same three pre-existing #228 failures.

4. Duplicate matchers — **FIXED**. Multiplicity is checked before dictionary conversion.

5. T2 dependency/header — **STILL BROKEN partially**. The T1→T3→T2 ordering is honest and acceptable; splitting is unnecessary. However, the oracle header still says “Четыре теста” although the file now contains five tests.

## New findings

- **blocking** — [test_write_scope_hook.py:145](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-fan-research/docs/tasks/238/acceptance/test_write_scope_hook.py:145), [test_write_scope_hook.py:186](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-fan-research/docs/tasks/238/acceptance/test_write_scope_hook.py:186): The empty-vs-emptied asymmetry is tested only by calling `_write_scope_violation` directly. A wrong hook factory can sanitize `["../"]` to zero roots and then install no matchers; it passes T1b and the current T2 test, which checks only source-empty `owned_dirs=[]`. Add an armed integration assertion that `owned_dirs=["../"]` still installs all four matchers and denies `other/x.py`. This directly enforces the plan’s critical rule:

  > “непустой вход, из которого после санитизации не осталось ни одного корня → гейт РАБОТАЕТ”

- **suggestion** — [test_write_scope_hook.py:3](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-fan-research/docs/tasks/238/acceptance/test_write_scope_hook.py:3): Update “Четыре теста на три тикета” to five and describe T1b as T1’s second test.

## Verdict

**CHANGES REQUIRED.** The security model is substantially improved, and the T2 dependency argument is sound, but the frozen oracle still permits the exact fail-open transition introduced by sanitizing an invalid nonempty ownership list.

> ⚠ Codex usage unaccounted: OperationalError: table turn_usage has no column named cost_unaccounted
