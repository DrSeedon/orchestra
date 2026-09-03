# grok-200

- Unifying a duplicated helper: re-export the function object (`from app.x import fn`), do not copy the corrected body. A test that builds fixture paths from the same helper it asserts against stays green when that helper is mutated — pin expected directory names as literals.
- A question to the orchestrator currently trips the fan barrier (platform bug, 14.08). Ask only when actually blocked, not “just in case”.
- `pipeline.yaml` is hand-edited. `scripts/extract-manifest.py` was a dead bridge from deleted `app/prompts/` — do not restore generation; `--check` only verifies roles/modules exist as files.
- `limit_wake` keys off `content LIKE 'turn ended%'`; percentages come from `current_provider_usage`, not the TG suffix.
- `wait_for(..., timeout=0.1)` in tests: 0 on 14.08. The short ones now are `timeout=0.05` in `test_tg_bridge.py` (4).
- Flake `cards==0` after `wait_for_timeout(5000)`: wait for `.chat-notify-user` and stream reconnect count, never the clock.
- `create_session(parent_name=...)`: missing session → `_resolve_role` returns `None` → `validate_spawn` treats it as **root**, not as unknown role. Unknown **role** is a live parent session whose `role` is absent from the manifest. A test named fail-open that passes a ghost parent_name stays green after a fail-closed inversion.
- Grok probes: own `GROK_HOME` under `/tmp`, never write `~/.grok/`. Do not force a live refresh (`GROK_AUTH_EARLY_INVALIDATION_SECS` + real `refresh_token`) — it can rotate the prod token. Dead auth is loud: missing file → `ensure_grok_home` RuntimeError; present-but-dead → ACP `session/new` `Authentication required`. `linux rename()` onto a symlink replaces the link; `ensure_grok_home` then deletes that regular file and re-links.
