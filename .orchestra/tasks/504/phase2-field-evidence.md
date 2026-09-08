> **RETRACTED как описание текущего main (08.09.2026, #530).** Ниже — историческое доказательство ветки #504, а не действующий контракт. Утверждения о живых площадках A, необходимости внедрить T1/T2/T3/T5, ожидании T4 и текущей пригодности прежних оракулов отменены коммитом `264daeb75484bbe9f97e53c654180fca11c8a12a`: main уже отделяет управление от прозы, удаляет T4-классификатор и safeguard-fork, использует `provider_limit`, завершение CLI и временный round hint. Исторические результаты тестов остаются результатами своих снимков, не текущего main. Адресная развязка всех десяти площадок и тестов: [дифференциал #530](../530/diff-main-vs-504.md). Исходные байты: `git show bf496f8828e4ae5859ac09fd1a20a864ac9e895b:.orchestra/tasks/504/phase2-field-evidence.md`.

# #504 Phase 2 — typed Claude rate-limit field evidence

- Production interpreter: `/mnt/data/Projects/Python/orchestra/.venv/bin/python`.
- Installed package: `claude-agent-sdk==0.2.114`.
- `claude_agent_sdk.types.RateLimitEvent` contains `rate_limit_info`, `uuid`, `session_id`.
- `RateLimitInfo` contains `status`, `resets_at`, `rate_limit_type`, `utilization`, `overage_status`, `overage_resets_at`, `overage_disabled_reason`, and exact `raw`.
- Installed SDK docstring defines `status="rejected"` as “the limit has been hit” and documents using it to back off.
- `app/backend_claude.py:1390` already receives `RateLimitEvent`, but `app/backend_claude.py:1393-1396` flattens it into `AgentEvent("status", "RATE_LIMIT_RAW <json>")`.
- Read-only SQLite online-backup measurement found 613 persisted `RATE_LIMIT_RAW` rows. All 613 had primary `status="allowed"` and `rateLimitType="five_hour"`; all also had `overageStatus="rejected"` with `overageDisabledReason="org_level_disabled"`.
- Negative control: `overageStatus="rejected"` alone cannot mean the primary subscription limit was hit; otherwise all 613 allowed events would be false terminal signals.
- No live `status="rejected"` event was present in the snapshot. Phase 2 therefore freezes a synthetic `RateLimitEvent(status="rejected")` oracle using the exact installed SDK dataclass, while the 613 allowed events prove the real producer path is active.

Design consequence: use only primary `RateLimitInfo.status == "rejected"` to arm terminal behavior. Map `rate_limit_type="overage"` to `monthly`; map `five_hour|seven_day|seven_day_opus|seven_day_sonnet` to `timed`; preserve unknown types as terminal `unknown` (no retry, no guessed auto-wake).
