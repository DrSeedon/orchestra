<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

The canonical parser mishandles two valid boundary cases: it rejects safe literal executables based only on their basename and persists commands with an empty executable. Both contradict the new externally consumed validation contract.

Full review comments:

- [P2] Restrict shell opt-in detection to exact executable names — /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-acceptance-command-contract/app/acceptance.py:100-101
  blocking: `app/acceptance.py:100` — Using `Path(argv[0]).name` classifies any safe executable whose basename is `bash` or `sh` (for example `./bash --check`) as a shell wrapper and rejects it unless it has the special three-argument shape. This violates the literal-argv contract and the requirement that only exact `bash`/`sh` invocations opt into shell semantics; compare `argv[0]` directly against the allowed executable spellings.

- [P2] Reject an empty executable produced by quoted input — /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-acceptance-command-contract/app/acceptance.py:93-98
  blocking: `app/acceptance.py:93` — Inputs such as `''` or `""` produce `argv == [""]`, so they pass persistence validation even though no executable exists; the runner later reports a generic `os_error` instead of the actionable invalid-command guidance required for legacy rows. Validate that `argv[0]` is non-empty before accepting the command.

> ⚠ Codex usage unaccounted: ValueError: Codex completed turn reported zero tokens

## Round (2026-08-23T18:39:11Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Re-review status

- FIXED — shell opt-in detection now compares exact executable spellings; `./bash --check` remains literal argv while standard bash/sh paths require `-c` or `-lc`.
- FIXED — quoted empty executables now raise `empty_executable` before persistence or execution, with `FIX_ACCEPTANCE_THEN_RETRY` guidance.

## New findings

None in the changed seam.

Tests: `uv run pytest -q tests/test_acceptance.py --tb=short` → `17 passed in 15.57s`.

## Verdict

APPROVED

Changed-file evidence: `if argv[0] in _SHELL_EXECUTABLES:`

> ⚠ Codex usage unaccounted: OperationalError: no such table: turn_usage
