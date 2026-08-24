# #313 suite metrics

## Frozen baseline

- `main` and `HEAD`: `1d9be7ae8511a1c5657362cc56eef395b4585bf2` (`#309: audit feature usage and deletion candidates`, 2026-08-24T13:23:07+07:00).
- Test inventory source: `docs/tasks/313/inventory.json`; AST/static analysis: `docs/tasks/313/evidence/static-signals.json`.
- 153 `tests/*.py` files; 78,491 physical LOC; 65,583 nonblank LOC; 2,886 source test definitions; 162 locally defined pytest fixtures.
- Patched collection command (only to provide the host-missing `os.pidfd_open` symbol): 3,284 nodes collected including 3 live-probe nodes; default merge-gate selection is 3,281 nodes and deselects 3 live-probe nodes. No live-probe body was run.
- Unpatched collection was not silently accepted: it collected `3151/3154` and stopped with eight named import errors, all `AttributeError: module 'os' has no attribute 'pidfd_open'`: `test_antigravity_usage.py`, `test_codex_usage.py`, `test_owner_mode.py`, `test_process_guard.py`, `test_quota_map_api.py`, `test_usage_history_resolution.py`, `test_usage_readiness.py`, `test_usage_snapshot.py`. Raw output: `evidence/collect-default.txt`.
- All direct `from app... import ...` rows resolved to a current module, definition, re-export, or package submodule after static re-export handling: 1,955 rows; missing modules 0; unresolved symbols 0 (`evidence/import-status.json`). This is an import-status check, not proof that every dynamic attribute/call path is live.

## Cost and shape

Largest files by physical LOC are `test_session.py` 5,712 / 203 source tests; `test_tg_bridge.py` 5,029 / 185; `test_frontend.py` 3,888 / 62; `test_manager.py` 3,408 / 158; `test_api.py` 3,324 / 120; `test_backend_codex.py` 2,464 / 82; and `test_mcp_stdio.py` 2,424 / 85. Full per-file and per-node records are in `inventory.json`.

Static signals are candidate generators, not verdicts:

- 29 `all(...)` and 65 `any(...)` aggregate sites;
- 415 mock-double call sites;
- 2,078 representation/cardinality comparisons;
- 207 wall-clock wait/sleep sites;
- 155 source/argv/DOM-shape signals;
- 108 browser/client signals and 135 subprocess signals;
- 6 `inspect.getsource` signals;
- exact normalized AST body duplicate clusters: 0;
- near-duplicate lower bound: 1 pair, `tests/test_pipeline.py:280` and `:292`, token-set Jaccard `0.9211`. The two tests validate separate `defaults.skills` and `roles[*].skills` fields; this is not deletion evidence.

The inventory counts test source definitions separately from collected parametrized nodes. It does not infer redundancy from LOC, rarity, aggregate syntax, or AST similarity.

## Safe targeted runtimes

Commands were run with `NOTIFY_SOCKET` removed and a local collection-only compatibility shim for the host's missing `os.pidfd_open`; no provider probe was invoked. Results are preserved verbatim:

| command group | result | artifact |
|---|---:|---|
| routes surface | 2 passed in 2.44s | `evidence/target-routes.txt` |
| acceptance + merge gate | 77 passed in 6.02s | `evidence/target-core-gates.txt` |
| backend Codex + Claude + session hibernate | 152 passed in 5.08s | `evidence/target-backend-recovery.txt` |
| prompting + task/payment/YouGile | 71 passed, 7 skipped in 2.90s | `evidence/target-prompt-task.txt` |
| quota admission + proxy | 95 passed, 4 failed in 3.37s | `evidence/target-quota-proxy.txt` |
| manager + merge recovery | 184 passed, 2 failed in 10.24s | `evidence/target-manager-acceptance.txt` |
| runtime handoff v2 | 64 passed, 10 failed in 5.86s | `evidence/target-session-recovery.txt` |

The quota failures are named parameterized E2E admission nodes. They reached a live blocked quota decision despite their intended monkeypatch, so they are a deterministic-seam defect rather than evidence that the quota rule is wrong. The merge failures are `TypeError: live_merge.<locals>.fake_execute() got an unexpected keyword argument 'expected_target_head'`; production `execute_merge_session` currently accepts that keyword. The runtime-handoff failures fail during current model-registry setup (`unknown model 'gpt-5.6-sol'`) and are safety/recovery tests, not deletion candidates.

The frontend polling test was not accepted as a runtime measurement: its fixture attempts a child dashboard process and the child exits before app startup at the same host-missing `os.pidfd_open` import. Its raw failure is retained in `evidence/target-polling.txt`; no successful service was started and no conclusion was drawn from that run. No further service-starting test was run.

## Mutation and selection evidence

The route pair was tested with runtime-only mutants under `evidence/` (production and tests were not edited):

- removing one route from the seam made `test_route_surface_snapshot` fail with the exact removed path while `test_route_surface_is_discoverable` was deselected (`evidence/mutant-route-snapshot.txt`, pytest exit 1);
- a compound mutant returning one route while supplying a matching one-route snapshot made `test_route_surface_snapshot` pass but `test_route_surface_is_discoverable` fail on `_MIN_PLAUSIBLE_ROUTES` (`evidence/compound-snapshot.txt`, `evidence/compound-discoverability.txt`).

Therefore the apparent snapshot overlap does not prove either test removable. No other candidate met the required current-symbol plus recoverable mutation/selection bar. Proven removable nodes/LOC: **zero**. Proven MERGE candidates: **zero**. Estimated removable nodes/LOC: **zero**.

## Live and high-risk exclusions

The only collected live-probe nodes are the two parameterized instances of `test_pinned_runtime_semantically_recalls_long_native_history` and `test_cross_runtime_packet_to_claude_recalls_tool_result_uuid` in `tests/test_native_history_import.py`. They require real CLI credentials/provider state and remain outside automatic conclusions. The verbose backend/session/Codex oversized-history and handoff tests, manager/merge acceptance tests, quota/proxy tests, prompt-text tests, browser tests, and task/payment/YouGile tests were audited as separate contract surfaces. Safety/recovery tests were not marked redundant because they are long or rare.

## Raw evidence and sanitation

`evidence/collect-*.txt`, `inventory.py`, `static_analysis.py`, `import_status.py`, `run_route_mutant.py`, `run_route_compound_mutant.py`, `mutate_routes_flat.py`, `static-signals.json`, `import-status.json`, and targeted-test outputs are the raw/reproducible records. `evidence/secret-scan.txt` ends with `RG_EXIT=1` (no secret-form matches); fixture-like secret strings copied by AST evidence were redacted in the generated artifact and are not credentials.

## Evidence normalization follow-up

The generators now store production imports once per file and expose `file_imports_ref` on each node instead of repeating the file-level import list. The same reference normalization is applied to static-signal nodes. Counts and candidate verdicts are unchanged; `evidence/verify_artifacts.py` is deterministic and reports `VERIFY PASS`.

| artifact | before bytes | after bytes | reduction |
|---|---:|---:|---:|
| `inventory.json` | 21,065,404 | 2,268,538 | 18,796,866 (89.2%) |
| `evidence/static-signals.json` | 5,976,341 | 4,125,300 | 1,851,041 (31.0%) |

Raw follow-up output: `evidence/normalization.txt`.
