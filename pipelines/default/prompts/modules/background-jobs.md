<background-jobs>
## Background jobs — the two things the tool description does not tell you

Types, parameters and examples live in the `bg_create` tool description; it is the owner, and
`base.md` already carries the "never sleep or poll" rule. Only these are yours:

- **`message` must explain WHY, not WHAT to check.** It is read by a future agent with none of
  today's context: "НАПОМИНАНИЕ: начислить надбавку 10% к окладу с декабря 2026", not "check X".
- **A job you created is yours to cancel.** A recurring job outlives the reason it was created;
  when that reason is gone, `bg_cancel` it instead of letting it wake agents forever.
</background-jobs>
