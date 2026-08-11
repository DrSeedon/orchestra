# Self-review #179

## Scope

Reviewed only `app/mcp_stdio.py`, `tests/test_codex_review_sandbox.py`, and the
acceptance artifacts in this directory. Per task instruction, no Codex implementation
review was used; Codex was used only after the fix to prove command execution.

## Correctness checks

- All four command paths (fresh/resumed `review`, fresh/resumed `exec`, including stale-session
  fallbacks) now put the global CLI policy before `exec`: `-s danger-full-access -a never`.
  This syntax was checked against `codex --help`, `codex exec review --help`, and
  `codex exec resume --help`. `codex exec -s ... -a ...` is invalid; the global ordering is
  required.
- `danger-full-access` is the least permissive available sandbox *mode* that does not invoke the
  unavailable namespace sandbox. `read-only` and `workspace-write` both require vendor `bwrap`.
  `-a never` prevents an unattended background review from waiting for an approval prompt. The
  stronger combined `--dangerously-bypass-approvals-and-sandbox` flag is not needed.
- The failure detector runs after the real Codex exit-code check and before artifact persistence.
  A Codex process that exits 0 but reports `bwrap`, a failed/rejected sandbox, unread files, or
  commands that all failed exits 70. Therefore a blind verdict cannot satisfy `success_file` or
  `success_pattern`.
- The detector reads both JSONL and the final round file. This covers a low-level command failure
  printed as a tool event and a reviewer that only admits the failure in its final answer.
- Existing atomic finalization and session UUID persistence remain unchanged.

## Regression risks checked

- Removed every `--full-auto` and `workspace-write` occurrence from generated review commands.
- Resumed sessions explicitly override their stored policy; otherwise sessions originally created
  with `workspace-write` would remain broken after this fix.
- Shell syntax is exercised by existing command-construction tests and by the new behavioral test.
- The detector is deliberately fail-closed. A review that discusses one of the failure phrases as
  subject matter may be rejected; that is safer than approving a review that executed no command.

## Evidence

- Targeted tests: `23 passed`.
- Original connected MCP process reproduced the blind false success in
  `live-review-original.md` (exit 0 despite `bwrap`).
- Fresh-process patched `codex_review()` executed `sed -n '2p'` and returned
  `Line 2: ORCHESTRA-179-READ-PROOF-68427.` in `live-review-fixed.md`.
- One background shell block copied the fixture, changed line 2, ran the patched review, restored
  the backup while preserving the review exit code, and left no `.bak`. Codex returned
  `Line 2: ORCHESTRA-179-MUTATED-93158.` in `live-review-mutated.md`; the fixture now contains the
  original `ORCHESTRA-179-READ-PROOF-68427` line.

## Remaining deployment gap

Already-connected MCP subprocesses keep the old module until their parent backend disconnects.
The server-side background-job runner currently trusts exit 0 plus a nonempty artifact/verdict and
cannot detect blind output produced by an old MCP command. This is outside the authorized files and
is documented in `report.md` as a separate follow-up.
