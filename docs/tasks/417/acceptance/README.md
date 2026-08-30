# #417 Phase 2 acceptance checks

These three scripts are the immutable Phase 3 oracles. They inspect production prompts/code and,
where applicable, exercise the future repository-local Markdown validator against scratch fixtures.
They must never be edited to make an implementation pass.

Run them with the main repository environment so `app.pipeline` has its declared dependencies:

```bash
ORCH_PY="$(dirname "$(git rev-parse --git-common-dir)")/.venv/bin/python"
"$ORCH_PY" docs/tasks/417/acceptance/test_t1_file_first_read_protocol.py
"$ORCH_PY" docs/tasks/417/acceptance/test_t2_lexical_fact_contract.py
"$ORCH_PY" docs/tasks/417/acceptance/test_t3_approved_one_hop_links.py
```

T1 and T2 behaviors are independent, but Phase 3 serializes them because both update the focused
prompt-delivery test file. T3 is blocked by T2 because it extends the same Markdown validator, but
its first RED assertion is the missing link-approval protocol rather than the missing validator.

Command baseline: Linux/POSIX shell in the Orchestra Git worktree, with the repository's own
`.venv`. `git rev-parse --git-common-dir` is absolute in linked worktrees and `.git` in the main
checkout, so the same expression resolves the main repository environment in both cases. It was
verified here with Git 2.53.0.
