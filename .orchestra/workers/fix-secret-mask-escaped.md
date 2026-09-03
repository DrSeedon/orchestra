# Personal memory

- Codex MCP tool arguments are serialized by `_tool_arguments_json()` and then reserialized by
  `_tool_use()` after `_codex_item_id` injection. A string-valued argument containing JSON turns
  the inner key terminator into `backslash + quote + colon`; secret-mask oracles must construct
  input through those production serializers, not a flat hand-written fixture.
- For the dashboard log mirror, invalidate sensitive cached content with a same-version atomic
  `logs + meta` read/write transaction and a content epoch. Do not use an IndexedDB version bump,
  `deleteDatabase()`, or call the shared transaction wrapper through an unresolved open promise.
