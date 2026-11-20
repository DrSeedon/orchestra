> HISTORICAL candidate 120cb528f. Superseded by r2/report.md and corrected source commit.

# Persistent Antigravity ACP — final offline candidate

VERDICT: offline candidate implemented and tested; overall merge/production gate RED.
This report supersedes the original implementation handoff. Source is now owned by
permanent CTO, following the explicit user continuation. Parent owns fresh review.

## Immutable deliverable / scope

- Remote worktree: /home/kesha/orchestra-worktrees/agy-acp-safe; branch agy-acp-safe.
- Base: 4e4e58dcba8eca8f4e961a2095be7efda1322d0e. Branch commit recorded in final reply.
- Exact imported app: /home/kesha/orchestra-worktrees/agy-acp-safe/app.
- No push, merge, deploy, service restart, real agy, Google/account request, token read,
  OAuth-home copy, provider enablement, proxy/billing/T3 configuration modification.
- Production HEAD is unchanged. Its three preexisting dirty tracked files are retained.
  Antigravity/Claude/Grok remain disabled. telegram-bot-api was not restarted.

## Implemented and reviewed behavior

- Lazy app-owned ACP process per canonical profile, lifetime flock, profile concurrency1;
  initialize/authenticate once, new/resumed independent sessions, advertised model/config
  selection, user role context, per-session updates, no auth/model/provider fallback.
- Repeated readiness/usage/quota polls remain passive, including egress verification;
  cached observations retain their age and unknown live information stays unknown.
- User provenance is enforced at session/backend dispatch. Timers retain durable mail
  without waking the consumer. Manual compact requires authenticated operator input,
  authorizes exactly summary + fresh-session acknowledgement and never auto-retries.
- Timeout/death/auth failures latch the profile without prompt replay or spawn loops.
  Immediate cancellation before coroutine entry still settles exactly once. Local absent
  model/unsupported resume refuse only that operation; healthy sibling sessions continue.
- Definite account-disabled/ToS RPC errors activate the existing durable ban circuit-breaker
  before raw details are discarded. Ordinary failures do not persist a ban. Verification
  writes only isolated test state and uses a fixed safe reason, never the raw payload.
- Text/thinking deltas stream live and assembled text is persisted once; complete final
  text is available to AgentSession. Tool input/result content, name/ID and failed status
  are retained; progress is not a premature terminal tool result.
- Permission requests are cancelled. Config-option updates affect the next model choice.
  Context and cumulative USD cost are separate; cancellation/failure advances cost baseline,
  resumed unknown historical cost is not charged again. Billed token totals stay unknown.
- Existing no-credit settings are required, not rewritten. CLI owns credentials. Browser
  login helper is disabled in the runtime environment. Retired legacy login now refuses
  before starting an executable, creating an auth directory or touching credential files.

## Actual final verification

| Check | Result | Evidence |
|---|---|---|
| New ACP/review + always-on + registry + usage contracts | 189 passed, 0 skipped, 2 dependency warnings, 26.01s | acceptance-final.log |
| Instruction contract | PASS | instructions-review.log |
| Syntax (9 changed Python entry points) / git diff --check | PASS | review-notes.md |
| Real loopback HTTP send + usage/readiness + chat SSE | PASS; anonymous POST denied, two operator turns | http-sse-smoke.json |
| Frozen legacy Antigravity set, unchanged | 15 failed, 18 passed, 79 setup errors, 5.69s | legacy-final.log |
| Extra unrelated compact/mailbox bundle | TIMEOUT at 60s; not counted as passed | adjacent-final.log |

Reproduction: scripts/run_antigravity_offline.sh tests/test_antigravity_acp.py
 tests/test_antigravity_acp_review.py tests/test_always_on_agents.py
 tests/test_runtime_registry.py tests/test_usage_contract.py -q --tb=short

The 189 count includes 44 original new ACP tests, 50 review/ported behavior tests and
95 existing adjacent-contract tests. Frozen original files were not edited/skipped.
Pure legacy SQLite/protobuf assertions are reused with synthetic canonical profiles;
manual compact, cancellation/cost, ban, chunking, tool progress, permission/config
metadata and local failures have new behavioral regressions. See semantic-coverage.md.
Historical R1/R2 failures are recorded in review-notes.md and retained local logs.

## Exact process / RPC observations

- Multiple backend instances and four turns: spawn=initialize=authenticate=1,
  session/new=2, session/prompt=4. Concurrent prompts serialize without overlap.
- Twenty passive batches: spawn=initialize=authenticate=prompt=0; verifier awaits=0.
- Actual HTTP/SSE test: before prompt spawn=0; initialize=authenticate=spawn=1,
  session/new=1, session/prompt=2. No custom /stand/prompt bypass remains.
- Immediate cancellation: spawn=prompt=0, exactly one terminal result, no hanging stream.
- Exact latest per-test counters and aggregate checks: verification-summary-final.json.

## Isolation / cleanup and limits of proof

Checks run inside an ephemeral kernel network namespace with only lo and no external
routes, empty credential environment, synthetic HOME and an independent SQLite DB.
The Python runner rejects external sockets/DNS, every subprocess except the exact fake,
protected home/production paths and native sqlite3.connect path/URI/PathLike opens.
Negative controls target nonexistent protected paths and are rejected before file access.
This is not a general filesystem sandbox: the fake is controlled Python code and does
not inherit the parent audit hook. Its external network remains blocked by the namespace;
its HOME is synthetic, it reads no real credentials. Production bootstrap/lifespan is
intentionally replaced: no Telegram, crons, auto-resume or account services run.

Stand on 127.0.0.1:18889 was stopped; no owned runner/fake processes remain. See
cleanup-final.json. No full production lifecycle, real installed CLI compatibility,
internal vendor background network or account eligibility was tested.

## Open gates and interface choice

1. Frozen legacy suite remains RED. Token-copy HOME, active quota/readiness, per-turn
   NDJSON and old login expectations conflict with the authorized replacement. These
   cannot be restored merely to make old tests green. Full suite was not run; an
   additional compact/mailbox bundle timed out and is not waived. Reviewed migration
   and fresh independent acceptance of the immutable commit are still required.
2. ACP v1 mock success does not authorize consumer deployment. Parent research records
   current Google FAQ/terms restrictions on third-party consumer wrappers. No claim of
   ban immunity or supported personal-Pro server relay is made. No live activation.
3. Direct ACP provides stateful sessions/updates/cancellation; a shared account process
   is our design, not a proven global T3 daemon. Official SDK/API approaches have separate
   documented auth/billing and are not an authorized silent OAuth/API-key fallback.
   Sources and detailed comparison: docs/antigravity-runtime.md; ACP session setup:
   https://agentclientprotocol.com/protocol/v1/session-setup and prompt-turn:
   https://agentclientprotocol.com/protocol/v1/prompt-turn .

## Main pointers

app/antigravity_acp.py; app/backend_antigravity.py; app/session.py;
app/routes/sessions.py; app/routes/system.py; app/mailbox.py; app/main.py;
app/antigravity_auth.py; tests/test_antigravity_acp{,_review}.py;
scripts/run_antigravity_offline.{sh,py}; tests/acp_mock/fake_agy_acp.py.
