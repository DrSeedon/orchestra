# V-1083 clean start — notes

Design: `ProjectOptions.clean_start` (hub-projects.json, explicit `true`) lets `HubBackend._run_turn`
step around records refused by the V-1073 guard ("quarantine") instead of raising. It then mints a new
`WorkspaceState` (`clean_start=True`, `clean_start_of=[old ids]`), checks the new remote dir does not exist
(`HubSsh.assert_fresh_target`, lstat-based), forces `persistent=False` (no warm base), requires explicit paths,
and skips the quarantined ids in `release_for_worktree(skip=...)`. A clean generation resumed later is
authorized by its own persisted `clean_start_of`; a clean generation is never itself quarantined.
Not done / unverified: real SSH shell for `assert_fresh_target` (only the FakeSsh local bash path ran);
old record latched by a first remote check keeps being latched by the existing guard (not new).
Tests: tests/test_hub_clean_start_v1083.py (isolated, fake transports).

## Round 2 (new worktree + poisoned persistent base)
Gap: `_run_turn` set `clean_start` only when same-worktree records were quarantined, so a NEW worktree
(retained=[]) with `clean_start=true` still went through `provision_from_base` and hit the blocked base.
Change (app/backend_hub.py, one condition): `if quarantined or options.clean_start:` — with the owner option
on, every NEW generation is strict-fresh checked (`assert_fresh_target` before save), marked `clean_start`
(`clean_start_of` = quarantined ids, possibly empty) and thereby forced to `persistent=False`: the base is
never read, cloned, refreshed or rewritten. Authorization persists in the record, so retry/restart after the
option is removed stays clean; resuming never needs the option. Behaviour change: ordinary test renamed
`test_ordinary_clean_path_unchanged_with_option_off` (option on now implies clean generation).
New tests (tests/test_hub_clean_start_v1083.py): `test_new_worktree_with_poisoned_base_starts_clean_without_touching_base`
[blocked|uninspected|manifest] (no WorkspaceState; base json + base dir bytes identical after; no
COMPANY-DATA in remote/manifest/input_manifest; local original kept; restart after option removal works;
control: provision_from_base on the same poisoned base still raises HubFilePolicyError for blocked/manifest) and
`test_new_worktree_clean_generation_contamination_still_refuses`.
Red/green: with the condition reverted to `if quarantined:` the 3 new parametrized cases FAIL (17 pass);
restored -> `tests/test_hub_clean_start_v1083.py tests/test_hub_file_policy_v1073.py`: 85 passed.

## Full run, verbatim stdout
`pytest-full-stdout.txt` in this directory is the complete verbatim output of
`uv run --frozen python -m pytest tests/test_hub_*.py tests/test_backend_hub.py tests/test_workspace.py
tests/test_audit0901_workspace.py tests/test_message_provenance_*.py tests/test_send_provenance_without_auth.py
tests/test_v1028_hub_outbox_report.py tests/test_instruction_contract.py tests/test_workflow_cards.py
tests/test_workflow_scheduler.py tests/test_dynamic_workflows.py -q -p no:cacheprovider`
Result: 9 failed, 749 passed, 1 error (identical set to round 1, which had 745 passed before the 4 new tests).
Failures, with causes seen in that output:
- test_hub_inputs_v1063::test_plain_upload_freezes_no_exemptions_even_after_git_init[False,True],
  test_hub_uv (6 tests): `HubWorkspaceError: cannot inspect Git index for hub input provenance`
  raised in `capture_inputs` (not touched by this task; this copy has no .git).
- test_workspace::TestCreateWorktree::test_different_repos_no_collision: git identity missing
  ("to set your account's default identity") -> "worktree already exists".
- ERROR test_workflow_cards::test_dynamic_workflow_call_renders_detail_card_and_expands_answer:
  FastAPI lifespan startup (`TaskStore(...).initialize()` / git commit), same git environment.
Baseline: NOT compared. This copy has no Git and no pristine sources, so no verdict is claimed; the host should
rerun these 10 on the unmodified base. None of them reference clean_start, assert_fresh_target or the changed code path.
Not run: scripts/run_tests.py full suite; real SSH (assert_fresh_target ran only via FakeSsh local bash).

## Host acceptance

Full corresponding host selection: 759 passed, 2 subtests, no deselections/skips. All nine worker failures and the setup error pass in actual Git checkout with process-scoped test author identity; no claim of pristine remote-copy baseline comparison. Canonical instruction contract passes. Root in-memory removal of new-worktree clean-start makes three committed base cases fail; allowing a dirty clean generation makes its privacy oracle fail; removing strict target check fails all three pre-existing target-kind oracles. Imported app: /home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-clean-hub-start/app/__init__.py.

Strict fresh-target probe also passed on actual configured SSH transport using a random nonexistent path, read-only: no remote files or provider calls. Earlier probe cleanup mistakenly called a nonexistent close() after the assertions; corrected probe exits zero. Real remote EACCES/ENOTDIR were not manufactured. Actual model start and project configuration remain separate delivery operations; old blocked records/history/base are not cleared. Worker stdout is a labelled public derivative; original and before/after hashes retained privately.
