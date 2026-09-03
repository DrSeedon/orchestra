# Codex review — plan (GPT-5.5)

Note: Codex ran in the main-repo checkout (plan.md lives in the worktree), so it evaluated the
DESCRIBED approach against current code paths. Verdict below.

## Verdict
**Proceed.** No production-blocking design issue. Implementation must wire EVERY persist/restore
path and must NOT reprice rows when raw token accounting or model pricing is absent.

## Key points (resolved into plan)
1. **Explicit fallback predicate** — recompute only when persisted raw cache totals are known to
   exist; all-zero rows → fallback to stored `cost_usd_cached`. Old rows get DEFAULT 0, but a valid
   new session can also have zero cache. MVP rule: any nonzero raw token total → recomputable;
   all-zero → fallback. Optional future marker `cost_tokens_v1 INTEGER DEFAULT 0` if exact zero-cost
   new rows ever matter — NOT needed now.
2. **Formula mirrors backend exactly** (`backend_claude.py:396`):
   `(input*p_in + cache_read*p_in*0.1 + cache_create*p_in*1.25 + output*p_out)/1e6`.
   Do NOT recompute from `cost_usd`. Do NOT add `cached_input_tokens` separately (backend already
   exposes cache_read/cache_create).
3. **Guard model pricing misses** — `TOKEN_PRICES` omits Codex (models.py:76); OpenCode/native-cost
   backends must NOT be repriced with Anthropic multipliers. If `TOKEN_PRICES.get(model)` is missing
   → fallback to stored `cost_usd_cached` (never zero, never drop the row).
4. **Migration additive + idempotent** — `ADD COLUMN ... INTEGER DEFAULT 0` behind `if not in cols`,
   matching total_input_tokens pattern (db.py:321). No backfill — do NOT reconstruct raw cache
   tokens from cost_usd_cached.
5. **Tests** — 3 boundaries: (a) old row with only cost_usd_cached → reports stored value;
   (b) new row with input/output/cache totals → recomputes under changed TOKEN_PRICES;
   (c) Codex/OpenCode/no-price row → falls back to stored cached cost.

## Impact on plan
T4 open question RESOLVED. Final rule for `_get_agents_cost`:
```
prices = TOKEN_PRICES.get(model)
has_raw = (total_cache_read_tokens or 0) > 0 or (total_cache_create_tokens or 0) > 0
if prices and has_raw:
    cost_cached = recompute(...)   # backend formula
else:
    cost_cached = stored cost_usd_cached   # fallback (old rows, codex, no-cache)
```
