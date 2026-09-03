# #261 — Opus adversarial review: Phase-2 plan + frozen RED oracles

Reviewer: `review-261-opus` (Claude Opus 5). Date: 2026-08-13. Read-only review; nothing outside
this file was touched.

**Why Opus and not Codex:** the Codex weekly pool stands at 96% ≥ the 95% reserve ceiling, so
`codex_review` was refused before work started. Opus is the declared operational fallback. This is a
single-runtime review — weaker than cross-runtime by construction (`CLAUDE.md`, «одна модель…
петля усиления»), and the plan author is a different runtime than this reviewer, so the loop is at
least not closed on itself.

## Scope reviewed

- `docs/tasks/261/plan.md` @ `e364e352`
- `tests/test_grok_x_tool.py`, `tests/test_grok_x_artifact.py`, `tests/test_grok_x_runner.py`
  @ `40150fce` (frozen)
- production refs: `app/mcp_stdio.py`, `app/backend_grok.py`, `app/routes/system.py`,
  `app/bg_jobs.py`, `app/routes/bg.py`, `app/quota_gate.py`, `app/codex_review_artifact.py`
- supporting evidence: `docs/tasks/261/research.md`, `e1-result.json`, `e2-result.json`

Direct-reading evidence — exact quote from the reviewed plan (`plan.md:78`), not present in the
assignment text:

> marker не удаляется после ошибки. Две параллельные команды могут пересечь ровно один atomic claim.

## RED baseline — verified, not taken on trust

```
$ uv run python -m pytest -q tests/test_grok_x_tool.py tests/test_grok_x_artifact.py \
      tests/test_grok_x_runner.py
17 failed in 9.86s        (exit 1)
```

All 17 failures are behavioural asserts on missing production symbols, **not** collection or import
errors — checked line by line in `/tmp/red-261-opus.log`:

| file | count | failing assert |
|---|---|---|
| `test_grok_x_tool.py` | 1 | `hasattr(system, "grok_x_readiness")` → False |
| `test_grok_x_tool.py` | 6 | `hasattr(m, "grok_x_search")` → False |
| `test_grok_x_tool.py` | 1 | `'grok_x_search' in mcp._tool_manager.list_tools()` → False (the call itself resolves; `list_tools()` is sync and returned the live registry) |
| `test_grok_x_artifact.py` | 4 | `importlib.util.find_spec("app.grok_x_artifact")` → None |
| `test_grok_x_runner.py` | 4 | `importlib.util.find_spec("app.grok_x_runner")` → None |
| `test_grok_x_runner.py` | 1 | `hasattr(backend, "build_grok_env")` → False |

Counts match the plan's frozen baseline exactly (T2 → 4, T3 → 5, T4 → 7 + 1 deselected, T1 → 1).
The `find_spec` guard is the right shape: it fails as an assertion instead of an `ImportError` at
collection, so the whole file stays selectable and the failure message is the ticket's own words.

Independently recomputed the one arithmetic constant in the oracles — the snowflake decode
`(2087564648325530099 >> 22) + 1288834974657` = `1786549171893` ms =
`2026-08-12T15:39:31.893+00:00`, matching `test_grok_x_artifact.py:118` and `e2-result.json`.
The oracle is not asserting an invented timestamp.

---

## Findings (10)

### 1. **blocking (architecture): a second, incompatible owner of quota admission**

`app/quota_gate.py` is already the single owner of "may this spend happen": `READINESS_POLICY =
"worker-weekly-v1"`, `READINESS_WIRE_VERSION = 2`, states `available | blocked | unknown |
not_applicable`, freshness carried in `observed_at`/`valid_until`, served at
`GET /api/usage/readiness` (`app/routes/system.py:1209`) and consumed by
`mcp_stdio._quota_refusal_from_readiness` (`app/mcp_stdio.py:607-700`), which is what `codex_review`
already calls before creating its bg job (`app/mcp_stdio.py:2115`).

Crucially, that owner *already knows about this exact gap*:

```python
# app/quota_gate.py:288-292
if runtime == "grok" and bucket is None:
    return QuotaDecision(
        state="not_applicable", model=resolved, provider="grok", ...
        reason="Grok is outside the subscription weekly quota policy",
    )
```

The plan instead adds `GET /api/usage/grok-x-readiness` with a *divergent* envelope:
`policy=grok-x-subscription-v1`, no `wire_version`, no `observed_at`/`valid_until`, and the state
token `exhausted` where the existing vocabulary says `blocked`. Fed to the existing parser, that
envelope fails three separate gates: wrong `policy`, then `wire_version is None` **with**
`decision_state` present → `"decision_state requires readiness wire version 2"`, then
`exhausted ∉ {available, blocked}`.

This is the project's own «одна мысль = один owner» rule inverted, and the reason it matters here is
not aesthetics: the next person who wants Grok admission at *worker spawn* (the natural follow-up to
`#227`) will extend `quota_gate.py`, and the two gates will disagree about the same subscription.

Worse, the frozen T1 oracle **locks the divergence in** with an exact-dict compare:

```python
# tests/test_grok_x_tool.py:40-46
assert result == {"policy": "grok-x-subscription-v1", "decision_state": "available",
                  "utilization": 13, "reset_at": "...", "reason": "fresh_billing_available"}
```

Adding `wire_version`/`observed_at` later to converge on `worker-weekly-v1` breaks a frozen test,
and per the worker contract a frozen test may not be edited. Decide the owner **now**, before T1 is
implemented: either fill the `not_applicable` hole in `quota_gate.py` and re-freeze T1 against
`worker_readiness_envelope`, or write down in the plan why Grok-X admission is deliberately a second
policy and how the two are kept from drifting.

### 2. **blocking (oracle gap): post-id provenance is claimed but never tested**

The contract's core anti-fabrication rule is that the published post id must have been the input of
a *completed* `x_thread_fetch` (`plan.md:16`, `research.md:105-107`). The T2 fixture only ever
contains one post id (`POST_ID`), and the only negative case flips `fetched` to `False`, removing
the fetch entirely (`test_grok_x_artifact.py:156`).

Therefore an implementation that checks *"at least one completed `x_thread_fetch` exists anywhere in
the trace"* — instead of *"this candidate's decimal id equals the `post_id` argument of a completed
`x_thread_fetch`"* — passes all four T2 tests. That implementation republishes any URL the model
emits as long as it fetched some unrelated post, which is exactly the fabrication the ticket exists
to prevent, and it is invisible in a green run.

Missing case: trace fetches `post_id = A`, model returns `https://x.com/…/status/B`, `_fetch_oembed`
answers 200 canonical for `B` → must raise `no independently verified X posts`.

### 3. **blocking (wiring): nothing binds the three modules into the production path**

Three seams are asserted separately and never connected — the project's recurring
«тест зовёт ПРИМИТИВ напрямую вместо пути, по которому идёт прод» failure (`#219`):

- T4 asserts only the substring `"grok_x_runner.py" in config["command"]`
  (`test_grok_x_tool.py:170`). Nothing executes the command, nothing checks the runner has a
  `__main__`/argparse that accepts the flags the MCP emitted. A command referencing a module with no
  CLI entry point is green in tests and `exit 2` in production — the exact shape of the `#215/#217`
  incident, where `codex_review_artifact.py` gained required args and every live process broke.
- T3 calls `run_grok_x_once(run_dir=…, question_file=…, output=…, cwd=…)` directly. Nothing asserts
  that `_invoke_grok` builds its argv via `build_grok_x_command()` or its env via
  `build_grok_env()`; both are tested only in isolation (`:137`, `:168`). An implementation that
  inlines a second, un-hardened argv/env in `_invoke_grok` passes every test — and inlined env is
  precisely how proxy/telemetry leaks come back.
- T3 monkeypatches `_finalize_grok_x` (`:105`) while T2 tests `finalize_grok_x_artifact`. The two
  names are never tied together by any oracle, so the finalizer can simply not be called.

At minimum, one oracle should drive the T4-emitted command string into the T3 runner entry point
(subprocess or `runpy` on the parsed argv) with `_invoke_grok` stubbed, and one should assert
`_invoke_grok`'s effective argv/env are the ones the two builders produce.

### 4. **blocking (oracle gap): the catalog/auth preflight has no oracle at all**

Every T4 test replaces `_grok_x_catalog_preflight` with a stub that returns success
(`test_grok_x_tool.py:149`, `:193`) or asserts it is never reached (`:234`). The plan's own
requirement — «нужны rc=0, logged-in banner и live `grok-4.5`» (`plan.md:119-120`) — and the task
contract's «fail before job on … invalid auth/catalog» have **zero** enforcement.

Two dangerous implementations pass today: a preflight that checks `rc == 0` and ignores the banner
(so a logged-out CLI that exits 0 is treated as authenticated), and one that accepts the default
model. The latter is not hypothetical: `research.md:62-66` records the live default as **4.6**, and
4.6 measured *worse* on this exact task (2/6 exact links vs 4/6). There is also no test that a
*failing* preflight blocks `POST /api/bg/jobs` — only the quota path has that oracle (`:204`).

### 5. **issue (oracle gap): four of the six integrity rejects are untested, and the X-call boundary is off-by-one-shaped**

`plan.md:62-63` lists six conditions that must reject the whole result before any write:
`>6` completed X calls, any completed non-X tool, non-unique or non-successful terminal `end`,
terminal model ≠ `grok-4.5-build`, `num_turns > 1`, and zero verified posts. Only the first and the
last have oracles. `_trace()` hard-codes `stopReason="end_turn"`, `num_turns=1`, a single `end`, the
`grok-4.5-build` key and zero non-X tools in *every* case, so an implementation that parses none of
them is green.

Separately, the accept side of the cap is untested: only `x_calls=7` (reject) and `x_calls ∈ {1,2}`
are exercised. `>= 6`, `> 5`, or `>= 5` all pass the suite while silently discarding paid, valid
runs — a failure that surfaces as "the tool sometimes returns nothing" and is very hard to attribute.
Add a green case at exactly 6.

### 6. **issue (provenance): `_fetch_grok_usage` is never tested to actually raise `GrokBillingExhausted`**

T1 asserts the class exists and that readiness maps an injected `GrokBillingExhausted` to
`exhausted` (`test_grok_x_tool.py:58-64`). It never drives an HTTP 429 through the real
`_fetch_grok_usage` (`app/routes/system.py:566-582`), which today does `resp.raise_for_status()` and
would surface `httpx.HTTPStatusError` — classified by the plan's own table as `unknown`, not
`exhausted`. So the whole 429 branch can remain dead code and every test is green; the only visible
symptom is that a genuinely exhausted subscription is reported as `unknown`. Both are fail-closed,
so nothing breaks loudly — which is why it will never be noticed.

Note also that `_fetch_grok_usage` is shared with the dashboard path (`system.py:867`, `:1073`);
`:867` catches `PermissionError` then bare `Exception`, so a new exception type degrades to a warning
there. That is survivable but should be stated in the plan rather than discovered.

### 7. **issue (oracle strength): the concurrency test does not prove atomicity**

`test_t3_concurrent_commands_cross_one_atomic_claim_only` starts thread A, waits on
`entered.wait(2)` until A is already *inside* `_invoke_grok`, and only then calls the second
`run_grok_x_once` from the main thread (`test_grok_x_runner.py:119-128`). The two claims are
strictly sequenced, so a non-atomic `if marker.exists(): raise` followed by `marker.touch()` passes
— the TOCTOU window is never entered. The plan's `O_CREAT|O_EXCL|O_NOFOLLOW` (`plan.md:73`) and the
AC "concurrent commands spawn exactly once" therefore have no oracle.

This is a smaller risk than it looks (the real concurrency is process-level, and `restore_from_db()`
→ `_start_task` re-execution is sequential — confirmed in `app/bg_jobs.py`), so I would not block on
it. But the test name overstates what it proves, and a reader will trust the name. Either rename it
to what it verifies (sequential re-entry is refused) or assert the syscall flags directly.

### 8. **issue (cross-scope): "ignored persisted directory" is a property of *this* repo only**

`plan.md:71` places run state at `<worktree>/data/grok-x-runs/<run-id>/` and calls the directory
ignored. That is true here — `.gitignore:12` is `data/` — and the frozen T4 oracle bakes the path in
(`test_grok_x_tool.py:173`). But `grok_x_search` is a plain MCP tool: it ships to every agent in
every scope Orchestra runs (kesha-tg-bot, polus, seedon, VPN-Service), and `worktree_path` comes
straight from the session record. In a scope where `data/` is tracked or simply not ignored, every
call leaves `question.txt`, `run.jsonl` and `run.stderr` as untracked files in the worker's tree —
and a worker's contract is `git status` must be clean before DONE.

The artifact has the mirror-image problem: `docs/tasks/<id>/grok-x-<run-id>.md` is an
Orchestra convention, and for an **orchestrator** the "worktree" is the main checkout, so a
successful call dirties tracked `docs/` in `main`. That is the `#114` pattern verbatim — a store
that writes itself sharing a working tree with the git lifecycle.

Prior art disagrees with the plan here and is worth following: `codex_review` keeps all volatile
state in `/tmp` (`app/mcp_stdio.py:2128-2131`) and writes only the caller-named artifact into the
tree. Recommend `/tmp/grok_x_<worker>_<run-id>/` for run state; keep only the artifact in `docs/`,
and say explicitly what happens in scopes without a `docs/tasks/` convention.

### 9. **issue (accounting): usage attribution is proved to be *called*, never to be *correct***

T2 monkeypatches `_record_usage` to raise and asserts the warning reaches the artifact
(`test_grok_x_artifact.py:97-100`, `:123`). That proves the call happens and that failure is
non-fatal — good, and it directly encodes the `#226` lesson. It proves nothing about the arguments.
`runtime`, `model`, tick→USD conversion and the quota sample are all unasserted, so
`turn_usage_add(runtime="claude", …)` is green — and «хвост `ELSE 'claude'` всегда баг» is a
standing entry in this project's grabli list, i.e. a mistake already made here.

The tick constant is at least internally consistent: the fixture's `total_cost_usd_ticks =
2_500_000_000` against `total_cost_usd = 0.25` matches `GROK_COST_TICK_USD = 1e-10` in
`app/backend_grok.py:81-83`. Note the fixture uses the key `total_cost_usd_ticks` while the live ACP
path reads `costUsdTicks` (`app/backend_grok.py:904`) — different transports, so probably fine, but
the streaming-JSON key name should be traceable to a captured run rather than to the fixture.

Idempotency of `turn_usage_add` (`plan.md:100`) is likewise unasserted: replay after a crash is the
whole point of T3, and a second `finalize` call must not double-count.

### 10. **issue (injection surface): the oEmbed fragment is untrusted text written into an agent-read artifact**

The design correctly refuses model synthesis and takes the body from oEmbed — but oEmbed's `<p>` is
*the post author's* text, and the artifact is written for an agent to read and act on. `plan.md:98`
specifies "HTML-unescape + whitespace normalization" and nothing else; T2 confirms `&amp;` → `&`
(`test_grok_x_artifact.py:119`). So arbitrary attacker-authored Markdown — headings, fenced blocks,
`<!-- … -->` comments, or literal instruction text — lands unfenced in a file the calling agent
reads as ground truth. The plan's threat model covers *fabrication by the model* and stops there.

Cheap mitigation, and it belongs in the frozen T2 oracle before implementation: emit the fragment as
a fenced or `>`-quoted block with the fence length chosen to survive the content, and assert on a
fixture whose post body contains `\n<!-- grok-x-validated:v1 -->\n` and a `#` heading that neither
escapes the block. Worth noting the same string is the bg-level `success_pattern`
(`(?m)^<!-- grok-x-validated:v1 -->$`, `test_grok_x_tool.py:169`) — MULTILINE, matching anywhere in
the file, not anchored to line 1 the way T2 and the runner's reuse check are.

---

## What the plan and the oracles get right

Recording this so the findings above are not read as a verdict on the whole artifact:

- **Admission ordering is correct and tested.** `test_t4_non_available_quota_refuses_before_bg_job`
  asserts no `POST /api/bg/jobs` for both `unknown` and `exhausted` (`:204`), and
  `test_t4_invalid_question_or_task_refuses_before_any_bg_job` asserts local validation precedes the
  provider preflight by making the preflight itself raise (`:234`). No job before admission holds.
- **Cache-cannot-authorize is genuinely tested, not decorative.** The last block of T1 populates
  `_grok_usage_cache` with a *fresh-by-TTL* successful reading (`ts = 2_000_000_000.0`) and then
  removes the credential; a cache-first or cache-if-fresh implementation returns `available` and the
  test fails. This is the correct shape for a fail-closed oracle.
- **Question leakage is closed on both ends** — `question not in config["command"]` (`:171`) plus
  `("--prompt-file", str(question))` in argv (`:152`), so nothing reaches shell argv or the SQLite
  job config. Traversal is covered by the `../escape` task-id parametrization (`:210`).
- **Overwrite safety is tested in the direction that matters:** a pre-existing artifact survives
  both the 7-call reject (`:144`) and the unverified-candidate reject (`:170`).
- **Synthesis leak is tested with a real trap**, not a token check: three distinct sentinels, a
  >3000-character prelude, a JSON object deliberately split across two `text.data` chunks at offset
  47 (so the finalizer must reassemble the stream), and a `WRONG_HANDLE_URL` that only canonical
  oEmbed normalization can correct. That last one is the single best assert in the set.
- **Replay economics are sound.** I confirmed `restore_from_db()` → `_start_task()` does re-execute
  `run` jobs (`app/bg_jobs.py`), so the marker is load-bearing, and the 120 s `expires_at` means a
  restart longer than the window expires the job instead of replaying it.
- **Research is evidence-backed, not narrative.** `e2-result.json` is a real run
  (`grok 1.0.3`, rc=0, 9639 ms, one `end`, `num_turns=1`, one `x_thread_fetch`, zero non-X tools),
  and E1's negative controls (`oembed_id_1 → HTTP 404`) are the discriminating half that most
  fixtures omit.

## Ticket boundaries

Vertical slicing is sound: T1 (admission) and T2 (finalizer) are independent, T3 depends on T2,
T4 on T1+T3 — matching the real data flow, and each ticket names files, symbols and one exact
command. Two remarks:

- `tests/test_grok_x_tool.py` is listed as `(frozen)` under **both** T1 and T4. The nodeid/`-k`
  split makes it workable, but two tickets now own one immutable file: T1's implementer can turn
  their command green while leaving the file red, and there is no rule stated for who re-runs the
  whole file at the end. Say explicitly that T4 closes on the *whole* file, not `-k 'test_t4_'`.
- T1 promises `tests/route_surface_snapshot.json` in the same implementation commit
  (`plan.md:91`) — correct, and it is the specific mistake that left `main` red after `#187 T1`.
  Keep it.

## Verdict

**NEEDS WORK.**

The design is the strongest part of this ticket: the independent-retriever framing, fail-closed
admission before the job, the atomic marker against double spend, and the split-chunk synthesis trap
are all correct and hard-won. Three things must be settled before implementation starts, because two
of them are frozen into immutable tests and become expensive afterwards:

1. **Finding 1** — decide the owner of Grok admission (`quota_gate.py` vs a parallel policy) *before*
   T1 is implemented; the exact-dict assert in the frozen oracle makes converging later impossible
   without breaking a test that may not be edited.
2. **Findings 2 and 4** — the two anti-fabrication guarantees the ticket exists for (post-id
   provenance, authenticated catalog with a pinned 4.5) currently have implementations that pass the
   suite while doing nothing. These need oracles added to the frozen set now.
3. **Finding 3** — add one oracle that crosses the MCP → runner → finalizer seam, or the first
   production call will be the first integration test.

Findings 5–10 are ordinary review debt and can be handled inside the tickets, except finding 10,
whose fixture belongs in the frozen T2 set for the same reason as 2 and 4.
