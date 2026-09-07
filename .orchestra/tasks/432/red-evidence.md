# #432 RED evidence

Frozen oracle commit: `db30b40d`. Prior `da7d6934`/`c36e22c6`/`fe587b86` are excluded: before review the
oracle was refrozen for currency revision; after Luna blockers it was refrozen again for one
terminal cumulative usage row, exact digest, auth/env canary, judge-timeout taxonomy and actual
serialized handoff bytes/hash; final refreeze distinguishes provider-missing terminal from
completed/duplicate-terminal parser failures.

Command:

```bash
/home/kesha/orchestra/.venv/bin/python -m pytest -q docs/tasks/432/acceptance/test_experiment_432.py
```

Observed: `5 failed`, exit 1. Each ticket fails on its own missing behavior, not import/collection:

```text
T1 AssertionError: missing behavior T1: controller-only oracle CLI does not exist
T2 AssertionError: missing behavior T2: inline Luna arm runner does not exist
T3 AssertionError: missing behavior T3: scout+main Luna arm runner does not exist
T4 AssertionError: missing behavior T4: paired experiment analyzer does not exist
T5 AssertionError: missing behavior T5: live Luna A/B result has not been delivered
```

All five exact node ids and AC are in `plan.md` under `## Tickets`.
