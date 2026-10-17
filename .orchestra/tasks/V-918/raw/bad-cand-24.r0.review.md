## Summary

Reviewed the complete diff from `8251d024700ee23d61a9b6477576c15eb3d63fb2` to `18309d4fdac88c60904bbf7fc4d5f3ca29bcc5f8`. The per-chat serialization, bounded retries for important sends, plain-text fallback for rejected entities, and post-conversion length checks address the stated delivery risks.

## Findings (blocking/suggestion/question)

- **Suggestion** — Topic status changes can be silently dropped and remain stale. `_update_topic_status()` calls `_tg_call_safe()` with its default `important=False` ([app/tg_bridge.py](/home/kesha/v918-work/v918-bad-cand-24.r0-gyyjobxt/app/tg_bridge.py:1011)). If another call holds the chat lock or the group interval has not elapsed, the update returns `None`; the status cache is left unchanged, but there is no guaranteed later retry when the stream becomes idle. This can leave a topic showing “running” after a turn ends, or miss its transition to “running.” Consider preserving the latest desired status and retrying it after the chat becomes available.

## Verdict

APPROVED — no blocking findings.