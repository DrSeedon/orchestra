# Sol/Astra 6.2 rollout checks
Imported test app: /home/kesha/orchestra-worktrees/sol62-rollout-20261118/app
Source: owner benchmark section 4, /tmp/sol_6_2_effort_benchmark_20261117.md on hub.
No benchmark was rerun; these are configuration/regression tests.

## Verified
- focused-r1.log: 35 new regressions passed.
- contracts-final.log: 418 passed, 9.42s. Files: test_sol62_rollout.py,
  test_default_pipeline.py, test_prompting.py, test_local_delegation_prompts.py,
  test_models.py, test_runtime_registry.py, test_quota_gate.py, test_pipeline.py.
- backend-regressions.log: 3 passed, 149 deselected (existing effort/retarget tests + overflow guard).
- instructions-verified.log: instruction contract OK.
- Kernel network namespace, synthetic HOME/DB, real provider binaries and external DNS/HTTP denied.
  --local-contracts only admits synthetic local Git for an explicit bounded file list.
- Native in-place model+effort persistence and rollback tested, no native thread replacement.
- Safe internal AGENTS->CLAUDE and chained internal links retain byte-budget diagnostics;
  external/prefix-sibling/broken/cycle/directory/escaped-parent links refused before external reads.
- Manual-only, disabled-provider, native-agent/sleep restrictions retained.

## Intermediate failures (not hidden)
- contracts-r1.log: 417 passed / 1 failure: new roles lacked required TG icons.
- contracts-verified.log: 417 passed / 1 failure: implementer reused worker icon.
  Assigned a distinct native role emoji; all 418 then pass.
- instructions.log: KB index checker does not accept fragment URLs; updated the existing file entry.
- egress-predeploy.log: EgressSafetyError correctly rejected AS51167 Contabo 158.220.127.161.
  Both diagnostic domains were absent from Xray resi-nl allowlist. Both probes independently
  returned the datacenter address through 18080; model/API calls were not attempted.
- proxy-route-repair.json: added domain:ipwho.is and domain:ipinfo.io to resi-nl and mirrored
  block rule, xray config -test PASS, restart only at 0 established 2443/8443/10809 clients.
  No outbound credentials/settings changed. Root-private original config retained outside Git.
- egress-verified.log/egress.json: both verify_provider_egress calls PASS,
  178.93.29.64 NL AS215294 Lumina Broadband UAB. No Google/OpenAI prompts yet.

All historical measurement sections are retained. Existing curated alias/role inventory pins
are explicitly migrated to the new owner contract rather than weakening admission assertions.
