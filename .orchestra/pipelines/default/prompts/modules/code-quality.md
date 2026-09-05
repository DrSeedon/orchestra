<code-quality>
## Code quality

**Think before coding.** State your assumptions. If multiple interpretations exist — ask, don't pick silently. If there's a simpler solution — say so. If the spec you were given has a flaw — push back.

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
- **A green command named in the assignment is a REGRESSION run, not the oracle of an unreproduced defect.** When the task asks you to reproduce something that is still broken, no oracle exists yet: write the failing test first, commit it alone as the frozen oracle with its `RC` recorded, and only then touch production. Measured 25.08 (#364): a worker read the regression command as its acceptance, found it already green, and stopped the task instead of reproducing the defect.

**Pit of success.** Code where screwing up is hard.
- Flat structure, minimal indirection. Reads top to bottom
- One task = one pattern. Not two helpers for the same thing
- Explicit > implicit. No magic, no hidden side effects
- Fail loud — crash > silent bug. Errors must be visible immediately
- 3 duplicate lines > premature abstraction
</code-quality>
