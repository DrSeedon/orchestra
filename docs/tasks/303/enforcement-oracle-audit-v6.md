<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

The v6 freeze is cryptographically intact: every registered SHA-256 matches the exact bytes at `1ec850dbf5b69a35bdcd6422eca1001f5a3576f8`. The later registry commit changes only registry/prose files.

Recorded commands reproduce:

- Self-test: `4 passed`, exit 0.
- Gate 1 RED: `5 failed, 3 passed, 2 deselected`, exit 1.
- Gate 2 RED: `3 failed, 3 passed, 1 deselected`, exit 1.
- Failures are absent production symbols/state, not collection/import failures.

Atomic replay is now a strong deterministic oracle. Two processes receive byte-identical argv, both reach `validated_before_consume`, authority state is unchanged at the barrier, and only then are they released. The oracle requires exit codes `[0, 73]`, reasons `authorized/replay`, one receipt with the winner PID, selector/admission/process `apply_count=1`, one append-only apply row containing only the winner PID, loser PID absent, and an exact zero-delta third replay ([oracle_support.py](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-venv-boundary/docs/tasks/303/oracle_support.py:627)). An `exists()` followed by ordinary write cannot false-green: the barrier forces both contenders past validation together, after which either both authorize, an exit/result differs, two journal rows appear, or authority state/receipt ownership violates the assertions.

The emergency baseline is correctly limited to recovery integrity. The plan explicitly identifies the writable same-UID checkout as counterevidence to prevention and assigns permanent enforcement to controller UID + executor UID + credential broker; env, prompt and path guards remain defense in depth ([plan.md](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-venv-boundary/docs/tasks/303/plan.md:21), [plan.md](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-venv-boundary/docs/tasks/303/plan.md:119), [plan.md](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-venv-boundary/docs/tasks/303/plan.md:156), [plan.md](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-venv-boundary/docs/tasks/303/plan.md:203)).

`cross-family verdict unavailable`. This is a fresh same-family Sol/Codex audit, not cross-family independence.

## Findings

blocking: [test_release_a_recovery.py:153](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-venv-boundary/docs/tasks/303/test_release_a_recovery.py:153) — Gate 1 proves the selected installed manager’s public `activate` implementation, but still does not mechanically prove that deployment invokes it. The deployment check only searches `deploy/install.sh` for independent substrings—`systemd-run` and the manager command—while the selection check merely trusts the declarative `public_activation_command` field ([test_release_a_recovery.py:188](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-venv-boundary/docs/tasks/303/test_release_a_recovery.py:188)). A deployment can retain a dead correct command/string and selection entry while its real `systemd-run` argv invokes a bypass; all nine physical swaps and the no-swap control would still exercise the unused correct manager and pass. The frozen gate therefore does not yet enforce the plan’s claim that the deployed transient unit enters the tested command. Require an executable deployment-command derivation/assertion, or a mutation proving that changing the actual transient-unit caller away from the selected argv turns Gate 1 red.

blocking: [test_release_b_identity.py:171](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-venv-boundary/docs/tasks/303/test_release_b_identity.py:171) — Gate 2 has the same caller-reachability hole. Every cryptographic, context, replay and concurrency arm correctly enters the installed public manager selected by the oracle, and no authority callback is injected. But deployment reachability is inferred solely from `selection["public_authorization_command"]`; no application activation route, transient manager caller, or generated command is executed or inspected. A correct but unused `authorize-commit` command can pass every arm while the real commit caller directly applies state, invokes an injected policy/helper, or bypasses authorization entirely. Require the real activation-commit caller to derive/execute the selected public argv, plus a wiring mutation showing that a direct-helper or direct-apply bypass makes Gate 2 red.

## Verdict

**CHANGES REQUIRED**

Atomic replay and recovery-versus-permanent-boundary wording are approved within scope. Gate 1 and Gate 2 deployment reachability remain blocking authority-bypass false-green paths.
