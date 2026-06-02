# Task #46 — Codex Debate Skill Analysis

Source: `vadim/v2-pipeline:app/skills/codex-debate/SKILL.md` (421 lines)

## What It Does

Codex Debate — adversarial cross-LLM review system. Claude (Anthropic) sends code/plans to Codex CLI (GPT-5.5, OpenAI) for independent review. Codex reviews, Claude verifies findings against code, fixes or disagrees, resumes session for next round. Loop until consensus or escalation.

Key difference from simple codex-review: **persistent sessions with multi-round debate**, not one-shot fire-and-forget.

## Architecture Breakdown

### 1. Frontmatter & Metadata
Vadim uses a different skill format (`app/skills/<name>/SKILL.md` with `roles: [all]`, `integrations: []`). We use `app/prompts/skills/<name>.md` with simpler frontmatter (`name`, `description`). The skill is injected into worktree's `.claude/skills/` at spawn time by `_inject_skills_to_worktree()`.

### 2. Core Principle — "Second Opinion, Not Truth"
The skill explicitly says Codex is a different model with different biases. Claude must:
- **Verify** each blocking finding against actual code before accepting
- **Debate** via resume if it disagrees (with code evidence)
- **Escalate** to user if Codex wants to delete functionality or change architecture
- **Never agree blindly** — that defeats the purpose

This is the most important section conceptually — it prevents the "yes-man" antipattern where Claude just applies everything Codex says.

### 3. Session Management (Persistent Sessions)
This is the key differentiator from our current codex-review module.

**Data model:**
```json
// <feature_dir>/codex_sessions.json
{
  "sessions": {
    "<slug>": {
      "uuid": "<codex-thread-id>",
      "topic": "plan review",
      "started": "2026-05-20T10:00:00Z",
      "last_used": "2026-05-20T10:15:00Z",
      "turns": 3
    }
  }
}
```

**Slug** = kebab-case topic identifier (e.g., `plan-review`, `code-review`). Used for:
- Filename: `codex_<slug>.md`
- Session key in `codex_sessions.json`
- Resume identification

**New session:** `codex exec -s workspace-write ...` → extract `thread_id` from JSONL output → save to sessions.json  
**Resume:** `codex exec resume "<uuid>" ...` → Codex has full context from previous rounds

Critical detail: `codex exec resume` does NOT support `-s` flag — sandbox is inherited from the original session.

### 4. Feature Directory Model
Vadim's project uses a `docs_work/<month_day>/<feature_name>/` directory structure. Each feature has its own folder where:
- `codex_<slug>.md` — review output (appended per round)
- `codex_sessions.json` — session registry
- `.codex_context.md` — optional project context cache

**Our equivalent:** `docs/tasks/<id>/` — we already have this pattern.

### 5. Process Flow

```
Pre-flight → Determine session (new/resume) → Run Codex → Extract UUID → Auto-iterate → Show result
```

**Step 0 — Pre-flight:**
- Check `codex` CLI exists
- Determine feature_dir, slug, project_root
- Create/load `codex_sessions.json`

**Step 1 — New vs Resume:**
- Check sessions.json for existing UUID under this slug
- UUID exists + user says "continue" → resume
- UUID empty or user says "fresh" → new session

**Step 2a — New Session:**
- Build prompt via temp file (avoids escaping issues)
- Run `codex exec -s workspace-write --json -o /tmp/codex-last-msg.txt - < /tmp/codex-prompt-$$.txt`
- Extract thread_id from JSONL: `jq -r 'select(.type=="thread.started") | .thread_id'`
- Save UUID to sessions.json
- Verify output file exists and Codex didn't touch other files

**Step 2b — Resume:**
- Load UUID from sessions.json
- Calculate turn number
- Run `codex exec resume "$UUID" ... - < /tmp/codex-prompt-$$.txt`
- Update sessions.json (last_used, turns)

**Step 3 — Ephemeral Mode:**
For one-off questions outside feature workflow. Uses `--ephemeral` flag, `read-only` sandbox. No sessions saved.

**Step 4 — Auto-iteration to Consensus:**
This is the "debate" loop:
1. Read Codex's output file, parse findings
2. For each **blocking** finding — verify via code (grep/cat/ls)
3. Decide: ACK / DISAGREE / PARTIAL
4. **Escalate to user** if Codex wants to delete functionality or change architecture
5. Fix ACK'd findings
6. Resume session with changelog
7. Loop until: Codex says APPROVED, 5+ rounds without progress, or escalation needed

**Step 5 — Show Result:**
Summary to user: verdict, finding counts by type, file path, next steps.

### 6. Conventional Comments Format
Structured finding format borrowed from Conventional Commits idea:

| Prefix | Meaning |
|---|---|
| `blocking:` | Must fix, merge impossible |
| `suggestion:` | Recommended improvement |
| `question:` | Needs author answer |
| `thought:` | Thinking aloud |
| `nit:` | Minor style issue |

Each finding: `<prefix>: file:line — problem → proposed fix`

### 7. Project Context Block
Calibrates Codex severity — without it, Codex reviews MVP code like enterprise. Template includes: stack, stage, scale priorities, severity calibration.

### 8. Prompt Templates
Four distinct templates:
- **Plan/spec review** — read plan, verify code references exist, find scope creep
- **Code review (diff)** — find test runner, read diff, find bugs/security
- **Debate (disagreement)** — Claude's counterarguments with code evidence
- **Re-review after fix** — status each previous blocking: FIXED/STILL BROKEN/NEW BUG

### 9. Error Handling
Covers: codex not found, billing issues (402), kernel sandbox (bwrap), stale sessions, rate limits, timeouts.

### 10. Technical Details
- Model: `gpt-5.5` with `model_reasoning_effort="high"` for reviews
- Sandbox: `workspace-write` (review) or `read-only` (ephemeral)
- Sessions stored in feature dir (not /tmp — survives reboot)
- Raw JSONL: `~/.codex/sessions/<year>/<month>/<UUID>.jsonl`
- Security: warn about .env/credentials in workspace-write mode

## Key Differences from Our Current codex-review Module

| Aspect | Current (codex-review module) | Vadim's codex-debate |
|---|---|---|
| Sessions | Ephemeral only (`--ephemeral`) | Persistent with resume |
| Rounds | One-shot, re-run from scratch | Multi-round debate, append to same file |
| Iteration | Manual (run again after fixes) | Auto-iterate until consensus |
| Output | Single file overwritten each run | Single file with appended `## Round N` sections |
| Verification | "verify each finding" (brief) | Explicit ACK/DISAGREE/PARTIAL with code evidence |
| Escalation | None | Escalate to user for deletions/arch changes |
| Prompt delivery | Inline in bash command | Temp file via stdin (`- < file`) |
| Session registry | None | `codex_sessions.json` per feature dir |
| Conventional Comments | No | Yes (blocking/suggestion/question/thought/nit) |

## Adaptations for Our Stack

1. **Proxy**: Our Codex runs via `HTTPS_PROXY=http://127.0.0.1:12334` — but Codex uses OpenAI, not Anthropic. We clear proxy: `HTTPS_PROXY= HTTP_PROXY= timeout 300 codex exec ...`
2. **Feature dir**: We use `docs/tasks/<id>/` instead of `docs_work/<date>/<feature>/`
3. **Frontmatter**: Our format: `name`, `description` (simple). No `roles`, `integrations`
4. **Module vs Skill**: The codex-review module stays as base instruction for workers. The skill adds debate capabilities for orchestrator/human-facing agents
5. **Bash wrapper**: All codex calls go through Bash tool with `timeout 300` and `timeout: 300000`
6. **No MCP codex_review fallback**: We keep our MCP fallback path from the existing module for workers without Bash
