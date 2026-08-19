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

**Pit of success.** Code where screwing up is hard.
- Flat structure, minimal indirection. Reads top to bottom
- One task = one pattern. Not two helpers for the same thing
- Explicit > implicit. No magic, no hidden side effects
- Fail loud — crash > silent bug. Errors must be visible immediately
- 3 duplicate lines > premature abstraction
</code-quality>
