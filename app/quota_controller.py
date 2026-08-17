"""Pure, shadow-only adaptive quota decisions and durable reservations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4

from app.db import quota_controller_connection


@dataclass(frozen=True)
class ConstraintDecision:
    bucket: str
    regime_key: str
    window_id: str
    utilization: float
    inflight_reserved_pp: float
    q95_next_turn_pp: float
    guard_pp: float
    reserve_pp: float
    lhs_pp: float
    rhs_pp: float
    would_allow: bool | None
    confidence: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class DispatchDecision:
    constraints: tuple[ConstraintDecision, ...]
    would_allow: bool | None
    binding_constraint: str | None
    recommendation: str
    zone: str
    confidence: str
    reasons: tuple[str, ...]
    decision_id: str = ""
    context: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)


def enforce_new_worker_turn(
    *,
    context: Mapping[str, Any],
    adaptive: DispatchDecision | None,
    static_decision,
    enforcement_enabled: bool = True,
) -> dict[str, Any]:
    """Apply the conservative Release-A policy to one new worker turn.

    ``server_role`` is supplied from the persisted session role.  Deliberately do
    not consult caller-provided boolean flags: an orchestrator exemption must be
    a server-owned fact.  Unknown adaptive telemetry falls back to the static
    decision; only a fresh, known adaptive hold can stop an otherwise admissible
    worker turn.
    """
    role = _text(context.get("server_role"))
    if role == "orchestrator":
        return {"action": "exempt", "reason": "orchestrator_exempt"}
    if static_decision is not None and not bool(getattr(static_decision, "allowed", False)):
        return {"action": "static_denial", "reason": "static_gate_denied"}
    if not enforcement_enabled:
        return {"action": "static_allow", "reason": "enforcement_hot_disabled"}

    zone = _text(getattr(adaptive, "zone", ""))
    unsafe_zones = {"THROTTLE", "RESERVE", "FAIL_SAFE"}
    adaptive_allow = getattr(adaptive, "would_allow", None)
    adaptive_confidence = _text(getattr(adaptive, "confidence", "")).lower()
    adaptive_reasons = getattr(adaptive, "reasons", ())
    known_fresh = (
        adaptive is not None
        and adaptive_allow in {True, False}
        and adaptive_confidence in {"operational", "calibrated", "pilot"}
        and not adaptive_reasons
    )
    if not known_fresh:
        return {"action": "static_allow", "reason": "adaptive_indeterminate_static_fallback"}
    model = _text(context.get("model")).lower()
    # Luna's Fast service tier is the server default.  It remains admissible in
    # reserve/fail-safe zones; the old generic ``fast_mode`` stop was an unsafe
    # policy because it could strand the default Luna lane.  Other explicitly
    # fast lanes retain the conservative hold until their own tier is routed.
    is_luna_fast = model in {"gpt-5.6-luna", "gpt-5.6-luna-fast", "luna-fast"}
    if bool(context.get("fast_mode")) and not is_luna_fast and zone in unsafe_zones:
        return {"action": "hold", "reason": "fast_disabled_zone"}
    if (
        "sol" in model
        and _text(context.get("task_class"), "worker") == "noncritical"
        and zone in unsafe_zones
    ):
        return {
            "action": "hold",
            "reason": "noncritical_sol_before_luna",
            "fallback_model": "gpt-5.6-luna",
        }

    if adaptive_allow is True:
        return {"action": "adaptive_allow", "reason": "adaptive_would_allow"}
    if (
        adaptive is not None
        and adaptive_allow is False
        and adaptive_confidence in {"operational", "calibrated", "pilot"}
        and not adaptive_reasons
    ):
        return {"action": "hold", "reason": "adaptive_would_hold"}
    return {"action": "static_allow", "reason": "adaptive_indeterminate_static_fallback"}


@dataclass(frozen=True)
class ShadowDispatchContext:
    """Server-owned identity for one logical provider operation."""

    session_id: str
    turn_gen: int | None
    model: str
    intent_kind: str = "idle_send"
    task_id: str = ""
    task_class: str = "worker"
    fast_mode: bool = False
    started_at: str = ""


class ShadowObserverUnavailable:
    """Explicit rollback observer: it never affects provider delivery."""

    async def reserve_before_submit(self, _context, _static_decision):
        return None

    async def mark_submitted(self, _reservation):
        return None

    async def mark_submit_failed(self, _reservation, _error):
        return None

    def settle_shadow_dispatch(self, *_args, **_kwargs):
        return None


_DISABLED_OBSERVER = ShadowObserverUnavailable()
_shadow_errors_total = 0


def adaptive_enforcement_enabled() -> bool:
    """Read the kill switch for every turn; no restart is needed to disable it."""
    return os.environ.get("ORCHESTRA_ADAPTIVE_ENFORCEMENT", "1").strip().lower() not in {
        "0", "false", "off", "no",
    }


def luna_fast_default_status(*, zone: str = "", telemetry_available: bool = False) -> dict[str, Any]:
    """Describe the server-owned Codex lane policy for Usage Analytics.

    This is deliberately derived from controller state, never from a request field.
    Luna Fast is always the default; a tight Codex runway suppresses Sol and points
    new work/reviews at Luna Fast.  Missing telemetry is visible as a fallback, not
    silently interpreted as available headroom.
    """
    normalized = _text(zone).upper()
    tight = normalized in {"THROTTLE", "RESERVE", "FAIL_SAFE"}
    if tight:
        reason = "codex_runway_tight_route_luna_fast"
    elif telemetry_available:
        reason = "codex_runway_normal_sol_allowed"
    else:
        reason = "codex_telemetry_unavailable_static_fallback"
    return {
        "luna_fast_default": True,
        "sol_suppressed": tight,
        "sol_suppression_reason": reason,
        "luna_fast_reason": "server_owned_default",
    }


def route_codex_model_for_runway(model: str, status: Mapping[str, Any] | None) -> tuple[str, str]:
    """Return the server-owned model lane for a new worker/review operation."""
    requested = _text(model)
    if "sol" not in requested.lower() or not isinstance(status, Mapping):
        return requested, "requested_lane"
    if status.get("sol_suppressed") is True:
        return "gpt-5.6-luna", "sol_suppressed_route_luna_fast"
    return requested, "sol_allowed"


def disabled_observer() -> ShadowObserverUnavailable:
    return _DISABLED_OBSERVER


def record_shadow_error() -> None:
    global _shadow_errors_total
    _shadow_errors_total += 1


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _text(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _window_id(raw: Mapping[str, Any]) -> str:
    return (
        _text(raw.get("window_id"))
        or _text(raw.get("regime_key"))
        or _text(raw.get("reset_at"))
    )


def _constraint_decision(
    raw: Mapping[str, Any],
    target_pct: float,
    active_reserved: float = 0.0,
) -> ConstraintDecision:
    bucket = _text(raw.get("bucket"), "unknown")
    regime_key = _text(raw.get("regime_key"))
    window_id = _window_id(raw)
    reasons: list[str] = []
    invalid_reason = raw.get("invalid_reason")
    if isinstance(invalid_reason, str) and invalid_reason:
        reasons.append(invalid_reason)

    values: dict[str, float | None] = {
        "utilization": _number(raw.get("utilization")),
        "inflight_reserved_pp": _number(raw.get("inflight_reserved_pp", 0.0)),
        "q95_next_turn_pp": _number(raw.get("q95_next_turn_pp")),
        "guard_pp": _number(raw.get("guard_pp")),
        "reserve_pp": _number(raw.get("reserve_pp")),
        "target_pct": _number(target_pct),
    }
    if any(value is None for value in values.values()):
        reasons.append("value_corrupt")
    elif any(value < 0 for key, value in values.items() if key != "target_pct"):
        reasons.append("value_corrupt")

    utilization = values["utilization"] or 0.0
    inflight = values["inflight_reserved_pp"] or 0.0
    q95 = values["q95_next_turn_pp"] or 0.0
    guard = values["guard_pp"] or 0.0
    reserve = values["reserve_pp"] or 0.0
    target = values["target_pct"] or 0.0
    effective_inflight = inflight + active_reserved
    lhs = utilization + effective_inflight + q95 + guard
    rhs = target - reserve
    clean_reasons = tuple(dict.fromkeys(reasons))
    allowed: bool | None = None if clean_reasons else lhs <= rhs
    return ConstraintDecision(
        bucket=bucket,
        regime_key=regime_key,
        window_id=window_id,
        utilization=utilization,
        inflight_reserved_pp=effective_inflight,
        q95_next_turn_pp=q95,
        guard_pp=guard,
        reserve_pp=reserve,
        lhs_pp=lhs,
        rhs_pp=rhs,
        would_allow=allowed,
        confidence=_text(raw.get("confidence"), "unknown"),
        reasons=clean_reasons,
    )


def evaluate_dispatch(
    constraints: Iterable[Mapping[str, Any]],
    *,
    target_pct: float = 99.0,
) -> DispatchDecision:
    """Evaluate every independent quota constraint using the inclusive gate."""
    items = tuple(_constraint_decision(raw, target_pct) for raw in constraints)
    reasons = tuple(dict.fromkeys(reason for item in items for reason in item.reasons))
    if not items:
        return DispatchDecision(
            constraints=(),
            would_allow=None,
            binding_constraint=None,
            recommendation="indeterminate",
            zone="FAIL_SAFE",
            confidence="unknown",
            reasons=("no_constraints",),
        )
    if reasons:
        return DispatchDecision(
            constraints=items,
            would_allow=None,
            binding_constraint=None,
            recommendation="indeterminate",
            zone="FAIL_SAFE",
            confidence="fail_safe",
            reasons=reasons,
        )
    allowed = all(item.would_allow is True for item in items)
    binding = min(items, key=lambda item: item.rhs_pp - item.lhs_pp)
    return DispatchDecision(
        constraints=items,
        would_allow=allowed,
        binding_constraint=binding.bucket,
        recommendation="allow" if allowed else "hold",
        zone="TRACK" if allowed else "THROTTLE",
        confidence=(
            "operational"
            if all(item.confidence == "operational" for item in items)
            else "pilot"
        ),
        reasons=(),
    )


def constraints_for_model(model: str, *, fast_mode: bool = False) -> tuple[dict[str, Any], ...]:
    """Return independent buckets; Fast only changes Codex primary q95."""
    name = model.lower()
    if "grok" in name:
        return ({"bucket": "grok:primary", "q95_multiplier": 1.0},)
    if "spark" in name:
        return ({"bucket": "codex_spark:primary", "q95_multiplier": 1.0},)
    if fast_mode and ("5.6" in name or "5.5" in name):
        return ({"bucket": "codex:primary", "q95_multiplier": 2.5},)
    if fast_mode and "5.4" in name:
        return ({"bucket": "codex:primary", "q95_multiplier": 2.0},)
    if "codex" in name or name.startswith("gpt-"):
        return ({"bucket": "codex:primary", "q95_multiplier": 1.0},)
    if "fable" in name:
        return (
            {"bucket": "anthropic:five_hour", "q95_multiplier": 1.0},
            {"bucket": "anthropic:seven_day", "q95_multiplier": 1.0},
            {"bucket": "anthropic_fable:weekly_scoped", "q95_multiplier": 1.0},
        )
    if "claude" in name or "anthropic" in name:
        return (
            {"bucket": "anthropic:five_hour", "q95_multiplier": 1.0},
            {"bucket": "anthropic:seven_day", "q95_multiplier": 1.0},
        )
    return ()


class SQLiteControllerStore:
    """SQLite owner for append-only shadow decisions and active reservations."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        conn = quota_controller_connection(self.path)
        conn.close()

    def reserve_shadow_dispatch(
        self,
        *,
        decision_id: str,
        constraints: Iterable[Mapping[str, Any]],
        target_pct: float = 99.0,
        context: Mapping[str, Any] | None = None,
        legacy_decision: Mapping[str, Any] | None = None,
    ) -> DispatchDecision:
        if context is None:
            context = {}
        elif not isinstance(context, Mapping):
            context = asdict(context)
        raw_constraints = tuple(constraints)
        conn = quota_controller_connection(self.path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            adjusted: list[dict[str, Any]] = []
            active_by_key: dict[tuple[str, str], float] = {}
            keys = {
                (
                    _text(raw.get("bucket"), "unknown"),
                    _window_id(raw),
                )
                for raw in raw_constraints
            }
            for bucket, window_id in sorted(keys):
                row = conn.execute(
                    """SELECT COALESCE(SUM(reserved_pp), 0) AS reserved
                       FROM quota_controller_inflight_reservations
                       WHERE bucket = ? AND window_id = ? AND state IN ('reserved','submitted')""",
                    (bucket, window_id),
                ).fetchone()
                active_by_key[(bucket, window_id)] = float(row["reserved"])
            for raw in raw_constraints:
                copied = dict(raw)
                key = (
                    _text(raw.get("bucket"), "unknown"),
                    _window_id(raw),
                )
                copied["inflight_reserved_pp"] = (
                    (_number(raw.get("inflight_reserved_pp", 0.0)) or 0.0)
                    + active_by_key[key]
                )
                adjusted.append(copied)
            session_id = _text(context.get("session_id"))
            turn_gen = context.get("turn_gen")
            if session_id and turn_gen is not None:
                existing = conn.execute(
                    """SELECT * FROM quota_controller_decisions
                       WHERE session_id = ? AND turn_gen = ? AND source = 'dispatch'""",
                    (session_id, turn_gen),
                ).fetchone()
                if existing is not None:
                    return self._decision_from_row(existing)
            decision = evaluate_dispatch(adjusted, target_pct=target_pct)
            decision = replace(
                decision,
                decision_id=decision_id,
                context=dict(context),
            )
            now = datetime.now(timezone.utc).isoformat()
            observation = json.dumps(adjusted, sort_keys=True, separators=(",", ":"))
            encoded = json.dumps(asdict(decision), sort_keys=True, separators=(",", ":"))
            legacy = json.dumps(
                dict(legacy_decision or {}), sort_keys=True, separators=(",", ":"),
            )
            conn.execute(
                """INSERT INTO quota_controller_decisions (
                    decision_id, created_at, mode, source, session_id, turn_gen,
                    task_id, task_class, model, fast_mode, critical_intent_id,
                    policy_version, regime_set_hash, observation_at, observation_json,
                    decision_json, legacy_decision_json
                ) VALUES (?, ?, 'shadow', 'dispatch', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    decision_id,
                    now,
                    _text(context.get("session_id")),
                    context.get("turn_gen"),
                    _text(context.get("task_id")),
                    _text(context.get("task_class")),
                    _text(context.get("model")),
                    int(bool(context.get("fast_mode", False))),
                    context.get("critical_intent_id"),
                    int(context.get("policy_version", 1)),
                    _text(context.get("regime_set_hash"), "unknown"),
                    now,
                    observation,
                    encoded,
                    legacy,
                ),
            )
            if decision.would_allow is True:
                for item in decision.constraints:
                    if item.q95_next_turn_pp <= 0:
                        continue
                    conn.execute(
                        """INSERT INTO quota_controller_inflight_reservations (
                            decision_id, bucket, window_id, reserved_pp, state,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, 'reserved', ?, ?)""",
                        (
                            decision_id,
                            item.bucket,
                            item.window_id,
                            item.q95_next_turn_pp,
                            now,
                            now,
                        ),
                    )
            conn.commit()
            return decision
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _decision_from_row(row) -> DispatchDecision:
        raw = json.loads(row["decision_json"])
        constraints = tuple(
            ConstraintDecision(
                **{**item, "reasons": tuple(item.get("reasons", ()))},
            )
            for item in raw.get("constraints", ())
        )
        context = dict(raw.get("context") or {})
        context.update({
            "session_id": row["session_id"],
            "turn_gen": row["turn_gen"],
            "task_id": row["task_id"],
            "task_class": row["task_class"],
            "model": row["model"],
            "fast_mode": bool(row["fast_mode"]),
            "critical_intent_id": row["critical_intent_id"],
        })
        return DispatchDecision(
            constraints=constraints,
            would_allow=raw.get("would_allow"),
            binding_constraint=raw.get("binding_constraint"),
            recommendation=raw.get("recommendation", "indeterminate"),
            zone=raw.get("zone", "FAIL_SAFE"),
            confidence=raw.get("confidence", "unknown"),
            reasons=tuple(raw.get("reasons", ())),
            decision_id=row["decision_id"],
            context=context,
        )

    def active_reserved_pp(self, bucket: str, window_id: str) -> float:
        conn = quota_controller_connection(self.path)
        try:
            row = conn.execute(
                """SELECT COALESCE(SUM(reserved_pp), 0) AS reserved
                   FROM quota_controller_inflight_reservations
                   WHERE bucket = ? AND window_id = ? AND state IN ('reserved','submitted')""",
                (bucket, window_id),
            ).fetchone()
            return float(row["reserved"])
        finally:
            conn.close()

    def decision_count(self) -> int:
        conn = quota_controller_connection(self.path)
        try:
            return int(
                conn.execute("SELECT COUNT(*) AS count FROM quota_controller_decisions").fetchone()[
                    "count"
                ]
            )
        finally:
            conn.close()

    def mark_submitted(self, reservation: DispatchDecision | None):
        if reservation is None or not reservation.decision_id:
            return reservation
        submitted_at = datetime.now(timezone.utc).isoformat()
        conn = quota_controller_connection(self.path)
        try:
            conn.execute(
                """UPDATE quota_controller_inflight_reservations
                   SET state = 'submitted', updated_at = ?
                   WHERE decision_id = ? AND state = 'reserved'""",
                (submitted_at, reservation.decision_id),
            )
            conn.commit()
        finally:
            conn.close()
        return replace(
            reservation,
            context={**dict(reservation.context), "submitted_at": submitted_at},
        )

    def settle_shadow_dispatch(
        self,
        reservation: DispatchDecision | None,
        event_id: str,
        ended_at: str | None = None,
        *,
        status: str = "unscorable",
        actual: Mapping[str, Any] | None = None,
    ) -> dict | None:
        if reservation is None or not reservation.decision_id or not event_id:
            return None
        ended = ended_at or datetime.now(timezone.utc).isoformat()
        context = dict(reservation.context)
        submitted = (
            _text(context.get("submitted_at"))
            or _text(context.get("started_at"))
            or ended
        )
        conn = quota_controller_connection(self.path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """SELECT * FROM quota_controller_outcomes
                   WHERE decision_id = ? OR terminal_event_id = ?""",
                (reservation.decision_id, event_id),
            ).fetchone()
            if existing is not None:
                conn.commit()
                return dict(existing)
            concurrent = conn.execute(
                """SELECT COUNT(*) AS count FROM quota_controller_outcomes
                   WHERE submitted_at < ? AND ended_at > ?""",
                (ended, submitted),
            ).fetchone()["count"]
            settled = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """INSERT INTO quota_controller_outcomes (
                    decision_id, terminal_event_id, submitted_at, ended_at,
                    settled_at, status, concurrent_dispatches, actual_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    reservation.decision_id,
                    event_id,
                    submitted,
                    ended,
                    settled,
                    status,
                    int(concurrent),
                    json.dumps(dict(actual or {}), sort_keys=True),
                ),
            )
            conn.execute(
                """UPDATE quota_controller_inflight_reservations
                   SET state = 'released', updated_at = ?
                   WHERE decision_id = ? AND state IN ('reserved','submitted')""",
                (settled, reservation.decision_id),
            )
            conn.commit()
            return {
                "decision_id": reservation.decision_id,
                "terminal_event_id": event_id,
                "submitted_at": submitted,
                "ended_at": ended,
                "status": status,
                "concurrent_dispatches": int(concurrent),
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def outcome_count(self, event_id: str) -> int:
        conn = quota_controller_connection(self.path)
        try:
            return int(conn.execute(
                "SELECT COUNT(*) AS count FROM quota_controller_outcomes "
                "WHERE terminal_event_id = ?",
                (event_id,),
            ).fetchone()["count"])
        finally:
            conn.close()

    def list_outcomes(self) -> list[dict]:
        conn = quota_controller_connection(self.path)
        try:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM quota_controller_outcomes ORDER BY submitted_at, decision_id"
            ).fetchall()]
        finally:
            conn.close()

    def create_reserve_intent(self, payload: Mapping[str, Any]) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        intent_id = _text(payload.get("intent_id")) or uuid4().hex
        values = {
            "intent_id": intent_id,
            "created_at": now,
            "deadline_at": _text(payload.get("deadline_at"), now),
            "task_id": _text(payload.get("task_id")),
            "logical_work_id": _text(payload.get("logical_work_id")),
            "reason": _text(payload.get("reason")),
            "lane": _text(payload.get("lane")),
            "task_class": _text(payload.get("task_class")),
            "model": _text(payload.get("model")),
            "turn_count": int(payload.get("turn_count", 1)),
            "created_by": _text(payload.get("created_by"), "owner"),
        }
        conn = quota_controller_connection(self.path)
        try:
            conn.execute(
                """INSERT INTO quota_controller_reserve_intents (
                    intent_id, created_at, deadline_at, task_id, logical_work_id,
                    reason, lane, task_class, model, turn_count, state, revision, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'planned', 1, ?)""",
                tuple(values[key] for key in (
                    "intent_id", "created_at", "deadline_at", "task_id",
                    "logical_work_id", "reason", "lane", "task_class", "model",
                    "turn_count", "created_by",
                )),
            )
            conn.commit()
            return {**values, "state": "planned", "revision": 1}
        finally:
            conn.close()

    def cancel_reserve_intent(self, intent_id: str) -> dict | None:
        conn = quota_controller_connection(self.path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM quota_controller_reserve_intents WHERE intent_id = ?",
                (intent_id,),
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            cursor = conn.execute(
                """UPDATE quota_controller_reserve_intents
                   SET state = 'cancelled', revision = revision + 1
                   WHERE intent_id = ? AND state = 'planned'""",
                (intent_id,),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                return dict(row)
            conn.commit()
            return {**dict(row), "state": "cancelled", "revision": row["revision"] + 1}
        finally:
            conn.close()

    def status(self) -> dict:
        status = empty_status()
        status["decision_count"] = self.decision_count()
        conn = quota_controller_connection(self.path)
        try:
            status["outcome_count"] = int(conn.execute(
                "SELECT COUNT(*) AS count FROM quota_controller_outcomes"
            ).fetchone()["count"])
        finally:
            conn.close()
        return status

    def analytics_snapshot(self) -> dict:
        """Return bounded, redacted shadow history for Usage Analytics."""
        conn = quota_controller_connection(self.path)
        try:
            rows = conn.execute(
                """SELECT created_at, model, decision_json, observation_json
                   FROM quota_controller_decisions
                   ORDER BY created_at DESC LIMIT 100"""
            ).fetchall()
            outcome_rows = conn.execute(
                """SELECT status, COUNT(*) AS count
                   FROM quota_controller_outcomes GROUP BY status"""
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            return {
                "data_available": False,
                "reason": "no_shadow_telemetry",
                "decision_counts": {"would_allow": 0, "would_hold": 0, "indeterminate": 0},
                "actual_hold_count": 0,
                "outcome_count": 0,
                "latest": None,
                "today_codex": {"data_available": False, "reason": "no_shadow_telemetry"},
                "history": [],
                "buckets": [],
            }
        counts = {"would_allow": 0, "would_hold": 0, "indeterminate": 0}
        history: list[dict[str, Any]] = []
        buckets: dict[str, dict[str, Any]] = {}
        today = datetime.now(timezone.utc).date().isoformat()
        codex_today = 0
        for row in rows:
            try:
                raw = json.loads(row["decision_json"])
            except (TypeError, ValueError):
                raw = {}
            try:
                observations = json.loads(row["observation_json"])
            except (TypeError, ValueError):
                observations = []
            observations_by_bucket = {
                _text(item.get("bucket"), "unknown"): item
                for item in observations if isinstance(item, Mapping)
            }
            value = raw.get("would_allow")
            key = "would_allow" if value is True else "would_hold" if value is False else "indeterminate"
            counts[key] += 1
            model = _text(row["model"], "unknown")
            if row["created_at"].startswith(today) and ("codex" in model.lower() or "gpt-" in model.lower()):
                codex_today += 1
            reasons = [str(item) for item in raw.get("reasons", ()) if isinstance(item, str)]
            history.append({
                "created_at": row["created_at"],
                "model": model,
                "would_allow": value,
                "zone": _text(raw.get("zone"), "FAIL_SAFE"),
                "binding_constraint": raw.get("binding_constraint"),
                "reasons": reasons[:5],
            })
            for item in raw.get("constraints", ()):
                if not isinstance(item, Mapping):
                    continue
                bucket = _text(item.get("bucket"), "unknown")
                observation = observations_by_bucket.get(bucket, {})
                reset_at = _text(observation.get("reset_at")) or None
                runway_seconds = None
                if reset_at:
                    try:
                        runway_seconds = max(
                            0.0,
                            datetime.fromisoformat(reset_at.replace("Z", "+00:00")).timestamp()
                            - time.time(),
                        )
                    except ValueError:
                        runway_seconds = None
                if bucket in buckets:
                    continue
                buckets[bucket] = {
                    "bucket": bucket,
                    "utilization": item.get("utilization"),
                    "q95_next_turn_pp": item.get("q95_next_turn_pp"),
                    "inflight_reserved_pp": item.get("inflight_reserved_pp"),
                    "guard_pp": item.get("guard_pp"),
                    "reserve_pp": item.get("reserve_pp"),
                    "headroom_pp": item.get("rhs_pp"),
                    "projected_end_pp": item.get("lhs_pp"),
                    "reset_at": reset_at,
                    "runway_seconds": runway_seconds,
                    "zone": _text(raw.get("zone"), "FAIL_SAFE"),
                }
        outcome_count = sum(int(row["count"]) for row in outcome_rows)
        actual_hold_count = sum(
            int(row["count"]) for row in outcome_rows if row["status"] == "adaptive_hold"
        )
        latest = history[0] if history else None
        return {
            "data_available": True,
            "reason": "shadow_telemetry_available",
            "decision_counts": counts,
            "actual_hold_count": actual_hold_count,
            "outcome_count": outcome_count,
            "latest": latest,
            "today_codex": {
                "data_available": codex_today > 0,
                "count": codex_today,
                "reason": "observed" if codex_today else "no_codex_decisions_today",
            },
            "history": history[:50],
            "buckets": list(buckets.values())[:20],
        }


class ProductionShadowController:
    """Process-owned observer that records advice but never owns admission."""

    def __init__(self) -> None:
        self._store_path: Path | None = None
        self._store_instance: SQLiteControllerStore | None = None

    def _store(self) -> SQLiteControllerStore:
        from app.db import DB_PATH

        path = Path(DB_PATH)
        if self._store_instance is None or self._store_path != path:
            self._store_instance = SQLiteControllerStore(path)
            self._store_path = path
        return self._store_instance

    @staticmethod
    def _legacy(static_decision) -> dict:
        if static_decision is None:
            return {"state": "not_applicable", "reason": "orchestrator_static_exempt"}
        serialize = getattr(static_decision, "to_dict", None)
        if callable(serialize):
            return serialize()
        return {"state": _text(getattr(static_decision, "state", None), "unknown")}

    @staticmethod
    def _constraints(context: Mapping[str, Any]) -> tuple[list[dict], str]:
        from app.routes.system import _quota_observation_from_cache

        observation = _quota_observation_from_cache()
        providers = observation.get("providers") or {}
        observed = observation.get("observed_at_by_provider") or {}
        now = time.time()
        result: list[dict] = []
        regime_parts: list[str] = []
        for topology in constraints_for_model(
            _text(context.get("model")),
            fast_mode=bool(context.get("fast_mode", False)),
        ):
            bucket = topology["bucket"]
            provider_id, window_name = bucket.split(":", 1)
            provider = providers.get(provider_id)
            windows = provider.get("windows", ()) if isinstance(provider, Mapping) else ()
            window = next(
                (
                    item for item in windows
                    if isinstance(item, Mapping) and item.get("id") == window_name
                ),
                None,
            )
            utilization = _number(window.get("utilization")) if window else None
            sampled_at = _number(observed.get(provider_id))
            invalid_reason = "unknown_q95"
            if window is None:
                invalid_reason = "telemetry_missing"
            elif utilization is None or not 0 <= utilization <= 100:
                invalid_reason = "value_corrupt"
            elif sampled_at is None or now - sampled_at < 0 or now - sampled_at >= 300:
                invalid_reason = "telemetry_stale"
            plan = _text(provider.get("plan_type")) if isinstance(provider, Mapping) else ""
            minutes = window.get("window_minutes") if window else None
            reset_at = _text(window.get("resets_at")) if window else ""
            regime = f"{bucket}|{plan}|{minutes}|{_text(context.get('model'))}"
            regime_parts.append(regime)
            result.append({
                "bucket": bucket,
                "utilization": utilization,
                "inflight_reserved_pp": 0.0,
                "q95_next_turn_pp": 0.0,
                "guard_pp": 0.5,
                "reserve_pp": 0.0,
                "window_id": f"{bucket}|{reset_at or 'unknown'}",
                "reset_at": reset_at or None,
                "observed_at": sampled_at,
                "regime_key": regime,
                "confidence": "cold",
                "invalid_reason": invalid_reason,
            })
        digest = hashlib.sha256("\n".join(sorted(regime_parts)).encode()).hexdigest()
        return result, digest

    async def reserve_before_submit(self, context, static_decision):
        context_map = asdict(context) if not isinstance(context, Mapping) else dict(context)
        constraints, regime_set_hash = self._constraints(context_map)
        context_map["regime_set_hash"] = regime_set_hash
        turn_gen = context_map.get("turn_gen")
        decision_id = (
            f"shadow:{_text(context_map.get('session_id'))}:{turn_gen}"
            if turn_gen is not None
            else f"shadow:{uuid4().hex}"
        )
        return await asyncio.to_thread(
            self._store().reserve_shadow_dispatch,
            decision_id=decision_id,
            constraints=constraints,
            context=context_map,
            legacy_decision=self._legacy(static_decision),
        )

    async def mark_submitted(self, reservation):
        return await asyncio.to_thread(self._store().mark_submitted, reservation)

    async def mark_submit_failed(self, reservation, error):
        if reservation is None:
            return None
        return await asyncio.to_thread(
            self._store().settle_shadow_dispatch,
            reservation,
            f"submit-failed:{reservation.decision_id}",
            status="submit_failed",
            actual={"error_class": type(error).__name__},
        )

    async def settle_shadow_dispatch(self, *args, **kwargs):
        return await asyncio.to_thread(
            self._store().settle_shadow_dispatch, *args, **kwargs,
        )

    async def create_reserve_intent(self, payload):
        return await asyncio.to_thread(self._store().create_reserve_intent, payload)

    async def cancel_reserve_intent(self, intent_id):
        return await asyncio.to_thread(self._store().cancel_reserve_intent, intent_id)

    def _latest_codex_lane(self) -> tuple[str, bool]:
        """Return a fresh, known Codex-primary zone for Sol suppression.

        Analytics history is provider-agnostic.  Sol routing must not infer Codex
        pressure from a newer Grok/Anthropic row or from stale FAIL_SAFE data.
        """
        conn = quota_controller_connection(self._store().path)
        try:
            rows = conn.execute(
                """SELECT decision_json, observation_json
                   FROM quota_controller_decisions
                   ORDER BY created_at DESC LIMIT 100"""
            ).fetchall()
        finally:
            conn.close()
        now = time.time()
        for row in rows:
            try:
                decision = json.loads(row["decision_json"])
                observations = json.loads(row["observation_json"])
            except (TypeError, ValueError):
                continue
            constraints = decision.get("constraints")
            if not isinstance(constraints, list):
                continue
            primary = next(
                (item for item in constraints
                 if isinstance(item, Mapping) and item.get("bucket") == "codex:primary"),
                None,
            )
            if not isinstance(primary, Mapping):
                continue
            if primary.get("would_allow") not in {True, False}:
                continue
            if decision.get("confidence") not in {"operational", "calibrated", "pilot"}:
                continue
            if decision.get("reasons"):
                continue
            obs = next(
                (item for item in (observations if isinstance(observations, list) else ())
                 if isinstance(item, Mapping) and item.get("bucket") == "codex:primary"),
                None,
            )
            sampled = _number(obs.get("observed_at")) if isinstance(obs, Mapping) else None
            if sampled is None or sampled > now or now - sampled >= 300:
                continue
            return _text(decision.get("zone")), True
        return "", False

    def status(self) -> dict:
        status = self._store().status()
        shadow = self._store().analytics_snapshot()
        status["shadow"] = shadow
        latest_zone, codex_known = self._latest_codex_lane()
        status.update(
            luna_fast_default_status(
                zone=latest_zone,
                telemetry_available=codex_known,
            )
        )
        status["enforcement_enabled"] = adaptive_enforcement_enabled()
        status["enforcement_active"] = adaptive_enforcement_enabled()
        status["enforcement_tier"] = "precalibration"
        status["enforcement_reason"] = (
            "active_precalibration" if status["enforcement_active"] else "enforcement_hot_disabled"
        )
        return status


_production_controller: ProductionShadowController | None = None


def get_quota_controller() -> ProductionShadowController:
    global _production_controller
    if _production_controller is None:
        _production_controller = ProductionShadowController()
    return _production_controller


def empty_status() -> dict:
    return {
        "mode": "shadow",
        # Legacy shadow status helper remains non-authoritative for #291 callers;
        # ProductionShadowController.status() overlays the live kill-switch state.
        "enforcement_active": False,
        "enforcement_enabled": False,
        "enforcement_tier": "precalibration",
        "enforcement_reason": "active_precalibration",
        "static_comparison_counts": {
            "agree": 0,
            "adaptive_would_allow": 0,
            "adaptive_would_hold": 0,
            "adaptive_indeterminate": 0,
        },
        "observer_errors_total": _shadow_errors_total,
        **luna_fast_default_status(telemetry_available=False),
    }


def annotate_concurrent_intervals(outcomes: Iterable[Mapping[str, Any]]) -> list[dict]:
    items = [dict(item) for item in outcomes]
    for index, item in enumerate(items):
        start, end = item.get("submitted_at"), item.get("ended_at")
        item["concurrent_consumers"] = bool(start and end) and any(
            other_index != index
            and other.get("submitted_at")
            and other.get("ended_at")
            and other["submitted_at"] < end
            and other["ended_at"] > start
            for other_index, other in enumerate(items)
        )
    return items
