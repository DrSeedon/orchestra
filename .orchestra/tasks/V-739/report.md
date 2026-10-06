# V-739 — curated selectable model registry

## Result

`SELECTABLE_MODEL_SPECS` now contains 16 entries: the 14 models named in the keep list, plus owner-selectable GPT-6 Astra and GPT-6.1 Sol. Astra and Sol have dashboard visibility but are hard-blocked for agent use, including `spawn_worker`, MCP `change_worker_model`, `dynamic_workflow`, and `codex_review`. `sol`, `gpt6sol`, and `codex` resolve to `gpt-6.1-sol`; `grok` resolves to `grok-4.6`; retired IDs are not selectable or alias destinations, and neither provider refresh nor dynamic registration can restore them.

The CLI 0.160.0 `model/list` evidence contains eight models. It identifies GPT-6.1 Sol as `gpt-6.1-sol` (visible and default) and Astra as `gpt-6-astra` (visible, not default); no newer Astra ID appears in that complete response. The raw response is [model-list-default.json](../V-726/evidence/model-list-default.json). V-726 also recorded a successful `codex exec -m gpt-6.1-sol` inference under this account.

GPT-6.1 Sol's official Standard API rates are $2.00 per million input tokens, $0.10 cached input, $2.50 cache writes, and $10.00 output. The Codex backend's API-equivalent estimator uses those rates. OpenAI's separate Enterprise Codex rate card lists the same input/cached/output rates and says Codex does not charge for cache writes; this distinction is preserved here rather than treating API cache-write pricing as subscription billing. Sources: [GPT-6.1 Sol model page](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [ChatGPT Enterprise token rate card](https://help.openai.com/en/articles/20001415-chatgpt-rate-card-enterprise-token-based-pricing).

Retired exact IDs live in `COMPAT_MODEL_SPECS`, outside `MODELS`, and keep applicable historic prices. `_load_from_db` now resolves those exact compatibility entries when restoring persisted sessions; model creation and alias resolution still reject them. This prevents the old rows from becoming selectable again while allowing their sessions and analytics to load. The default `reducer` pipeline role and the quota gate's Luna key now use `gpt-6-luna`.

## Manual session migration and restart order

No database session was changed by this task. Before restarting, the owner should recheck the live rows, then use `change_worker_model` to move each idle session below to `gpt-6-luna`; the operation refuses while a worker is running, so retry only after it becomes idle. Confirm all rows show `gpt-6-luna` before the owner-initiated restart. If a row cannot be migrated first, its exact retired model remains loadable through the compatibility registry; after the restart, load it and change it once idle. The code update does not restart Orchestra.

The corrected active-session list from the orchestrator contains seven GPT-5.6 Luna sessions:

| Session | Scope |
|---|---|
| `prompt-engineer` | `/home/kesha/orchestra` |
| `fix-onboarding-clients` | `/home/kesha/projects/VPN-Service` |
| `feat-ingress-watchdog` | `/home/kesha/projects/VPN-Service` |
| `balatro-vps` | `/opt/cog-second-brain` |
| `autobattler` | `/opt/cog-second-brain` |
| `elevator` | `/opt/cog-second-brain` |
| `balatro-perf` | `/opt/cog-second-brain` |

The three GPT-5.6 Sol sessions are `fix-limits-card-fallback` (`kesha-tg-bot`), `fix-tspu-ingress` (`VPN-Service`), and `ai-table-worker` (`dnd-game-master`). The orchestrator confirmed the Luna total is seven, not eight, and will recheck the current database rows before restart.

## Verification

- Focused registry, routing, pricing, manual-only gates, dynamic-workflow refusal, review-model, session-restore, quota paths, and cache-analytics run: **971 passed, 1 skipped** across 21 affected modules.
- The original `rg -l` inventory found 79 paths under `tests/`; 76 are `test_*.py` modules, and three remaining helper/fixture files are loaded by those tests. The exact search inventory is [removed-model-test-paths.txt](removed-model-test-paths.txt); the 76-module run list is [removed-model-pytest-paths.txt](removed-model-pytest-paths.txt). The first full run found 98 failures where active-path fixtures still requested retired IDs; its raw log is [removed-model-pytest.log](removed-model-pytest.log). Those fixtures now use current IDs, while historical-record fixtures retain retired IDs. The final 76-module run passed: **2073 passed, 22 skipped, 3 deselected**; raw output is [removed-model-pytest-final.log](removed-model-pytest-final.log).
- Imported `app` path: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-codex/app/__init__.py`.
- Initial background wrapper exited before starting pytest because `/bin/sh` rejects `set -o pipefail`; the corrected run uses `bash -c` and targets this worker.
- Source diff passes whitespace checks. `git diff --check` flags only trailing spaces in the verbatim failed-run pytest log, retained as raw output.

## Restart checklist

The migration order is: update the seven Luna and three Sol rows after each worker is idle; verify the rows and the `reducer` pipeline value; then the owner restarts Orchestra; after startup, verify sessions load and change any remaining compatibility-model session to `gpt-6-luna` when idle. The three Sol names and seven Luna names above are the exact list provided for the owner's pre-restart database recheck.
