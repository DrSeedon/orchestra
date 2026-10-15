# V-879 — Public README refresh

## Section-by-section disposition

| Section | Status | Why |
|---|---|---|
| Opening description | Updated | Kept the team-orchestration pitch, clarified the self-hosted product and persistent workers, and avoided owner-specific copy. |
| Dashboard GIF, tour video, dashboard screenshot | Kept and updated captions | Restored the existing `dashboard-live.gif`, original user-attachment tour, and `dashboard-real.png`; the Russian README retains its localized GIF, tour, and screenshot. Removed the 85/74-second labels because runtime duration was not rechecked; the media links remain. |
| Navigation and badges | Updated | Kept repository, license, Python, and changelog navigation; removed the company site link and “built by itself” badge, which added no onboarding value and identified an owner-linked property. |
| Quick Start | Updated | Kept the source install and run flow; replaced the inaccurate assumption that Claude Code is the default with runtime/provider configuration, warned users to replace `.env` placeholders, and corrected Node.js from a required 18+ dependency to optional CLI integration. `CONTRIBUTING.md` says Node is optional for Codex integration, and the repository has no Node package manifest. |
| Offline install | Kept and checked | Restored the bundle build/install instructions from `scripts/build_offline_bundle.sh` and `deploy/install-offline.sh`; removed the old approximate archive size and Chromium `/limits` detail because they were unnecessary and liable to age. |
| How It Works | Kept and updated | Restored the workflow diagram and explanation; made review conditional/accurate rather than promising an active cross-model reviewer. |
| “What Orchestra does, doesn’t…” capability table | Updated | Replaced implementation paths, old status dates, and one-off metrics with a smaller current-state table covering lifecycle, isolation, communication, merge gates, frozen model review, shell limits, memory, runtimes, UI, and quota delivery. |
| Sub-agent comparison | Removed | Vendor statements were last checked 2026-09-03 and lifecycle measurements were from 2026-09-02; no fresh comparative research was in scope. |
| Orca head-to-head | Removed | Its README snapshot was from 2026-09-05 and audience/install claims were time-sensitive; removed the dated third-party comparison rather than presenting it as current. |
| “Where we are behind” comparison | Removed | Included a host-specific tool-latency benchmark and competitor observations last checked 2026-09-03; neither establishes current general product behavior. |
| Persistent Agent Fleet | Updated | Retained the feature and described durable sessions, hibernation, and restart recovery without old lifetime statistics. |
| Git Worktree Isolation | Updated | Retained isolation and added project-configured sparse worktrees and ownership checks, consistent with current implementation. |
| Telegram Bridge | Updated | Retained optional text/file/image/voice workflow and clarified that transcription requires provider configuration. |
| Cross-Model Review | Updated | Retained the heading but disclosed that model review is frozen by policy; distinguished the dormant service from the merge gate’s review-coverage enforcement. |
| Orchestrator hierarchy | Updated | Retained project orchestrators, sub-orchestrators, and workers; added cross-project messaging without naming other projects. |
| Built by itself | Updated | Retained self-development as a scenario, with no stale installation session counts. |
| Per-role model policy | Updated | Retained routing and runtime choices, qualified by configured routes/credentials/provider availability. |
| Task Manager | Updated | Retained durable task assignments/run history and current checklists; removed unsupported payment-tracking and approval-card claims (V-873 removed proposal cards). |
| Persistent Sessions / Background Jobs | Updated | Retained session and job behavior while avoiding the former unconditional “costs nothing” claim. |
| Durable Bug Inbox | Retained and updated | Kept the user-facing `report_bug` flow and described its isolation from worker Git changes. |
| Project Memory | Updated | Kept project-rule/KB/task retrieval; clarified lexical `rg` retrieval and that vector search is not current. |
| Real-Time Dashboard | Updated | Retained dashboard capability, added Info checklists and fresh chat snapshots; removed stale component implementation details. |
| New merge safeguards feature | Added | Describes current mapped test, applicable mutation, review coverage, diff/repository gates and append-only `.gitignore` merge behavior. |
| Real Projects Built with Orchestra | Kept, anonymized | Removed named clients/projects, locations, private repositories, and old scale figures; preserved only generalized categories of completed work. |
| Architecture | Kept and updated | Restored the high-level diagram with generic project labels; omitted the former inventory of internal tables and private service-state details. |
| Telegram Bridge setup | Kept and updated | Restored setup variables while using placeholders only and marking transcription optional. |
| Stack | Kept and updated | Restored the technology overview; removed stale/version-specific library claims and stated optional integrations. |
| Currently in Progress | Added | Lists only the three owner-identified active areas, explicitly without dates or delivery promises. |
| Contributing | Kept and updated | Fixed the placeholder repository URL and aligned the test command with `scripts/run_tests.py`. |
| License | Kept and updated | Retained AGPL and NOTICE references without naming an owner or offering a private contact route. |

## Sources and validation

Checked current behavior against `CHANGELOG.md` entries through V-873 and relevant implementation: `app/checklists.py`, `app/shell_policy.py`, `app/merge_test_gate.py`, `app/quota_queue.py`, `app/quota_gate.py`, `app/sparse_worktree.py`, `app/workspace.py`, and `scripts/video_artifact/`. Offline-install instructions were checked against the two referenced scripts. The five-second shell-guard threshold and Python 3.12 / CPython 3.12 bundle target remain because they are explicit current contracts; stale dashboard/session counts, host benchmarks, and dated comparisons were removed.

`docs/` contains dashboard media and operator setup files, not another feature guide, so no additional docs file was changed. No application code or prompts changed.

Validation: `git diff --check`; internal Markdown file links in README, Russian README, and CONTRIBUTING checked with no missing targets; manually checked that tour/media references were restored and private-project names and old numeric comparison claims were absent. No behavior tests apply to this documentation-only change; no wording tests were added.
