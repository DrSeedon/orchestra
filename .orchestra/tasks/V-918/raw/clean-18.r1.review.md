## Summary

Reviewed the complete diff between the specified commits. The production change enables Codex thread resume across model switches; its test checks that reconnect receives the new model and preserved thread ID. No blocking crash, corruption, or security issue found.

## Findings (blocking/suggestion/question)

**Suggestion** — `app/runtime_registry.py`: Preserving the thread also preserves `_last_context`, including the previous model’s context percentage and limit. Those values feed operator status and precompact scheduling; Codex models can have different context windows. Consider refreshing or marking context state unknown on a model switch, and handling any pending precompact timer, until the new model reports its context.

## Verdict

APPROVED — with the context-state improvement noted above.