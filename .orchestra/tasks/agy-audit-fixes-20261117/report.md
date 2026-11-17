# VERDICT: deployed; scoped checks pass, native limitations retained

COMMIT (code): 912b2f18afe65986c4158286a16676046489ce5e
Candidate/imported tests: /home/kesha/orchestra-worktrees/agy-acp-safe/app
Production app: /home/kesha/orchestra/app

## Changes
Own proof-bound one-shot bg completions and authenticated live-orchestrator direct messages
are admitted. Cron, cron_command, timer, dreaming, scheduler, retries, system/platform/unknown
remain denied. The canonical Antigravity provider overlay applies to every backend role.
A1–A12/S2 boundary corrections and current aliases/G1 Pro model were implemented.
GPT-6.2 Sol/Astra registered with manual-only admission; sol stays gpt-6.1-sol.

## Actual checks
- 55 new audit regressions passed (new-regressions-verified.log, 13.65s).
- 267 ACP checks passed, 9 explicitly superseded policy cases deselected, 2 deprecation warnings
  (acp-verified.log, 55.35s). The 9 original assertions are retained unchanged, never called green.
- 289 pipeline/prompt/model/runtime/quota/Hub contracts passed (contracts-verified.log, 10.33s).
- Instruction contract, compileall, diff whitespace and credential-pattern scan passed.
- Strict fake-ACP and bounded local-Git harnesses used kernel network namespaces, synthetic
  profiles/DB and negative controls. No real provider/Google/OAuth/TG test traffic.
- 100 create/close cycles tested: 1 mock front, 101 close RPCs including keeper, bounded maps,
  final owned PID exit. Actual archive through SessionManager preserves durable history.

## Deployment measured
Fast-forwarded production main. Installed IPC and systemd files, daemon-reload, restarted
orchestra.service only when no running turn/unfinished compact was detected. Waited for old
vendor/tool children to exit before restarting the two IPC daemons. No broad process kill.
- Orchestra active; PID 2492052, cwd /home/kesha/orchestra.
- Both IPC daemons active; MemoryHigh=6442450944, MemoryMax=8589934592.
- restart_cut_turns before=0, after=0; vendor PIDs after restart=[].
- telegram-bot-api PID 2786980 unchanged.
- Three original dirty production files byte-identical; disabled_providers hash unchanged.
- Hydrogen local Antigravity, model unchanged, idle after restart.
- Canonical ACP token regular 0600, CLI symlink to that source. Opaque previous CLI snapshot
  retained privately; no token content exported. Application/CLI writers share the profile lock.
- Both no-credit booleans false. Local proxy listeners 18080 and 10809 reachable.
- Live provider prompts/canary=0. Native catalogue is passive/cold after restart; not presented
  as a fresh account entitlement or successful Google inference.

## Remaining limits (not a global GREEN)
Vendor os.WriteFile is still not crash-atomic; single-process writer + shared lock removes
concurrent process-per-session writers without patching the vendor. Native session/close is
optional and used only if advertised: unsupported close retains vendor state until profile exit.
Actual vendor token/quota notification support is not established; absent data remains unknown.
Fixed-profile identity boundary remains, no same-HOME account-change detection or ban immunity.
The historical frozen CLI/probe suite was not rerun; the 9 current old profile-latch cases require
an explicit policy migration, not restoring the rejected global failure behavior.

## POINTERS
- acceptance.md: per-finding disposition, contract and limitations.
- checks.md and *verified.log: commands, pass/fail/deselected/warnings and intermediate failures.
- deployment.json, deploy.py/deploy.log: exact deployment argv and unit/PID/resource evidence.
- post-deploy-readiness.json: passive credential/listener checks, no-credit flags.
- static-checks.json and baseline.json: source path, scan, owned fake PID and file-preservation checks.
