<code-quality>
## Code quality

**Think before coding.** Check discoverable facts and state bounded assumptions. Ask only when
an unresolved choice changes scope, authority, material cost or an external contract.
Prefer the simplest complete solution; challenge a faulty premise with evidence.

**Simplicity first.**
- Minimum code that solves the task. Nothing speculative
- No features beyond request. No abstractions for one-off code
- No comments except WHY (not WHAT), non-obvious decisions, docstrings on public API
- 200 lines where 50 suffice → rewrite

**Surgical changes.** Touch ONLY what the task requires.
- Don't "improve" neighboring code, formatting, comments
- Don't refactor what isn't broken. Follow existing style
- Noticed dead code → mention, don't delete unless your changes orphaned it

**Diagnostic rounds.** Batch independent read-only checks into one tool round with bounded
output and visible results for each check. Keep commands sequential when the next action
depends on the previous result; do not batch mutations or retries merely to save a round.

**Route code intelligence by question.**
- Literal text, paths, and current occurrences → `rg` first
- Python reachability, decorators, registries, or dead clusters → task-local AST plus `rg`; a zero from either alone proves nothing
- Known static-symbol rename → LSP/Serena is optional, then `rg` strings/comments/config/templates and run tests
- Delete as unreachable only with a production-root proof and a mutation that makes the acceptance test fail
- **A mutation proves nothing unless the test it reddens is COMMITTED.** A throwaway probe dies with your turn and guards nobody. Measured 25.08 (#398): a worker reported both fixes mutation-checked, and disabling one of its own fixes afterwards left the named suite green — `35 passed, RC=0` — because no test had entered the repository. Report a mutation only against a test that is in your diff.
- A green regression command does not settle an unreproduced defect. Inspect the reported path,
  reproduce it and add a meaningful check. Use test-first work when the contract is known;
  exploratory diagnosis need not manufacture a frozen test before understanding the failure.

**Test the core, never the wording (owner's decision 06.09.2026, verbatim: «тесты нужны только
на кор фичи которые не будут меняться… а не хуйню которую мы хотим поменять… ебанные тесты палки
в колеса»).** This project changes constantly; a test that fails because we deliberately changed
something is not a guard, it is a brake.
- **Never assert a literal phrase of a prompt, rule, report or document.** No anchor lists of
  quotes, no "this exact sentence must be present/absent". Such a test reddens when the OWNER
  rewrites a rule — it reports his decision back at him as a failure. Measured 06.09: 23 such
  tests were deleted at once, and not one of them had ever caught a defect; three were red at
  that moment purely because the wording and the docs had legitimately moved on.
- **Do test the mechanics that carry the wording**: that a module reaches every role, that one
  role's prompt does not leak into another, that an index is assembled from its single source.
  Those catch real loss — a role silently losing an entire layer of rules was found exactly this
  way (#490).
- Before adding any test, answer in one line: *what breaks in production if this is missing?*
  Cannot name it → do not write the test. "It documents the current text" is not an answer.
- Test the core that must not change: data integrity, authorization, money and quota accounting,
  lifecycle transitions, concurrency, recovery, external contracts. Leave prose, formatting,
  ordering of sections and internal naming untested.
- Finding a brittle wording test while doing something else → delete it in that same change and
  say so in the report. Do not "fix" it by updating the quote.

**Pit of success.** Code where screwing up is hard.
- Flat structure, minimal indirection. Reads top to bottom
- One task = one pattern. Not two helpers for the same thing
- Explicit > implicit. No magic, no hidden side effects
- Make errors visible. Fail the unsafe operation; optional bookkeeping or unavailable metadata
  must not crash an otherwise valid task.
- 3 duplicate lines > premature abstraction
</code-quality>
