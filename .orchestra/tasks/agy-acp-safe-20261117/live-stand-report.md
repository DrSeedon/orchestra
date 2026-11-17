# Step1 resumed — STOPPED on first model/effort preflight refusal

VERDICT: authorized PhaseB preparation and10s idle precheck completed; PhaseC stopped
before its first model prompt, exactly once, with no retry/model/account fallback.
The installed native ACPv1 initialized and authenticated successfully. The adapter
then refused the requested model/effort combination from session/new metadata:

> Antigravity ACP failure: Requested effort variant is not advertised; no nearest fallback

This is a local exact-catalog guard refusal, not an observed account ban or auth failure.
The end-to-end worker cycle is NOT passed. Native tool execution, warm Turn2 and45s
post-turn silence remain unverified. No further live call was made after the refusal.

Base: b85ca2c9f0e122727e0e4fb8615a1c0b6d623ac1; branch agy-acp-safe.
Imported app: /home/kesha/orchestra-worktrees/agy-acp-safe/app/__init__.py.
Previous non-owned-orphan blocker/evidence is retained in live-stand/ and parent commit.
CEO confirmed its ownership and terminated it; this task did not kill a foreign process.
The new attempt independently confirmed baseline0 and an unoccupied18889 first.

## Measured live timeline (UTC)

-08:12:47.503907: driver started; separate private stand directory/profile prepared.
-08:12:47.871525: NL proxy and nft preflight passed.
-08:12:48.716767: separate FastAPI18889 serving, production lifespan/background loops off.
-08:12:58.904534:10s idle passed, vendor processes0, ACP RPC0.
-08:12:59.515544: observed sole vendor PID2089094.
-08:12:59.859729: initialize returned protocolVersion1.
-08:13:02.727785: stand gracefully stopped; vendor PID list empty.
-08:13:02.729610: fail-stop recorded the first model/effort refusal.
-08:13:02.867803: final cleanup/evidence complete; no repeat.

## Live metrics

| Metric | Actual result |
|---|---|
| Vendor spawn / PID_ACP |1 /2089094; stopped during cleanup |
| initialize |1 successful; protocolVersion1 |
| authenticate |1 successful, method oauth-personal |
| Offered oauth-personal type |absent (null in redacted telemetry) |
| session/new |1 successful |
| set_model / set_config_option |0 /0 |
| session/prompt / application retries |0 /0 |
| Child creation attempts / Luna spawns |0 /0 |
| Completed CEO/worker turns |0 /0 |
| Turn1/Turn2 token/cache/duration |not available; no prompt submitted |
| Same-PID warm reuse |not tested |
| Worker files/unittest/worktree |not created |
|45s post-turn silence |not run: no turn completed |
| Proxy |178.93.29.64, NL/Amsterdam, AS215294 Lumina broadband UAB |
| nft skgid977 before |0 packets,0 bytes |
| nft skgid977 after |0 packets,0 bytes |
| nft interval delta |0 packets,0 bytes (attempt interval, not fabricated45s audit) |
| All remaining vendor / owned MCP/server PIDs |0 /0 |
| Port18889 / temporary directory |closed / removed |

Installed initialize capabilities include session resume/load and an advertised native
systemPrompt.append extension; the candidate did not newly enable that extension.
Other offered auth IDs were not selected. RPC counts reflect the app-owned ACP boundary;
they do not claim to count every internal vendor HTTP operation.

## Profile, isolation and cleanup

Created /tmp/orchestra-live-stand-20261117 mode0700, private data/demo repo/profile,
separate SQLite and task store. Stand disabled file [claude,grok]; ORCHESTRA_URL18889.
Copied the7 required source files into the private profile, duplicated CLI state to the
ACP directory, with private0600 files/0700 directories. useG1Credits=false and
userSettings.useAiCredits=false were enforced by the adapter before native startup;
telemetry disabled. Original source file hashes remained unchanged.

The isolated antigravity-oauth-token changed during authentication. Only its change
flag was retained. Per requested cleanup the temporary copy was deleted; no source
refresh-state overwrite/copyback and no token/hash/value in the report or telemetry.
No credential copy remains in the candidate tree or evidence.

Main remains4e4e58dcba8eca8f4e961a2095be7efda1322d0e with its same3 tracked dirty files;
production disabled bytes unchanged [antigravity,claude,grok]. Production8888, services,
T3/provider settings, proxy/billing and source account profile were not modified.
No push/merge/deploy/restart, no API-credit fallback, no Telegram request.
Separate foreground FastAPI/task runtime only; no scheduler/TG/dreaming/usage loop.
Stand cache-only quota policy used the existing read-only Codex observation; no live
quota/models probe was launched. Source application code was unchanged in this wave.
The live driver source changes only preserve resumed evidence separately and accept
nft JSON's numeric977 or resolved agy_oauth group; both have offline regressions.

## Checks and diagnostic limit

After the live stop, offline fake-only preflight/receipt regressions:32 passed,0 failed,
0 skipped,2 existing websockets deprecation warnings,12.82s. No real provider in this run.
Instruction contract, Python AST, source diff and focused credential scan passed.
The earlier PhaseA84P belongs to base b85ca2c9f and is not recounted as this wave's result.
Owned commands were awaited in the active turn. Raw log SHA256/whitespace-only
normalization, exact commands and deadlines are in resumed/commands.json.

The client guard computes an exact model+effort variant and requires it in the parsed
advertised model catalog. The refused session/new model/config options were not retained
by this driver, so the exact catalog mismatch cannot be reconstructed from this record.
Do not infer that the account lacks Hydrogen: a parsing/variant-contract mismatch has
not been excluded. Another native session/model probe was NOT opened to investigate.
A fresh live attempt requires a later explicit decision after the model/effort contract
is reviewed. This report neither queues a retry nor claims production readiness or
immunity from account restrictions.

Evidence: /home/kesha/orchestra-worktrees/agy-acp-safe/.orchestra/tasks/agy-acp-safe-20261117/live-stand/resumed/
telemetry.json, stand-ceo-logs.json, cleanup.json, verification.json, commands.json,
live-run.log, offline-after-live.log, instructions.log. Prior blocked-run files retained.
