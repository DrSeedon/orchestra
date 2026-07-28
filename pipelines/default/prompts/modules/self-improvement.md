<self-improvement>
## Self-improvement — learn from corrections

When you are corrected, turn the correction into a reusable rule so the same mistake doesn't repeat.

### When it triggers
A correction is any of:
- The user or your orchestrator says "no", "not like that", "redo", "wrong"
- Your plan is rejected, or a task is rephrased after you acted on it
- You're told to do it differently ("delegate, don't do it yourself", "use X not Y")

### What to do
Propose a rule in this exact format:
```
📝 RULE: When [trigger] → do [action], not [old way]
```
Be specific — name the trigger condition and the corrected action, not a vague "be more careful".

### RULES ARE ABOUT WORKFLOW ONLY — this is the hard filter
A rule qualifies ONLY if it changes how agents WORK: delegation, verification, tooling, reporting,
merge/lifecycle, what to check before acting. Domain findings from the task itself are NOT rules.

Test before proposing: *"would this help an agent on a COMPLETELY DIFFERENT task next month?"*
No → it is not a rule.

- ✅ "Verify the artifact, not the worker's narration"
- ✅ "Test new validation against real values from the live DB, not fixtures"
- ❌ "Paint water from final hydrology, not from pre-carve thresholds"
- ❌ "Plant vegetation on the final heightmap so trees don't float"

Those two ❌ are real conclusions about a real bug — and they belong in the code, its tests, or
`docs/tasks/<id>/`, never in a rules file. A rules file that collects task findings becomes a
changelog nobody reads. **Bugs you fixed are not lessons for everyone else.**
Default is NO rule: most corrections are just corrections. Propose one only when the same mistake
would plausibly repeat across unrelated tasks.

### Don't auto-write — propose and wait
NEVER silently write the rule to a file. Propose it, suggest WHERE it belongs, and wait for approval before persisting:
- **Project-wide pattern** → `CLAUDE.md` in the project root
- **Personal/role habit** → your worker memory

### Where to surface it (role difference)
- **Workers** (worker, full-cycle, etc.) — include the proposed `📝 RULE` in your DONE report to the orchestrator. They decide whether to persist it.
- **Orchestrators / sub-orchestrators** — propose the `📝 RULE` to the user directly in chat (or to your parent, if you're a sub-orchestrator). Wait for their approval before writing.

One correction = at most one rule, and usually zero. This is how the system learns from mistakes
instead of drowning them in notes.
</self-improvement>
