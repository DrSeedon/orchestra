## Summary

The vertical split and external ownership boundaries are mostly clear, but the plan has one credential-isolation flaw, one crash-consistency flaw, and two frozen RED tests that do not enforce their stated security/concurrency acceptance criteria.

## Findings

- **blocking:** [docs/tasks/249/plan.md:14](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-gemini/docs/tasks/249/plan.md:14) — Private `HOME` is not credential isolation when every Antigravity agent is granted `command(*)` and all processes run under the same Unix user. An agent command can read the canonical OAuth token or sibling worker homes directly; `--add-dir` is explicitly not a kernel sandbox. This violates the stated requirements for credential isolation and no cross-worker state access. The design needs an enforced filesystem boundary or a credential-delivery mechanism inaccessible to agent-launched commands.

- **blocking:** [docs/tasks/249/plan.md:25](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-gemini/docs/tasks/249/plan.md:25) — Two `os.replace` calls under `flock` are mutually exclusive but not crash-atomic. If the login process dies between replacements, the lock is released with a new token paired with the old generation. The next turn can therefore resume a native conversation belonging to the previous account. Store token and generation as one atomically replaced object/directory, or derive the generation from the token snapshot so mismatched pairs cannot exist.

- **blocking:** [tests/test_antigravity_runtime.py:397](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-gemini/tests/test_antigravity_runtime.py:397) — The “terminates only owned process” RED test creates no unrelated Antigravity process. An implementation using a global `pkill` could pass while killing other workers under production concurrency. Add a second live fake process with a distinct owner and assert it survives the interrupt.

- **blocking:** [tests/test_antigravity_runtime.py:342](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-gemini/tests/test_antigravity_runtime.py:342) — The secret-leak oracle checks argv and emitted event content, but the fake CLI never writes the MCP secret to stderr. A backend that forwards or persists stderr without redaction would pass despite the AC explicitly requiring secrets absent from stderr. Make the fake emit a sentinel secret on stderr and assert it is neither surfaced nor logged through the reviewed event seam.

- **suggestion:** [tests/test_antigravity_runtime.py:73](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-gemini/tests/test_antigravity_runtime.py:73) — The frozen capability contract requires `"subagents": True`, while the custom agent configuration asserted later requires `subagent: false`. Clarify whether `RuntimeCapabilities.subagents` means “this runtime may spawn subagents” or “this agent may be used as a subagent,” then make the plan and oracle express the same meaning.

## Verdict

**BLOCKING FINDINGS REMAIN**

## Round (2026-08-13T09:12:42Z)

## Summary

All five Round 1 findings are addressed. The replacement RED tests now cover the missing interrupt and stderr failure modes, and the revised rotation design removes the split-state crash window. No new blocker found.

## Findings

- **FIXED — crash consistency:** [plan.md:26](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-gemini/docs/tasks/249/plan.md:26) defines generation as SHA-256 of the exact token snapshot and publishes one file with one `os.replace`. [test_antigravity_readiness.py:295](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-gemini/tests/test_antigravity_readiness.py:295) verifies generation from both snapshots, exactly one replacement, and absence of the old marker.

- **FIXED — interrupt isolation:** [test_antigravity_runtime.py:402](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-gemini/tests/test_antigravity_runtime.py:402) starts an unrelated live process, proves it entered the body, and [line 446](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-gemini/tests/test_antigravity_runtime.py:446) asserts it survives interruption of the owned backend.

- **FIXED — stderr secret leakage:** [test_antigravity_runtime.py:127](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-gemini/tests/test_antigravity_runtime.py:127) deliberately emits the MCP token on stderr. The test separately checks argv, events, and DEBUG logs at [lines 347–378](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-gemini/tests/test_antigravity_runtime.py:347).

- **FIXED — native subagent capability:** [plan.md:96](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-gemini/docs/tasks/249/plan.md:96) explicitly excludes the unverified native lifecycle while preserving Orchestra delegation. [test_antigravity_runtime.py:75](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-gemini/tests/test_antigravity_runtime.py:75) now pins `subagents=False`.

- **RESOLVED BY SCOPE — same-UID confidentiality:** [plan.md:19](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-gemini/docs/tasks/249/plan.md:19) accurately defines the boundary as namespace/collision isolation and explicitly disclaims adversarial confidentiality between same-UID workers. That matches the clarified #249 acceptance scope.

No new findings.

Evidence line from the current artifact: “Soft-denied tool остаётся видимой ошибкой, а не terminal SUCCESS.”

## Verdict

**APPROVED**
