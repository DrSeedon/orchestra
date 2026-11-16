# Bounded Astra R2 correction wave
- Base 120cb528faaefcf0fddd688e4ab300469aeb3fc8; one writer, isolated remote worktree.
- No production/account/provider settings edits, no real agy/Google calls/credentials.
- R1 fixes tests: 13 passed, 1 fixture assertion failed. Fake ACK preamble contained
  INITIAL_CONTEXT from the verbatim tail, so fake itself reported 700 instead of200.
  Corrected fake context discriminator once; no product assertion weakened.
- R2 fixes tests: 15 passed, including normal _ensure_backend/_make_backend/event loop,
  durable structured bans, actual model confirmation, real HTTP receipt/interrupt/compact.
- Old fake finish_ack test was removed from the NEW review file and replaced by stronger
  real lifecycle tests; frozen original tests untouched.
- Acknowledgement context uses typed occupied-window report, not unknown billed totals.
  Unknown ACK context gives null post/after/dropped in receipt and known=false in state.
- Timeout diagnostic: exact original four-file command retained in timeout-command.json.
  29 items collected; first node test_compact_pending_ack_467.py::test_pending_user_input_waits_until_compact_ack_succeeds
  never completed before timeout60s (exit124); captureoff, faulthandler disabled. No SIGSEGV.
  Relationship to ACP ACK defect not proven; no repeat of that bundle, no timeout increase.
  Root cause remains unresolved, acceptance RED.
- Parent owns next independent review of the final immutable commit, no local reviewer.
