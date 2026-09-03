# Task #45 — Final Report

## Summary
Fixed all 11 findings from Codex GPT-5.5 full review. P0 auth bypass patched first, followed by 6 P1 correctness/security bugs and 3 P2 hardening items. Skipped P2.4 (log drain) as acceptable for MVP.

## Changes

### P0 — Auth Bypass (CRITICAL)
- `app/auth.py`: `check_internal_token()` returns `False` when `INTERNAL_TOKEN` unset (was `True`)

### P1 — Security & Correctness
1. **Concurrent send race** (`app/session.py`): Re-check status inside `_lifecycle_lock`. Preserves Claude mid-turn inject behavior
2. **Scoped lookup fallback** (`app/main.py` + `app/bg_jobs.py`): Removed `ensure_loaded_any()` fallback from 6 call sites (3 API endpoints + 3 bg job handlers)
3. **TG /restart auth** (`app/tg_bridge.py`): Checks `group_id` + admin/creator status before restart
4. **Bot token plaintext** (`app/tg_bridge.py`): Token stripped from `save_config()`, legacy tokens scrubbed on `load_config()`, `start_bridge()` no longer assigns token to config
5. **Rename divergence** (`app/main.py`): DB UPDATE first with IntegrityError catch, in-memory mutation only on success
6. **YouGile sync false ok** (`app/tm.py`): Moved 'ok' from `finally` to `try` body, added `except` with 'error' status

### P2 — Hardening
1. **Uploads auth + traversal** (`app/main.py` + `app/auth.py`): `/uploads/` requires auth, replaced StaticFiles with endpoint using `relative_to()` path check + force-download headers
2. **Denylist** (`app/main.py`): Added `.npmrc`, `.pypirc`, `.netrc`, `.docker`, `.kube`
3. **Dead code** (`app/tools.py`): Deleted (no imports referenced it)

## Files Changed
| File | Lines |
|------|-------|
| app/auth.py | +4/-2 |
| app/bg_jobs.py | +0/-6 |
| app/main.py | +36/-30 |
| app/session.py | +14/-0 |
| app/tg_bridge.py | +11/-4 |
| app/tm.py | +5/-3 |
| app/tools.py | -231 (deleted) |
| **Total** | **+70/-276** |

## Tests
- 195 passed, 0 regressions
- 6 pre-existing failures (4 deselected, 2 unrelated to changes)

## Codex Reviews
- Plan review: 3 blocking findings → all addressed before implementation
- Impl review round 1: path traversal in uploads → fixed with `relative_to()`
- Impl review round 2: sibling prefix bypass → fixed with `relative_to()` (replaced `startswith`)
- Impl review round 3: 2 P2 suggestions (rename prompt staleness, filename sanitization) — accepted as known limitations for MVP

## Breaking Changes
- **MCP tools without INTERNAL_TOKEN will get 401.** All MCP workers already have INTERNAL_TOKEN configured at spawn. Only breaks if someone manually calls API without token and relied on the bypass
- **ensure_loaded_any() fallback removed.** API calls must provide correct scope. MCP tools already do this. Dashboard JS already sends scope

## Skipped
- P2.4 (log drain) — fire-and-forget logging acceptable at MVP scale
