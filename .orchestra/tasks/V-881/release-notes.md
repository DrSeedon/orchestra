# Orchestra v2.46.0

Voice input, checklists with time estimates, mechanical rule enforcement and evidence-gated merges. Full details: [CHANGELOG.md](CHANGELOG.md#v2460--2026-10-15--voice-input-checklists-with-time-estimates-mechanical-rules-evidence-gated-merges).

## Highlights

- **Voice input in the dashboard.** Recordings are saved locally while you speak, transcribed on the server, and sent once to the agent selected when recording started.
- **Worker checklists with time estimates.** Durable step lists in the INFO panel; each step takes an optional minute estimate compared with actual time spent.
- **Dashboard design system.** Model colors, statuses and surfaces come from one source.
- **Rules enforced by mechanism.** A shell guard rejects long `sleep` calls and recursive `find`/`grep -r` before they run. It is a narrow policy, not a sandbox.
- **Merge gate with mutation checks.** Mapped tests run before merge; changed tests must fail against the pre-change sources. Failed or inconclusive required gates block the merge.
- **Orchestrators talk across projects.** Project orchestrators can message each other; delivery receipts show whether quota is holding dispatch.
- **Partial (sparse) worker worktrees.** Faster worker startup in large repositories.
- **Quota gate override until a chosen time**, set from the dashboard.
- **Local Russian voice-over for explainer videos** (TeraTTSv2, automatic stress, timed pauses, Manim defaults, bundled CMU Serif).
- **Live chat activity.** Streaming generation and running tools are visible as they happen; attachments show as compact chips.
- **Append-only `.gitignore` conflicts** are merged automatically.
- **Refreshed README (English and Russian) and CONTRIBUTING.**

## Removed

Internal MCP tools and API only: project-memory search (use `rg` over `.orchestra/kb/` and `.orchestra/tasks/`), suggested-task cards, the `idle` background-job type, and the `vps-deploy` skill.

## Upgrading

Python code changes take effect after the service restarts. Dashboard JS/CSS load on page refresh.
