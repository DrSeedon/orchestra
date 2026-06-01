<codex-review>
## Codex review (cross-LLM review via GPT-5.5 Codex CLI)

**Run Codex via the Bash tool directly** — this is the primary path. You run in your worktree (your cwd), so Codex picks up git context and writes output files in the right place. You see Codex stdout in real time, so there is no black box and no "did it run?" guessing.

### Primary: Bash

**Review an implementation (git diff):**
```bash
timeout 300 codex exec review --uncommitted --full-auto --ephemeral --skip-git-repo-check -o docs/tasks/<id>/codex-review-impl.md 2>&1; echo "EXIT:$?"
```

**Review a plan or a specific file:**
```bash
timeout 300 codex exec -s workspace-write --full-auto --ephemeral --skip-git-repo-check -o docs/tasks/<id>/codex-review-plan.md "Review this file: docs/tasks/<id>/plan.md. PROJECT CONTEXT below. Write findings to the output. Format: ## Summary, ## Findings (blocking/suggestion/nit), ## Verdict.

<paste PROJECT CONTEXT block here>" 2>&1; echo "EXIT:$?"
```

### Rules for the Bash call
- **Always wrap in `timeout 300`** (5 min hard cap). Codex review is 60-120s, exec 60-300s. If it hangs, `timeout` kills it and you see a non-zero exit
- **Pass `timeout: 300000` to the Bash tool itself** — the Bash tool defaults to 120s and would cut Codex off otherwise
- **Check `EXIT:$?`** — non-zero = Codex failed. Do NOT pretend a review happened. If it failed, retry once, then report the failure to your orchestrator (do not silently skip review)
- **Never claim "Codex is running" / "Codex approved" without seeing its stdout and the output file.** No hallucinated processes — if you didn't see the output, it didn't run
- `-o <file>` writes Codex's final message; read that file after the Bash call returns

### Legacy fallback: codex_review() MCP tool
Use ONLY if Bash is unavailable (e.g. a Codex-backend worker without a Bash tool), or if the Bash path fails twice:
```
codex_review(target="docs/tasks/<id>/plan.md", output="docs/tasks/<id>/codex-review-plan.md", mode="exec")   # plan
codex_review(output="docs/tasks/<id>/codex-review-impl.md", mode="review")                                    # diff
```
- Runs async via a background job. If no output file appears within ~3 min, treat it as **failed** — do not wait indefinitely. Switch to the Bash path or report to orchestrator
- Never via raw `codex` commands invented from memory other than the ones above

### Iterate to consensus
1. Read the findings file
2. Verify each finding against the actual code — Codex can be wrong; do not blindly apply
3. Fix blocking/critical findings
4. Re-run until no blocking findings remain (each run still capped at `timeout 300`)
5. If you disagree with Codex after verifying — document WHY in the output file and let the orchestrator decide

### PROJECT CONTEXT block (always pass it to Codex)
```
PROJECT CONTEXT (calibrate review severity):
- Scale: small team, MVP stage
- Users: ~10 active, NOT millions
- Philosophy: simple, flat, minimal abstractions. 3 lines > premature abstraction
- "blocking" = crash/corrupt/security. "suggestion" = real improvement. "nit" = skip
```
</codex-review>
