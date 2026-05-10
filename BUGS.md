# Orchestra Bug Reports (from agents)

No open bugs.

## [2026-05-09 12:27 UTC] Worker idle mid-task: likely max_turns=25 exhaustion, not output token limit
- **Reporter:** Parsing-orchestrator
- **Scope:** /mnt/data/Projects/Python/Parsing
Follow-up from Orchestra-orchestrator investigation. Workers going idle mid-task is likely NOT output token limit (Sonnet 4.6 has 16384, plenty). More probable causes:

1. max_turns=25 exhaustion — large tasks (S1 with 6 subsections, many file edits) easily burn 25 turns
2. Sonnet misinterprets task completion — thinks it's done when it's not

Fix applied to worker system_prompt: "report progress after each major step via send_message, don't wait for full completion." This ensures partial results survive even if turns run out.

TODO: 
- Check if max_turns is configurable per-worker at spawn time
- Add stop_reason logging to understand exact cause per case
- Consider max_turns=50 for large tasks

## [2026-05-10 03:47 UTC] Orchestrator misses new user message when finishing previous task
- **Reporter:** Orchestra-orchestrator
- **Scope:** /mnt/data/Projects/Python/orchestra
When user sends a new message while orchestrator is finishing a previous task (e.g. killing worker, updating TODO), the orchestrator responds to the previous task and ends turn with stop_reason=end_turn without addressing the new message. The new message gets injected but the orchestrator doesn't process it. Seen at 10:46:53 — user asked about worktree fix, orchestrator answered about TG media instead.

## [2026-05-10 03:57 UTC] Batch messages from TG trigger multiple turns instead of one
- **Reporter:** Orchestra-orchestrator
- **Scope:** /mnt/data/Projects/Python/orchestra
When user sends multiple messages rapidly in TG (e.g. forwarding several files), each message triggers a separate send() → separate turn → separate response. Should batch them. The session debounce (2.5s) is too short for TG media downloads which take several seconds each. Result: orchestrator responds multiple times to what the user intended as a single batch.
