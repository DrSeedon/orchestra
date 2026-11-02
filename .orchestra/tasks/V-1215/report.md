# V-1215 — integrate V-1213 hub report ordering

Integrated source HEAD `f416821f4f6dab261cacb6f9a27a2bf5e53a00e2` over current `main` base `5690fe48a4f16abe12a21cf5e0f5ef8117a6dc72` in branch `task-V-1215/integrate-hub-notify`. Neither `main` nor the source ref was changed by this task. During the work, `main` and `origin/main` advanced to `beb08fd2be61cda707775ea28899a682d35a9fae`, a separate V-1212 commit that changes only `TODO.md`; this branch remains based on the explicitly supplied `5690fe48`.

The four reported conflicts were resolved by retaining V-1206's transport and import implementation from current main, while bringing in V-1213's durable return transaction and report delivery. `HubSsh.run()` still allows `max_out=None` only for file-backed output, drains stderr in bounded chunks, and never buffers an unbounded archive with `communicate()`. `apply_changes()` still streams tar headers and payloads and verifies hashes before replacement. Existing finite snapshot caps, upload/import/privacy guards and failure cleanup remain. `WorkspaceState.pending_sync` and release cleanup cover the retained archive and interrupted `.sync.tmp` copy. Outbox messages persist broker-owned delivery IDs and recover before a new upload or provider run.

The V-1213 large-return regression remains and now asserts snapshot cleanup after completion. Its same-filesystem test verifies inode preservation at import; a too-broad test monkeypatch initially blocked the deliberately streamed payload copy and was removed. Partial imports and outbox rejection now produce a failed turn result. No production contract outside the internal hub state and outbox delivery path changed.

## Checks

- `uv run --frozen python -m pytest tests/test_backend_hub.py tests/test_hub_workspace.py tests/test_hub_download_v1064.py tests/test_hub_return_v1206.py tests/test_hub_report_order_v1213.py tests/test_hub_snapshot_v1213.py tests/test_v1028_hub_outbox_report.py -m 'not live_probe' -q --tb=short` — **282 passed in 32.53s**. The first run was **281 passed, 1 failed** because the new test intercepted the valid payload stream; the test was narrowed and the full mapped command passed on rerun.
- `uv run --frozen python scripts/check_instruction_contract.py` — OK.
- `uv run --frozen python scripts/secret_scan.py --staged` — OK.
- `git diff --cached --check` — OK.
- Imported modules resolve to this worktree: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/integrate-hub-notify/app/__init__.py`, `app/backend_hub.py`, and `app/hub_workspace.py`.

Raw mapped-suite output is local-only under `/home/kesha/orchestra/.orchestra/private/V-1215/` (`mapped-suite.log` is the failed first run; `mapped-suite-rerun.log` is the passing run). Tests used synthetic workspaces and a `/dev/shm` scratch directory. No live Hub/provider, production database, retained remote workspace, sync retry, service or restart was used. The full repository suite was not run.

## Reading order

1. `app/backend_hub.py` — journal phases, commit recovery and report delivery ordering.
2. `app/hub_workspace.py` — V-1206 streaming/import guards and persisted workspace state.
3. `app/hub_outbox.py` — broker-owned delivery identity and existing delivery receipt handling.
4. `tests/test_hub_report_order_v1213.py`, `tests/test_hub_snapshot_v1213.py`, then the mapped V-1206/workspace/outbox tests — lifecycle recovery, retention, caps and guards.
