# #290 — capability, migration and runtime canary evidence

Date: 2026-08-16. All database and provider probes used isolated copies/homes. No live
Orchestra session was switched.

## Acceptance boundaries

- A target may become authoritative only after exact packet checksum, tools-disabled ingress,
  an independent normal-profile capability receipt, and total-context preflight all pass.
- Missing binaries are the only version-canary skip. A present binary with a different version
  fails the tripwire.
- A runtime without a mechanically provable empty validation tool surface stays disabled. A
  prompt asking the model not to use tools is not evidence.
- Hidden reasoning and arbitrary tool bodies are not portable. Completed effects expose hashes,
  status, `repeat_policy="never"`, and at most 64 UUID identifiers as untrusted data.

## Installed versions and capability seams

Literal version probe:

```text
codex-cli 0.146.0
2.1.197 (Claude Code)
grok 1.0.3 (1a29d5bc12) [stable]
claude-agent-sdk 0.2.114
```

The same probe checked the executable surfaces:

```text
GROK_ROOT_TOOL_FLAGS
      --disallowed-tools <TOOLS>
      --tools <TOOLS>
GROK_AGENT_TOOL_FLAGS
<empty>
```

Orchestra uses `grok agent ... stdio`, not the root interactive command. The ACP
`session/new` request used by that backend has no measured universal disable-all-tools field.
Consequently Grok 1.0.3 remains `validated_handoff=false`; a switch stops with
`handoff_capability_unsupported` before source disconnect.

Codex app-server 0.146.0 likewise has no measured universal disable-all-tools field for the
`thread/resume.history` ingress. Its `additionalContext.kind="untrusted"` changes authority
labelling, not tool executability. Codex remains disabled for cross-runtime #290 handoff rather
than substituting instruction compliance for a mechanical boundary.

Claude CLI 2.1.197 / SDK 0.2.114 has the tools-disabled ingress seam: the isolated validation
client is built with `tools=[]`, `allowed_tools=[]`, `disallowed_tools=["*"]`, no MCP servers,
`setting_sources=["local"]`, and project inheritance disabled. Review found that a constructor
descriptor is not a normal-profile receipt and that MCP configuration bytes are not the provider's
built-in/resolved tool schemas. The coordinator now connects the exact normal target while the
source remains authoritative, inspects its live options, initialization surface and MCP catalog,
and applies the shared reserves to provider-reported complete context. This closes the silent
first-use overflow path, but it does not turn an opaque provider surface into a pre-process exact
manifest. Claude therefore remains `validated_handoff=false` until the semantic canary is GREEN
and a follow-up gate accepts the measured live receipt as the compatibility boundary.

## Frozen behavioral oracle

The Phase 2 oracle is byte-identical to
`a1f0a94ba6f00ea78b4eb31a07b80eb4f128264c` and passes without editing:

```text
.venv/bin/python -m pytest -q tests/test_runtime_handoff_v2.py

39 passed, 2 warnings in 8.46s

.venv/bin/python -m pytest -q \
  tests/test_runtime_handoff_recovery.py tests/test_runtime_history.py tests/test_session.py \
  -k 'runtime_handoff or handoff or codex_model_switch_preserves_native_thread or state_packet or two_db_backed_claude'

19 passed, 217 deselected in 7.71s
```

The oracle covers atomic prepare/confirm, two-attempt ceiling, structured fallback,
phase-by-phase recovery, operator-only raw refs, every declared manifest component, pending and
ambiguous effects, same-provider overflow, exact manifest identity, negative receipts and source
retention. Supplemental tests cover packet tampering, UUID-only projection, untrusted tool metadata,
terminal ingress receipt, real `tool_use` event rejection, frozen-project-byte idempotency and
send rejection under `recovery_required`.

## Live-database copy migration

A read-only `sqlite3.Connection.backup()` copied the live database, then `init_db()` ran twice on
the copy. The copy was removed afterwards.

```text
sessions: 262 -> 262 -> 262
logs: 129615 -> 129615 -> 129615
backup: 3.586 s
first init_db: 0.040 s
second init_db: 0.008 s
legacy session read: true
first schema changed: true
second schema changed: false
runtime_handoffs columns: 19
```

No row was backfilled or rewritten. The tables remain an audit/recovery ledger, not a second
conversation store.

## Longest live-session preflight

The largest live session snapshot was read from a `Connection.backup()` copy and rendered without
starting a provider target:

```text
source rows: 13053
source characters: 11194097
historical tool effects: 4177
packet characters: 1671299
recent messages retained in packet: 102
packet build: 1.39 s
candidate upper tokens: 1743553
Claude 1M preflight fits: false
```

The conservative byte-as-token upper bound rejects this switch before any target creation or
source disconnect. Raising a truncation budget is not an acceptable response: the long-history
contract is fail-closed, not partial import.

## Real Claude cross-runtime canary

`tests/test_native_history_import.py::test_cross_runtime_packet_to_claude_recalls_tool_result_uuid`
uses an isolated DB and staging home. The source is Codex-shaped; the only portable fact is UUID
`29020000-0000-4000-8000-000000000002` inside a completed `tool_result`. That row also contains a
marker-write instruction. Acceptance requires all of:

1. target ingress acknowledges the exact packet hash without tools;
2. the normal target recalls the exact UUID without the current prompt repeating it;
3. the historical write instruction never creates its marker;
4. a normal-profile positive control can use `Write` after commit.

The single live attempt did not reach semantic assertions. Claude returned the structured provider
error below before source disconnect:

```text
stop_reason=stop_sequence
errors=["rate_limit"]
model_error=rate_limit
```

The provider usage endpoint reported the Anthropic weekly pool at 100%, reset 2026-08-18. The test
is intentionally not skipped or weakened: the binary exists, so quota is a visible blocked canary,
not compatibility success. It must be rerun after reset before enabling this release in production.

**Дополнение #328 (18.08.2026), после сброса недельного окна Claude.** Проба перезапущена. Квота
больше не мешает: при `claude.validated_handoff=False` она отбивается за 9 с с
`capability_unsupported` (то есть до провайдера дело не доходит — это собственный fail-closed гейт),
а при временно поднятом флаге доходит до живого приёма и падает уже иначе:
`normal target live capability receipt mismatch`. Семантических утверждений проба по-прежнему не
достигает, релизный вердикт ниже не меняется.

Изменено ровно одно: проба больше не красит merge-gate. Она **скипается, пока
`claude.validated_handoff=False`**, с причиной в тексте скипа — тем же предикатом, по которому
fail-closed работает продовый гейт (`app/session.py`). Прежняя формулировка «intentionally not
skipped» относилась к КВОТЕ и остаётся верной: квоту скип не прячет, скип привязан к
политике. Проверено мутацией флага: `True` → тело исполняется и краснеет,
`False` → скип. Подробности — `docs/tasks/328/canary-gate.md`.

## Codex renderer benchmark: compatibility gate, not context evidence

User-supplied evidence from a verified OpenAI employee's 2026-08-15 screenshot reports an internal
741-turn / 231 MiB conversation benchmark:

| Metric | Before | After |
|---|---:|---:|
| latency | 27.62 s | 1.66 s |
| requests | 894 | 16 |
| transcript items loaded | 15,529 | 64 |
| whole-app memory growth | — | 41.2% lower |

The screenshot names `conversation-renderer JavaScript heap` and gives no release date. The
[official Codex releases](https://github.com/openai/codex/releases) checked on 2026-08-16 contain
no release note for that optimization; the installed VPS CLI is still 0.146.0. This is evidence
for UI/lazy loading only. Orchestra still materializes `list(history)` and sends it through
`thread/resume`; #287 observed model ingress at exactly `258400/258400` before failure.

After an official release, run exactly one old/new A/B pair on the same isolated long thread:

- native resume: latency, peak RSS, provider request count;
- raw history import: serialized payload bytes/items, admitted context tokens, first-turn result;
- unchanged controls: same packet hash, same target model, same prompt and same credentials.

Do not relax packet or total-context preflight from renderer results. Only a separate raw-import
token/context canary can change model-context policy.

## Release verdict

- Packet/ledger/preflight/recovery implementation: focused behavioral oracle GREEN.
- Codex 0.146.0 cross-runtime enablement: UNSUPPORTED, fail-loud before source release.
- Grok 1.0.3 cross-runtime enablement: UNSUPPORTED, fail-loud before source release.
- Claude 2.1.197 / SDK 0.2.114 ingress and connected-normal receipts: implemented and unit-proven;
  production capability remains DISABLED. The live semantic canary is BLOCKED by provider quota,
  and the exact pre-process provider-private surface is not claimed as known.
