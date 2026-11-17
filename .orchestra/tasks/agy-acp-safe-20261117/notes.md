# Foreground wave notes
- Base f68c2335, remote candidate only. Required reports/T3 current source read statically.
- Native permissions/choice questions persisted with owner/session/epoch/transport/RPC/payload binding; no deferred mailbox resolver.
- First core run9passed/1failed. Second narrow order run still failed: task active after listener timeout.
- Existing synthetic traces proved fake prompt never reached prompt_end. Static cause found:
  fake update(sid, kind, **extra) collided with tool-call kind=execute keyword; TypeError before tool emission.
  Corrected fixture helper parameter to update_kind once, preserving assertions. No production protocol weakened.
- TG fake tests4passed: actual formatter/callback, owner/topic/CSRF ACL, cursor resume, unknown-send no replay.
- Receipt f68 gates retained; ordered journal isolated to new ACP session path, no global DB rewrite.

- Expanded core+TG:22passed; final additions (explicit fixed-profile restart/resume,
  null tool patch semantics, dead-app pending request, chunked TG ambiguity)26passed.
- Initial compatibility selection240passed/2dependency warnings (33.54s) before final
  namespaced tool IDs and rate-admission placement; final scoped verification follows.
- UI bounded attempts: R1 loaded actual renderers but fixture omitted utils.js locale;
  R2 reached native-card choice/response then overbroad visible-text assertion failed;
  final attempt reached native-card response but selector [data-last-tool] timed out
  (completion removes that transient marker). UI full acceptance remains OPEN; no more
  headless iterations in this wave. This is a fixture/result limitation, not a claimed
  successful tool-renderer/visual verdict. Native UI/RPC endpoint and ACL are separately
  integration-tested. No changes to product renderer were made just to satisfy fixture.

- Static UI fixture correction after final failed run: completed tool cards deliberately
  delete data-last-tool (chat.js), but keep data-tool-raw-name. The fixture now uses
  that stable selector; it was NOT rerun (headless iteration budget exhausted). Full
  UI result remains unverified/RED, not inferred green from this correction.
- First artifact proof: fake helper kind keyword collision fixed; ordered multi-turn
  pipeline subsequently passed and emitted actual durable DB + TG transcript.
- No additional helpers/reviewers, watcher configuration, real providers, accounts or TG.

- Final compatibility attempt246passed/1failed: newly added reconnect fixture wrongly
  expected a live thought while native card boundary had correctly flushed it durable.
  Fixture changed once to an explicit still-running thought-only fake turn. Product
  flush semantics unchanged. Cancellation callbacks now record cancelled ACP writes
  rather than throwing from done.result(), and fixture/session teardown awaits journal.
