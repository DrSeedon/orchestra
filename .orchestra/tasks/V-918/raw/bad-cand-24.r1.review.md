## Summary

Reviewed the complete diff between the specified commits, including the bridge changes, tests, and task documents. The per-chat limiter, bounded retries, formatted-message splitting, and file retry handling are consistent with the delivery goal. I did not run tests or edit files.

## Findings

### Blocking

None found.

### Suggestion

- In `_tg_send_safe()` and `_tg_edit_message_safe()`, any `TelegramBadRequest` with entities is treated as an entity-format rejection. Other bad requests—such as an invalid topic or inaccessible chat—therefore trigger a second request without entities, which cannot fix the underlying error and can obscure the cause. Consider limiting the fallback to entity-related errors and logging other bad requests directly.

### Question

None.

## Verdict

APPROVED — no blocking findings.