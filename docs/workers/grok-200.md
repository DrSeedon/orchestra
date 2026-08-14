# grok-200

- Unifying a duplicated helper: re-export the function object (`from app.x import fn`), do not copy the corrected body. A test that builds fixture paths from the same helper it asserts against stays green when that helper is mutated — pin expected directory names as literals.
- A question to the orchestrator currently trips the fan barrier (platform bug, 14.08). Ask only when actually blocked, not “just in case”.
- `pipeline.yaml` is hand-edited. `scripts/extract-manifest.py` was a dead bridge from deleted `app/prompts/` — do not restore generation; `--check` only verifies roles/modules exist as files.
- `limit_wake` keys off `content LIKE 'turn ended%'`; percentages come from `current_provider_usage`, not the TG suffix.
- `wait_for(..., timeout=0.1)` in tests: 0 on 14.08. The short ones now are `timeout=0.05` in `test_tg_bridge.py` (4).
