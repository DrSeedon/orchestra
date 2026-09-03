# Review — #98 T3 (explicit model routing, catch-all removal)

Reviewer: `grok-backend` (Opus 5). Standing in for the Codex cross-review that
died on quota exhaustion.

Commit under review: `9abf4a2` — "#98 T3: explicit model routing, opencode
inventory, no catch-all". Diffs read as supplied (`/tmp/t3-models.diff`,
`/tmp/t3-rest.diff`); the worktree `grok-quota` was used only to *execute* the
post-change code, not to re-derive the diff.

## Method

Every claim below is either a number measured in this session or a line I
opened. No finding rests on reading the diff alone.

- Live DB was copied read-only to `/tmp/ro-orchestra.db` (`sessions`=339,
  `turn_usage`=799). No write ever touched `data/orchestra.db`.
- Every distinct `sessions.model` and `(backend_type, model)` pair from the
  live DB was pushed through the post-change `get_model_spec` /
  `resolve_model` / `backend_for_model`.
- Failure scenarios were *executed*, not hypothesised: the startup crash below
  was reproduced by monkeypatching `httpx.AsyncClient` and awaiting the real
  `refresh_models()`.
- Targeted suite re-run in `grok-quota`: `test_backend_routing`,
  `test_backend_grok`, `test_usage_analytics`, `test_usage_analytics_frontend`,
  `test_manager` → **234 passed in 6.94s**.

## Verdict

**No merge blocker.** The three risks I was asked to check are clean; I
verified each against live data rather than against the diff's intent. Two
findings below are real but are consequences of a *deliberate, tested*
fail-loud design meeting an unguarded caller — they are follow-up work, not
reasons to hold T3.

---

## Risk checks requested

### Risk 1 — catch-all removal vs. live sessions: **CLEAN**

All 8 distinct models in the live `sessions` table resolve after the change:

```
claude-opus-5[1m]     190   OK  rt=claude  prov=anthropic  ctx=1000000
gpt-5.6-sol            91   OK  rt=codex   prov=openai     ctx=258400
claude-sonnet-5[1m]    28   OK  rt=claude  prov=anthropic  ctx=1000000
claude-sonnet-4-6      19   OK  rt=claude  prov=anthropic  ctx=200000   ← COMPAT
claude-fable-5[1m]      7   OK  rt=claude  prov=anthropic  ctx=1000000
gpt-5.5                 2   OK  rt=codex   prov=openai     ctx=258400
grok-4.5                1   OK  rt=grok    prov=x-ai       ctx=500000
gpt-5.3-codex-spark     1   OK  rt=codex   prov=openai     ctx=128000
```

`claude-sonnet-4-6` — the one legacy id, 19 sessions — survives *only* because
`COMPAT_MODEL_SPECS` exists. That is exactly the migration the inventory said
was required, and it was actually done. `turn_usage` additionally holds
`claude-opus-4-8[1m]` (2 rows), also covered by COMPAT.

Sessions with an empty/NULL model: **0**. So the `get_model_spec("")` path
(see finding 2) is latent today, not live.

### Risk 2 — Grok records intact: **CLEAN**

`grok-4.5` → runtime `grok`, provider `x-ai`, context **500000**. Aliases
`grok`, `grok4.5`, `grok-build` all resolve to `grok-4.5`.

The load-bearing guard still holds:

```
resolve_model('x-ai/grok-4')  -> ValueError: unknown model 'x-ai/grok-4'
get_model_spec('x-ai/grok-4') -> ValueError
```

The provider-qualified id does **not** reach the native runtime. It now fails
harder than before (raise instead of opencode), which is strictly safer for
this particular test's intent.

### Risk 3 — legacy Opus/Sonnet remaps: **CLEAN**

```
claude-opus-4-8      -> claude-opus-5[1m]
claude-opus-4-8[1m]  -> claude-opus-5[1m]
claude-opus-4-6      -> claude-opus-5[1m]
claude-opus-4-6[1m]  -> claude-opus-5[1m]
claude-sonnet-4-6    -> claude-sonnet-5[1m]
claude-sonnet-4-5    -> claude-sonnet-5[1m]
```

Worth stating explicitly because it is subtle and *correct*: these ids exist in
**both** `ALIASES` (remap → current model, used when a human/agent asks for
them) and `COMPAT_MODEL_SPECS` (pinned legacy spec, used when a persisted
session already runs one). `resolve_model` remaps; `get_model_spec` pins. A new
spawn on `claude-opus-4-6` gets Opus 5; an existing session on
`claude-opus-4-6` keeps its own context length instead of being silently
re-specced. Both behaviours verified by execution.

---

## Findings

### F1 — one unroutable proxy model aborts the whole registry load and escapes into startup

`app/models.py:457-467` (`fetch_models_from_proxy`), reaching
`app/main.py:44` (`await refresh_models()`), unguarded.

The discovery comprehension is atomic: `_proxy_model_spec` raises on the first
id that has neither routing metadata nor a reviewed exact route, and the whole
batch is discarded. Aborting *before mutation* is deliberate and covered by
`test_unreviewed_proxy_model_without_route_fails_before_mutation` — I am not
disputing that choice. The gap is the caller.

Measured, by awaiting the real `refresh_models()` against a faked proxy
returning `[{"id": "moonshot/kimi-k3", "context_length": 256000}]`:

```
refresh_models PROPAGATES: ValueError invalid proxy model registry:
proxy model 'moonshot/kimi-k3' must declare runtime/backend
```

And the batching effect, measured on a two-model payload where only the second
is unroutable:

```
ENTIRE REFRESH ABORTS -> proxy model 'moonshot/kimi-k3' must declare ...
deepseek still registered afterwards: False
```

**Failure scenario.** The upstream proxy adds any new model id that carries no
`runtime`/`provider` field — an operator-side event, no deploy of ours needed.
On the next Orchestra start, `refresh_models()` raises inside the lifespan
before `_tm_mod.set_main_loop(...)` and before session auto-resume. The service
does not come up at all, and the good models in the same payload are lost too.
The enterprise retry loop at `main.py:49-56` is also unprotected, so the same
exception kills the retry task.

Note the asymmetry: an *unreachable* proxy is handled gracefully (falls back to
hardcoded models), but a *reachable proxy with one unknown id* is fatal. The
harsher path is the more likely one.

Suggested (not applied — review only): keep the strict per-model contract, but
catch `ValueError` at the `refresh_models()` call sites and log loudly +
fall back to the hardcoded registry, or skip-and-log the offending entries
rather than discarding the batch.

### F2 — `get_model_spec` has no total fallback, and one caller feeds it an empty string

`app/manager.py:783-786` (`_hydrate_row`) sets `model=row.get("model") or ""`.
`app/session.py:1761` (`to_dict`) then calls `get_model_spec(self.model).provider`.

```
get_model_spec('') -> ValueError: unknown model ''
```

**Failure scenario.** Any `sessions` row with a NULL/empty `model` — a partially
written spawn, a hand-edited row, a future migration — is hydrated fine, but
serialising it raises. `to_dict` backs `/api/sessions`, `/api/orchestrators`
(`routes/system.py:1046`) and the MCP session views, so a single malformed row
takes down the whole list response, not just its own entry. Today: **0 such
rows**, so this is latent.

Related, same root cause: `get_model_spec` is also the one function with no
safe path when `MODEL_SPECS` is empty. In enterprise mode with the proxy down,
`_clear_selectable_models()` wipes the registry, and I measured that even
`claude-opus-5[1m]` then fails to resolve while `claude-sonnet-4-6` still works
(it lives in COMPAT, which is never cleared). So a proxy outage degrades
*current* models harder than legacy ones — an inversion worth knowing about.

Suggested: give `_hydrate_row` the same treatment the diff already gave
`AgentStatus` two lines above it (try/except → conservative default), or let
`to_dict` fall back to provider `"unknown"`.

### F3 — `_cache_ttl_case` is correct but silently depends on dict insertion order

`app/usage_analytics.py:41-52`.

Not a bug — I checked, and I want the dependency on the record because it is
invisible. `branches` emits one `WHEN ... THEN ?` per provider *except*
`unknown`, then one trailing `ELSE ?`, giving N placeholders. `ttls` is built
over all of `_PROVIDERS`, giving N values. These line up **only** because
`unknown` is last in `PROVIDER_METADATA`'s literal:

```
PROVIDER_METADATA order: ['claude', 'codex', 'grok', 'opencode', 'unknown']
```

so the ELSE placeholder consumes `ttls[-1]` = unknown's TTL. Verified correct
as written. But if anyone adds a runtime *below* `unknown` in that dict, the
ELSE binds the new runtime's TTL and every unclassified row is scored against
it — wrong numbers, no exception, no failing test. A one-line
`sorted(..., key=lambda p: p == _FALLBACK_PROVIDER)` or an explicit
`_PROVIDERS = (...non_fallback..., _FALLBACK_PROVIDER)` construction would make
it structural instead of incidental.

---

## Things I checked and found genuinely good

- **`_provider_case` legacy branch is correctly gated.** Prefix matching now
  applies *only* when the runtime column is empty
  (`COALESCE(runtime,'')=''`), so an explicit runtime always wins. The old
  version let a `gpt-` prefix override a stored runtime. Live `turn_usage`
  contains exactly such a row — `runtime=codex, model=claude-sonnet-5[1m]` (1
  row) — which now buckets by its explicit runtime rather than its misleading
  model name.
- **`ELSE 'claude'` is gone from all three copies** (`manager.py:804`,
  `manager.py:1156`, `mcp_stdio.py:267`, `routes/system.py:1058`) and replaced
  by a single `runtime_for_record` helper. This is the exact class of bug
  (`ELSE 'claude'` swallowing a new runtime's spend) that #95 T6 found in three
  places; consolidating it into one function is the right fix, not a patch of
  the first copy.
- **`manager.py:1002`** — `stored_bt = db_row.get("backend_type") or expected_bt`
  removes the `"claude"` default from the mismatch check, so a missing
  `backend_type` no longer produces a spurious "backend mismatch" warning.
- **The DeepSeek migration actually works**, tested against the verbatim remote
  proxy payload recorded in the inventory:
  ```
  deepseek/deepseek-v4-flash  rt=opencode prov=deepseek ctx=1048576 in=0.098 out=0.196
  deepseek/deepseek-v4-pro    rt=opencode prov=deepseek ctx=1048576 in=0.435 out=0.87
  validate_model_registry OK
  ```
- **`resolve_model` no longer silently returns the first model in the dict.**
  The old fallback meant a typo'd model in `spawn_worker` produced a *working
  agent on the wrong model*. Raising is a real improvement to a shared-runtime
  path, and `routes/sessions.py:74` already surfaces it as a validation error.
- **`opencode-inventory.md` is honest evidence, not advocacy.** It separates
  "CONFIRMED for the inspected set" from "not proved globally", records the
  remote deployment's `harness` runtime as a *counter-example* to its own
  convenience, keeps the adapter rather than deleting on a one-time zero, and
  states the four observations that would justify deletion later. This is the
  standard the project's grails ask for.

## Note for the orchestrator

The remote deployment `SeedonRuInfra / orchestra-test` runs runtime `harness`,
which is **not** in `PROVIDER_METADATA`. That deployment is the enterprise
harness generation with its own `_infer_backend`, so this diff does not run
there — but if `harness` rows ever reach *this* codebase's analytics they bucket
as `unknown` (TTL 0), not as Claude. That is the intended conservative
behaviour, worth knowing before someone reads a `unknown` column on the
dashboard and files it as a bug.
