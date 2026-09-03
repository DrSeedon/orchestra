## Summary

No blocking findings. The admission gate is atomic at all three sites: `send()` (`app/session.py:1026`), `_flush_pending()` (`:1725`), and compact acknowledgment (`:2174`) have no `await` before `status = RUNNING`. `send()` releases `_lifecycle_lock` in `finally`; refusal occurs before state mutation, so it neither leaks the lock nor strands the session as `RUNNING`.

The drain loop yields once per second, uses a monotonic deadline, and terminates unconditionally. The final `cut` list is one synchronous snapshot taken after admission closes. Prompt-rebuild fallback preserves the previous overlay and refreshes worker memory; full operator prompts remain guarded by `prompt_overlay is None`.

Focused tests passed: `14 passed in 12.85s`.

Proof-of-reading line: `self._pending_messages[0:0] = msgs`

## Findings

suggestion: `app/routes/system.py:1743` — the drain only recognizes `RUNNING`; a Claude compaction can be actively generating its summary while `_compacting=True` and status remains `IDLE`, so restart may signal immediately and cut paid compaction work before the new acknowledgment gate is reached -> include `_compacting` sessions in the active-work predicate, or explicitly document and test that compaction is intentionally expendable.

suggestion: `app/routes/system.py:1725` — `_record_restart_outcome()` writes durable session logs only for `cut_ids`; a successful zero-cut drain therefore has no durable session-journal record despite the UI/TG message promising the result after restart -> record the summary in a durable system-level destination, or attach it to the initiating/session journal even when `cut_ids` is empty.

suggestion: `tests/test_hot_apply.py:230` — the internal-starter test covers only `_flush_pending` and `_auto_continue`; it would stay green if either `_rate_limit_retry`, `_retry_after_server_error`, or compact acknowledgment lost its dedicated drain handling -> add focused cases for the two retry paths and the compact gate, especially because compact refusal currently escapes auto-compact through its broad exception handler with only a warning.

## Verdict

Approved with suggestions. No blocking correctness issue found in the requested concurrency, lock-release, deadline, prompt-fallback, or async-mock review areas.

## Round (2026-08-12T10:44:51Z)

## Round 2

### Re-review status

- FIXED — compaction is now included through `AgentSession.is_busy`. The property is safe: `_compacting` is initialized on every constructed `AgentSession`, and sessions are not exposed through `manager.sessions` during partial construction.
- FIXED — the Telegram wording now accurately promises only per-cut-session notification. A system-wide durable zero-cut record is unnecessary for this scope; the unconditional server log is sufficient.
- FIXED — all four internal starters have behavioral coverage. No remaining `MagicMock` auto-attribute issue found.
- ACCEPTED GAP — compact acknowledgment lacks a behavioral gate test, but there is no cheap stable seam: reaching `start_ack_turn` requires traversing compaction summary generation and permit handling. Extracting a production seam solely for this test is not justified; the atomic adjacency remains directly reviewable.

### New findings

None. Focused tests passed: `16 passed in 13.53s`.

Updated-diff proof: `return self.status == AgentStatus.RUNNING or self._compacting`

### Verdict

APPROVED. No blocking findings remain.
