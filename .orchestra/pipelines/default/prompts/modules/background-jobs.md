## Background jobs — what the tool description does not tell you

Types, parameters and examples live in the `bg_create` tool description; it is the owner, and
`base.md` already carries the "never sleep or poll" rule. Only these are yours:

- **`message` must explain WHY, not WHAT to check.** It is read by a future agent with none of
  today's context: "REMINDER: add a 10% salary increase from December 2026", not "check X".
- **Never create a timer to retry a delivery.** A message or first task that the quota gate
  holds back is accepted into a durable queue (`WAITING_QUOTA`) and goes out by itself, in
  order, when the gate opens — also after a restart. The receipt gives an estimate; do not
  wake yourself to "retry in N hours": each such wake is a paid turn. If a send call's own
  outcome is ambiguous, repeat the same call with the same delivery id; accepted calls are
  idempotent. To withdraw a queued message use `cancel_message_delivery`.
- **A job you created is yours to cancel.** A recurring job outlives the reason it was created;
  when that reason is gone, `bg_cancel` it instead of letting it wake agents forever.
- **A worker report needs no watchdog.** If a worker turn ends without a message (error,
  interruption, process death, or an Orchestra restart), the platform sends one durable
  `[auto-report]` message: who ended, how the turn ended, and the last output. A normal DONE does
  not duplicate it. Do not create a `bg_create` job or wait on a timer for this. When you receive
  `[auto-report]`, check the actual result, not only its text: it proves the turn ended, not that
  the work succeeded.
