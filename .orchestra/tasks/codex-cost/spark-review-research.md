[BLOCKING] none.

- [SUGGESTION] The split is not “worker vs `codex_review` for all codex activity,” it is specifically **Sol-only** because both worker and review buckets require model `gpt-5.6-sol` in [`measure_usage.py`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-cost/docs/tasks/codex-cost/measure_usage.py) (`SOL = "gpt-5.6-sol"`). If Spark or any other model is used for worker/review work later, the reported quota share will silently drift.

- [SUGGESTION] The review count path pulls only `bg_jobs` with `status='triggered'` and then matches to rollouts in `codex_exec`. Failed/aborted/background errors are excluded from the split (`measure_usage.py` logic). If failures exist in the window, “review share” is undercounted and not directly comparable to raw account spend.

- [SUGGESTION] The `codex_review` MCP implementation currently does **not** expose `--model`/effort controls in [`app/mcp_stdio.py`]( /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-cost/app/mcp_stdio.py), so routing to Spark is not actually operational from this tool path. A conclusion about routing feasibility should be phrased as “wrapper does not currently let caller select model,” not “codex_review path can route.”

- [SUGGESTION] There are two accounting planes: `measure_usage.py` includes bg-job usage while `/api/usage/daily` in [`app/routes/system.py`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-cost/app/routes/system.py) parses only `turn ended` status logs. This can make dashboard validation look inconsistent with the research report unless the same exclusion set is used.

- [SUGGESTION] `model`/`originator`/`cwd` classification logic is serviceable but fragile: it bakes assumptions (window + fixed routing identity), so claims like “definitive” split should be downgraded to “current-instrumentation estimate.”

- [SUGGESTION] Arithmetic itself is broadly consistent with that instrumented scope in this period (sample counts/ratios reproduced), so the strongest falsification is scope, not the math formulas.

**Verdict:** `PASS w/ caveat` — no blocking implementation bug found, but the report’s conclusions are over-broad and should be constrained to the exact measured slice (successful Sol + current orchestration path).