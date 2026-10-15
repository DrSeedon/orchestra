# V-873: remove proposal cards and duplicate INFO blocks

## Changes

Removed the `propose_task` MCP tool, task proposal routes/storage/UI/styles/translations and route-surface entries. The schema no longer creates the table; startup runs `DROP TABLE IF EXISTS task_proposals` after `init_db()` to remove existing proposal rows.

INFO now renders only child workers whose checklist has a positive total. The collapsed child-work summary is removed; the chat and session list remain the discussion/status surfaces. A direct dashboard render with one worker with a checklist and one without produced exactly one worker card and no disclosure block; screenshot: [info.png](info.png).

The 15.10 owner review decision and reason are recorded under Removed in CHANGELOG and in [tasks-and-projects KB](../../kb/tasks-and-projects.md). Return to task cards if proposals are written into the orchestrator's chat.

## Verification

- `uv run --frozen python -m pytest tests/test_frontend.py::test_info_panel_shows_only_workers_with_checklists tests/test_routes_surface.py tests/test_tailwind_css.py tests/test_checklists_v858.py -q` — 14 passed.
- Full browser suite: `uv run --frozen python -m pytest -m browser tests/ -q` — 200 passed, 7 skipped, 4432 deselected.
- `bash scripts/build-tailwind.sh` run because utility classes were removed from `app.js`; `tests/test_tailwind_css.py` passed as part of the 14-test command.
- Startup migration check: seeded a disposable DB with four rows, started the dashboard against it, and verified the table was absent once startup completed.
- `rg -n 'propose_task|task_proposals' app tests` finds only the startup `DROP TABLE` line. A scan for proposal routes/classes/renderers and the removed child-work block found no remaining references in `app/` or `tests/`.
- The test suite rewrote four tracked V-860 screenshots; restored those test-generated changes. Working tree is clean.

Python startup code changed, so an owner-initiated service restart is required; none was performed.
