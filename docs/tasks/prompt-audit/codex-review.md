## Summary

The audit is directionally useful, and its top finding about orchestrator custom `system_prompt` replacing the role template is technically correct and high-impact for determinism. However, it overstates several token-efficiency findings and makes two material enforcement claims that are wrong against the current backend:

- Built-in `Agent`/`Task` is stripped only for orchestrators via `disallowed_tools`; workers still get `_disallowed_tools(False) == []`, so the base prompt rule against built-in Agent remains load-bearing for workers.
- `run_in_background` is not in `_BLOCKED_TOOLS`, but it is still denied by `_make_auto_approve()` for any tool input containing `run_in_background`.

For an MVP where predictability matters more than prompt minimalism, the audit should downgrade most "remove prompt text because harness enforces it" recommendations. Keep short explicit guardrails where they prevent wrong tool choice, even if the backend also fails loud.

## Findings

blocking: `manager.py:391-393` asymmetry is real and severity is calibrated correctly. Orchestrator custom prompt uses `system_prompt or ROLE_SYSTEM_PROMPT(role, scope)`, so any custom prompt discards the orchestrator role, decision tree, tool rules, worker catalog, and modules. Worker prompt assembly appends custom text to the role template. This is a genuine determinism bug, not an enterprise concern.

suggestion: The audit incorrectly says the built-in Agent/Task rules are "dead" because the model cannot call them. That is only true for orchestrators. In `backend_claude.py`, `_disallowed_tools(True)` returns `["Task", "Agent"]`, but `_disallowed_tools(False)` returns `[]`; workers are protected only by prompt text for built-in subagent delegation. Recommendation: do not remove the base "NEVER use built-in Agent" rule unless workers also get CLI-level disallow.

suggestion: The audit incorrectly classifies `run_in_background` as unenforced except by prose. `_make_auto_approve()` denies any dict tool input with `run_in_background`. The prompt rule is still useful because it avoids a wasted denied call and explains the alternative, but the audit should not present it as solely prompt-enforced.

suggestion: The `claude_code` preset duplication finding is plausible but over-severe and under-evidenced. From the code we know Orchestra appends to the preset; we do not know from these code facts exactly which preset instructions are present or how stable they are. For MVP determinism, do not remove local rules like "Respond in the same language" or file-persistence guidance solely because the preset or `CLAUDE.md` may cover them. Treat this as a low-risk cleanup only after observing real prompt conflicts or measurable token pressure.

suggestion: The recommendation to delete or heavily shrink `orchestrator.md` tool references is risky if applied broadly. MCP descriptions describe individual tools, but the role prompt gives one-path routing: which tools are orchestrator-approved, when to spawn/reuse/kill/merge, and task-reference conventions. Removing dry duplicate signatures is fine; removing the canonical tool map would hurt determinism.

suggestion: The audit missed an important stale prompt instruction in `app/prompts/roles/worker.md`: it tells workers to use the `codex-review` skill via `Skill(skill="codex-review")`, while the current system has a native `codex_review()` MCP tool and `full-cycle.md` explicitly says to use that, not bash/skill. This is a real prompt correctness issue because generic workers asked for Codex review may follow the obsolete path.

suggestion: The audit missed a small but concrete background-job drift: `base.md` documents timer/file/command/ssh/run and says jobs are one-shot, but `bg_create()` also supports `cron`, and cron is recurring. If cron is intended for agents, base should mention it or avoid the blanket one-shot statement. If cron is not intended, the MCP description should be restricted.

question: The `report_bug` conflict is correctly identified, but the proposed fix should stay narrow. Do not replace fail-loud with a more flexible taxonomy. A single line is enough: `report_bug` is for Orchestra platform/runtime/tooling failures; task-code bugs belong in task docs and the orchestrator report.

## Verdict

Revise before using as an implementation checklist.

Keep the P0 manager fix. Keep the `report_bug` clarification and targeted duplicate cleanup. Do not accept recommendations that remove Agent/Task guardrails from base, rely on undocumented preset behavior, or delete orchestrator tool-routing context for token savings. The audit is strongest when it improves one-path workflows; it is weakest when it optimizes prompt length at the expense of explicit deterministic instructions.
