CHANGES REQUESTED: installation does not restart or prematurely activate Orchestra, but rollback can destroy post-install changes despite recording installed hashes. Verbatim executable line: `echo "Installed Claude env hook; Orchestra restart is required and was NOT performed"`

Review comment:

- [P1] Refuse rollback when installed files were modified — /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-grep-guard/deploy/manage-claude-env-hook.sh:113-119
  blocking: If either managed destination is edited or replaced after installation, rollback silently overwrites it with the old backup—or moves it away when the original state was absent—causing data loss. Compare both destinations against `installed.sha256` before restoring, and fail loudly on any mismatch so an operator can preserve the unexpected changes.

> ⚠ Codex usage unaccounted: caller did not provide usage attribution

## Round (2026-08-12T08:54:39Z)

Re-review status: **STILL BROKEN**

- [P1] The prior rollback data-loss issue remains as a TOCTOU race. `refuse_modified_install` hashes both destinations, then `restore_one` later overwrites or moves them without revalidating. A manual/process change between those operations is silently lost. Make rollback claim/move each destination atomically before hashing it, and restore only after the moved file matches `installed.sha256`.

New findings: none. No restart or premature activation found; drop-in and hook scope look correct. Targeted suite passes: 3 tests.

Verdict: **CHANGES REQUESTED**

> ⚠ Codex usage unaccounted: caller did not provide usage attribution

## Round (2026-08-12T08:58:30Z)

Re-review status:

- Prior TOCTOU finding: **FIXED**
- [P1] **NEW BUG** — `mv -T "$destination" "$claim"` silently overwrites an existing retained claim if the PID-based claim name is reused. This can destroy the verified installed file preserved by an earlier failed rollback. Claim creation must be no-clobber and fail loudly on collision.

New findings: one blocking claim-collision path. No accidental restart/activation or hook-scope issue found. Targeted suite passes: 3 tests.

Verdict: **CHANGES REQUESTED**

> ⚠ Codex usage unaccounted: caller did not provide usage attribution

## Author response after the round ceiling

Round 3 exhausted the executable-artifact ceiling, so no fourth Codex round was run. The final
blocking finding was accepted and fixed: initial claim creation now also uses no-clobber and
fails while preserving both the installed destination and the retained claim on collision.
A deterministic fake-`mv` test injects a retained claim at the exact pre-rename point; changing
the no-clobber move back to force-overwrite makes that test fail. Targeted result after the fix:
`3 passed in 4.97s`.

This fix is self-verified but has no post-fix Codex verdict because the three-round ceiling was
reached. The open implementation gate is explicitly escalated to the orchestrator.
