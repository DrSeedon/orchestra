# STATE.md — Orchestra (`agy-acp-safe`)

- **Updated:** 2026-11-17 (Step 1 isolated live stand completed — `LIVE_CYCLE_PASS` substance, `0` retries).
- **Worktree / Branch:** `/home/kesha/orchestra-worktrees/agy-acp-safe` (`agy-acp-safe`), production `/home/kesha/orchestra` untouched at `4e4e58dcb` (`disabled_providers.json = ["antigravity", "claude", "grok"]`).
- **Authorized Single Live Cycle (`10:24:15Z – 10:31:28Z`, `:18889`, `PID_ACP = 2171216`):**
  - `10s` idle precheck: `0` `agy-vendor.elf` processes, `0` RPCs, passive `/api/stats` & `/api/usage`.
  - Turn 1 (`stand-ceo`, `antigravity/gemini-4-hydrogen-medium`): `initialize=1`, `authenticate=1` (`oauth-personal` via NL `178.93.29.64` `AS215294`), `session/new=1`, `session/set_config_option=1` (`gemini-4-hydrogen` + `medium`), `session/prompt` #1 -> `mcp_orchestra_spawn_worker` -> HTTP owner `Allow` -> `end_turn` (`ctx:3%`).
  - Worker (`stand-calc-worker`, `gpt-6-luna`, `task #1`): wrote `calc_stand.py` + `test_calc_stand.py`, passed `python3 -m unittest` (`2` tests), committed `e4afcee8b5b3d029b9b428bdda80065aa95e72d5`, sent completion report to `stand-ceo` (`end_turn`, `44.98s`).
  - Turn 2 (`stand-ceo`): verified child report admitted, reused **same `PID_ACP = 2171216`** (`3.56s` warm session, `session/prompt` #2 `ok=true`, `end_turn`, `ctx:3%`).
  - Post-turn silence: **`356.65s`** (`10:25:31.18Z – 10:31:27.83Z`) with `0` new logs, `0` new RPCs, `0` `/quota` or `models` calls, `0` `nftables` `skgid 977` drops (`0 packets / 0 bytes`).
  - Cleanup: `:18889` stopped, `/tmp/orchestra-live-stand-20261117` removed, `0` leftover owned PIDs, `sandbox_home` (`119` hashes) unchanged, refreshed OAuth state saved (`0600`) in gitignored `acp_stand_profile`.
- **Post-Live Accounting Fix & Offline Suite:**
  - Fixed `AntigravityBackend._end()` (`event_id`, `num_turns`, `turn_duration_ms` -> `turn_usage` & `total_turns`) and driver `completed_turns()` for `CodexBackend` `total_turns == 0`.
  - Airgapped offline suite (`unshare --net`): **`221 passed, 0 failed`** across all 11 ACP test files + `check_instruction_contract.py` **PASS**.
- **Next Gate:** Await explicit owner decision before any merge/deploy or live production enablement.
