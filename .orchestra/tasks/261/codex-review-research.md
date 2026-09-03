## Summary

Phase 1 is directionally sound, and the `codex_review` analogy matches current code. However, two contract-level holes remain: quota failures are not classified safely before inference, and “available to every role” conflicts with existing MCP access modes.

## Findings

1. **blocking:** `docs/tasks/261/research.md:143-152` — the proposed `null → fail-open` policy conflates exhaustion with ordinary telemetry failure. Current `_fetch_grok_usage()` special-cases only 401; billing HTTP 429 falls into the generic exception path, and `_get_usage_data()` turns that into unavailable data. Consequently, an explicit quota response can become `UNKNOWN` and authorize inference—the opposite of “refuse before work when exhausted.” Preserve status provenance: billing 429 must fail closed as quota exhaustion; only specifically classified network/schema failures may enter the debated fail-open path.

2. **blocking:** `docs/tasks/261/research.md:233-235` — one common tool cannot currently be available to every role without changing access semantics. `READ_ONLY_MCP_TOOLS` and `REDUCER_MCP_TOOLS` are explicit allowlists in `app/mcp_stdio.py:53-73`. Adding the tool only to the reducer list still excludes read-only roles; adding it to read-only grants a quota-spending, artifact-writing operation under a mode whose focused test explicitly hides mutating tools. Narrow the requirement to full/reducer roles, or introduce a separately named capability class. Do not silently redefine read-only.

3. **suggestion:** `docs/tasks/261/research.md:103-132` — the identity validator is credible, but the fragment conclusion is stronger than the preregistered evidence. Exact full-text matching was preregistered; the 200-character rule is explicitly labeled “Exploratory diagnostic added after the preregistered exact-match run” in `validate_251_oembed.py`. It was observed on only four unique posts, with no mutated-fragment negative control. Downgrade “CONFIRMED” for prefix verification and prospectively test altered prefixes, valid short posts, Unicode/HTML normalization, and fabricated suffixes. Publish only the matched prefix; never expose the suffix merely with a nearby `UNVERIFIED` label.

4. **suggestion:** `docs/tasks/261/research.md:176-184,209-211` — the execution-budget wording is honest about spend and X-call limits, but restart safety is not supplied by the current runner. `BgJobManager.restore_from_db()` re-executes every active stored `run` command. A durable marker can make no-retry viable, but only with a specified atomic state transition created before spawning Grok and tested at each crash boundary. Otherwise “one active attempt” is an intention, not an enforced property. The 120-second wall and one-turn limits themselves are truthfully characterized.

5. **suggestion:** `docs/tasks/261/research.md:136-141` — `grok models` can demonstrate current subscription authentication and model availability before inference, but the contract should distinguish “credential file exists,” “catalog request authenticated,” and “billing credential accepted.” These paths currently read related subscription credentials through different mechanisms. Require both authenticated catalog success and a classified billing result; avoid presenting the catalog banner alone as complete auth/quota readiness.

6. **suggestion:** `docs/tasks/261/research.md:74-80` — the `codex_review` JSONL/full-text analogy is accurate. Current normal output comes from `codex -o ...round`; `codex_review_artifact.py` reads JSONL for thread identity and usage, not for review-text recovery. Nonzero CLI exit prevents the finalizer from running. Preserve this precise distinction in the plan, because Grok’s proposed “concatenate all text events” is new behavior rather than reuse of Codex recovery semantics.

## Verdict

**NEEDS WORK — 2 blocking findings.** Proceed after separating quota-exhaustion signals from telemetry uncertainty and resolving which access modes may legitimately spend Grok quota and write artifacts.

Proof of direct review, verbatim from the research: “Пустой вопрос и параллельный run с тем же id тоже отклоняются.”

## Round (2026-08-13T09:07:45Z)

## Summary

All prior blockers are closed at the research-design level. The revised contract is internally consistent with current access-mode, quota, and background-runner behavior. No new load-bearing contradiction found.

## Findings

1. **FIXED — quota admission:** Fresh classified billing must return `AVAILABLE`; both `EXHAUSTED` and `UNKNOWN` now fail closed before job creation. HTTP 429 retains exhaustion provenance, and the research correctly identifies the missing Grok lock/timestamp support in current quota observation.

2. **RESOLVED BY CODE FACT — role availability:** `app/manager.py` maps only the reducer role to `reducer`; every other production pipeline role receives `full`. Adding the tool to `REDUCER_MCP_TOOLS` therefore covers every pipeline role while correctly excluding the independent read-only capability mode.

3. **FIXED — fragment verification:** The post-hoc 200-character result is explicitly non-load-bearing. The artifact publishes only independently returned oEmbed text, never the model’s suffix or free synthesis.

4. **FIXED — no-replay contract:** The proposed immutable `O_CREAT|O_EXCL` marker addresses current `BgJobManager.restore_from_db()` command replay. Valid artifact wins; marker without artifact fails as outcome-unknown without inference. Crash-boundary and concurrency tests remain correctly required for Phase 2.

5. **FIXED — auth separation:** Credential presence, authenticated catalog/model availability, and classified billing readiness are now distinct mandatory preflights.

6. **FIXED — Codex analogy:** The research accurately preserves that normal `codex_review` text comes from `.round`, while Grok reconstruction from ordered JSONL text events is new behavior.

Evidence of direct reading:

> Неподтверждённый suffix и свободный синтез модели в пользовательский артефакт не попадают;

## Verdict

**APPROVED.** No blocking findings remain.
