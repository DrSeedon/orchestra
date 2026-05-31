<codex-review>
## Codex review (cross-LLM review via GPT-5.5)

Run Codex review via the `codex_review()` MCP tool ONLY — never via bash or a skill. Never invent codex commands from memory.

### When to call
- **Reviewing a plan** → `mode="exec"` (Codex reads the target file you point at)
- **Reviewing an implementation** → `mode="review"` (Codex reviews the git diff)

### Syntax
```
codex_review(target="docs/tasks/<id>/plan.md", output="docs/tasks/<id>/codex-review-plan.md", mode="exec")   # plan
codex_review(output="docs/tasks/<id>/codex-review-impl.md", mode="review")                                    # implementation (diff)
```
- `target` — file to review (required for `exec`, omitted for `review`/diff)
- `output` — where findings are written (always under `docs/tasks/<id>/`)
- `context` — extra instructions for the review prompt; **always pass the PROJECT CONTEXT block here** so Codex calibrates severity

### Iterate to consensus
1. Read Codex findings (in the `output` file)
2. Verify each finding against the actual code — Codex can be wrong; do not blindly apply
3. Fix blocking/critical findings
4. Re-run `codex_review` until no blocking findings remain
5. If you disagree with Codex after verifying — document WHY in the output file and let the orchestrator decide

### PROJECT CONTEXT block (pass via `context`)
```
PROJECT CONTEXT (calibrate review severity):
- Scale: small team, MVP stage
- Users: ~10 active, NOT millions
- Philosophy: simple, flat, minimal abstractions. 3 lines > premature abstraction
- "blocking" = crash/corrupt/security. "suggestion" = real improvement. "nit" = skip
```
</codex-review>
