# Codex review — plan

**Reviewer:** GPT-5.5, isolated read-only CLI fallback.  
**Target:** `plan.md` checked against `app/tg_bridge.py` and `tests/test_tg_bridge.py`.  
**Verdict:** no blocking findings; plan is fit for implementation after four clarifications.

## Findings and resolution

- **suggestion:** distinguish Telegram `bot.send_message` coverage from the `"send_message"` tool pretty-render branch. **ACK:** T2 AC names both paths.
- **suggestion:** mirror file delivery also needs a fresh `FSInputFile` on retry. **ACK:** T2 AC requires primary and mirror recreation/routing.
- **suggestion:** explicitly test the two edit helpers dropping before lock wait. **ACK:** T2 AC names `_edit_tool_with_result()` and `_edit_expandable()` and forbids invoking `edit_message_text` while busy.
- **question:** decide whether an important retry holds the lock. **Resolved:** it holds the per-chat lock through `retry_after`/network backoff, preventing overtaking and retry stampedes; T1 AC now fixes this contract.

## Verdict

No unresolved blocking or disagreement. The tickets remain vertical and acyclic: reliable text, then media/edit/file coverage, then integrated evidence.
