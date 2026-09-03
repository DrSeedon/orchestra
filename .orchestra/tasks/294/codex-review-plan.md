## Summary

The plan is substantially security-oriented and matches the requested architecture: immutable private snapshots, HMAC revocation, exact-buffer serving, conditional public routing, sandbox isolation, explicit fallback, and staged enablement. Current references such as `app.auth:requires_auth`, `app.db:init_db`, `app.mcp_stdio:_auth_headers`, `app.tg_bridge:_tg_send_safe`/`send_text_to_tg`, and `app.routes.system:_is_safe_path` are accurate.

Two plan gaps need correction before implementation. Notably, the plan explicitly says: “A rare ambiguous delivery can therefore leave a received but dead link, which is safer than leaving an unreported live capability.”

## Findings

**blocking:** Telegram exceptions and cancellation are not included in the revoke contract.

[plan.md:157](docs/tasks/294/plan.md) specifies revocation only when delivery “does not return explicit success.” `_tg_send_safe()` can raise, and request cancellation/process shutdown can interrupt the await without returning any result. In those paths, the database row remains live even though the caller receives no safe metadata or fallback instruction; Telegram may also already have accepted the message. This violates the stated rule that ambiguous delivery leaves a dead link, not an unreported live capability. T2 must require a delivery-state guard that revokes on every exit other than confirmed success—including exceptions and cancellation—and a deterministic RED oracle for both raised delivery and cancellation after dispatch.

**blocking:** Gate C records revocation but does not require testing secret rotation on real clients.

The authoritative contract says rotation revokes both fragments and grants, and unit group 6 covers it, but the real-browser matrix at [plan.md:364](docs/tasks/294/plan.md) checks only row revocation of an open grant. Cookie parsing/storage and navigation behavior are precisely what Gate C exists to validate across engines. Before enablement, each required engine/client should prove that rotating `ARTIFACT_LINK_SECRET` rejects both an already issued grant cookie and the original fragment; otherwise the cross-engine release gate does not cover a non-negotiable revocation mechanism.

**suggestion:** Rollback leaves no specified cleanup route while the feature is disabled.

Startup cleanup runs only under validated enabled configuration ([plan.md:142](docs/tasks/294/plan.md)), while rollback disables the feature and says expired files can later be removed through that cleanup path ([plan.md:498](docs/tasks/294/plan.md)). As written, cleanup requires temporarily restoring an enabled public configuration or relying on an unspecified manual operation. Define a maintenance cleanup path that can run with public exemptions disabled while remaining registry-scoped and fail-closed.

## Verdict

CHANGES REQUIRED. The architecture is sound, but exception/cancellation-safe Telegram revocation and real-client secret-rotation evidence must be added before Phase 3.

## Round (2026-08-16T11:34:31Z)

## Summary

All three first-round findings were resolved:

- Telegram ambiguity now uses an inert `pending` state and CAS activation only after explicit delivery success.
- Gate C now tests secret rotation against both stored grants and original fragments on every engine/device.
- Registry-scoped cleanup now runs safely while public links are disabled.

The plan still contains exactly 12 test groups, preserves the future RED oracle-entry gate, and changes only `docs/tasks/294/`.

## Findings

No blocking findings or actionable suggestions.

The previous Telegram dissent is closed by the explicit contract: “Every other exit—including a false/non-success result, ordinary exception, `CancelledError` during or after dispatch, database activation failure, or process death before activation—leaves the row non-active.” T2 also specifies deterministic exception, post-dispatch cancellation, and activation-failure oracles.

The previous rotation dissent is closed by Gate C’s per-row requirement to reject both “its already stored grant cookie and its original fragment.”

The previous cleanup dissent is closed by disabled-mode, registry-only cleanup that neither enumerates unregistered files nor creates public auth exemptions.

## Verdict

APPROVED. The plan is ready for the separately authorized oracle-only Phase 3 entry commit; runtime implementation must not begin before that gate.
