# V-839 — Caller keys for Telegram file delivery

## Finding and change

The rejection was in `app/mcp_stdio.py`: both MCP tools stripped a supplied `event_id` and then called `uuid.UUID`, returning `invalid_argument` for readable keys. The internal API path is also UUID-only: `app/tg_file_deliveries.py::_validate_event_id` canonicalizes with `uuid.UUID`; `tg_file_deliveries` stores the value as a globally unique delivery key, and the receipt URL embeds that key. The route obtains the authenticated MCP session's project scope and sender before dispatching.

Normalization belongs at the MCP adapter boundary. This is where arbitrary caller keys enter, while preserving the established API/database identity format avoids changing queued receipts, spool directory names, or the schema. `app/file_delivery_ids.py::normalize_file_delivery_event_id` keeps UUID inputs in their existing canonical form and maps every other non-empty key to UUIDv5 over a JSON tuple containing a version tag, project scope, sender, and original key. This yields repeatable identity for retries and distinct keys across projects or senders. Empty inputs still get a random UUID as before. Both MCP tools use the same helper; `/api/tg/send_file` continues to receive canonical UUIDs.

## Verification

`uv run --frozen python -m pytest tests/test_mcp_stdio.py tests/test_tg_file_deliveries.py -q` passed: **146 passed**. The tests cover slug acceptance by `send_file` and `send_files`, stable receipt IDs across retries, UUID identity preservation, namespace separation by scope and sender, and one durable delivery row for a repeated scoped key. Imported helper path: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-api/app/file_delivery_ids.py`.

Mutation check: temporarily restored UUID-only parsing in the shared normalizer. The committed `test_file_delivery_keys_are_scoped_and_uuid_identity_is_unchanged` failed with `ValueError: badly formed hexadecimal UUID string`; the normalizer was restored and the full focused suite passed.

`git diff --check` passed. No schema or API response changes were made. Since only the per-session MCP adapter changes, a new MCP session loads the fix; **an Orchestra restart is not required**.
