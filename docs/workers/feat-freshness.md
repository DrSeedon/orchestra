# feat-freshness — personal memory

- `bg_create(type="run", ...)` reports the exit code of the **last command in the chain**, not pytest.
  `pytest ...; tail log` → job says `Exit code: 0` while the log says `1 failed`. Always read the
  summary line, never trust the job's exit code.
- `tests/test_session.py::TestCompactPromptContract` opens a REAL `ClaudeSDKClient` and hangs 60s
  per test when the runtime/quota is unavailable. Reproduces on clean `main` (from #126) — if it
  fails after a merge, check `main` before suspecting your own diff.
