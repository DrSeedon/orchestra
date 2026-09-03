# T1 — readiness before/after and mutations

Commit before implementation: `95fdbae`.

## Behavioral before

Command:

```bash
uv run pytest -q \
  tests/test_mcp_quota_gate.py::test_legacy_server_requires_explicit_upgrade_before_review \
  tests/test_mcp_quota_gate.py::test_expired_available_readiness_is_rejected_before_review \
  tests/test_usage_readiness.py::test_readiness_endpoint_exposes_worker_weekly_policy \
  tests/test_usage_readiness.py::test_unknown_model_endpoint_fails_closed_without_refresh
```

Raw aggregate: `4 failed in 8.07s`.

- legacy server returned `weekly_quota_unknown`, not actionable
  `weekly_quota_upgrade_required`;
- expired `available` launched instead of raising;
- endpoint lacked `wire_version` and `decision_state`.

## Behavioral after

```text
64 passed in 6.81s
```

Command:

```bash
uv run pytest -q tests/test_quota_gate.py tests/test_usage_readiness.py \
  tests/test_mcp_quota_gate.py tests/test_mcp_codex_review.py
```

Rollout/client subset repeated without changes:

```text
31 passed in 5.37s
31 passed in 5.54s
31 passed in 5.84s
```

Strict self-review added a malformed-skew guard: canonical
`decision_state` is accepted only with exact integer `wire_version=2`; v1
without canonical fields remains supported. The full T1 subset after that
guard was `68 passed in 5.89s`.

## Independent mutations

Каждая мутация выполнялась из свежего `cp`, targeted test запускался, затем
файл восстанавливался через `mv` в той же shell-команде; marker count после
отката был `1`.

| ID | Mutation | Behavioral red evidence |
|---|---|---|
| M1 | weekly `>=95` → `>95` | exact-threshold test: `1 failed in 4.07s` |
| M2 | legacy projection разрешает `unknown` | unknown-projection test: `1 failed in 4.09s` |
| M3 | freshness `valid_until <= now` → `< now` | boundary matrix: `1 failed, 4 passed in 5.21s` |
| M4 | new client читает top-level legacy `state`, игнорируя `decision_state` | canonical-preference test: `1 failed in 4.77s` |
| M5 | synthetic legacy retry `60s` → `0s` | retry timestamp test: `1 failed in 4.01s` |

Все пять мутаций обнаружены; после каждой production marker восстановлен.
