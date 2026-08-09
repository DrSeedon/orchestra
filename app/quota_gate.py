"""Admission policy for new subscription-backed worker turns."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Awaitable, Callable, Mapping

from app.models import backend_for_model, resolve_model
from app.runtime_registry import get_runtime


WEEKLY_WINDOW_MINUTES = 10080
WORKER_WEEKLY_LIMIT_PCT = 95.0
QUOTA_OBSERVATION_MAX_AGE = 300.0
SPARK_MODEL = "gpt-5.3-codex-spark"
READINESS_POLICY = "worker-weekly-v1"
READINESS_WIRE_VERSION = 2
LEGACY_QUOTA_RECHECK_SECONDS = 60.0


@dataclass(frozen=True)
class QuotaDecision:
    state: str
    model: str
    provider: str
    provider_label: str
    weekly_utilization: float | None
    observed_at: float | None
    valid_until: float | None
    reset_at: str | None
    alternatives: tuple[dict[str, str], ...]
    reason: str

    @property
    def allowed(self) -> bool:
        return self.state in {"available", "not_applicable"}

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "model": self.model,
            "provider": self.provider,
            "provider_label": self.provider_label,
            "weekly_utilization": self.weekly_utilization,
            "threshold": WORKER_WEEKLY_LIMIT_PCT,
            "observed_at": self.observed_at,
            "valid_until": self.valid_until,
            "reset_at": self.reset_at,
            "alternatives": [dict(item) for item in self.alternatives],
            "reason": self.reason,
        }


def worker_readiness_envelope(
    decision: QuotaDecision,
    *,
    now: float | None = None,
) -> dict:
    """Serialize one decision for both strict and pre-v1 MCP clients.

    The old client only blocks ``state=reset`` with a parseable reset timestamp.
    Canonical fields stay separate so a compatibility retry timestamp can never
    masquerade as the provider's real reset or as a fresh observation.
    """
    checked_at = time.time() if now is None else float(now)
    canonical = decision.to_dict()
    decision_state = canonical.pop("state")
    decision_reset_at = canonical.pop("reset_at")
    legacy_allowed = decision_state in {"available", "not_applicable"}
    legacy_reset_at = None
    if not legacy_allowed:
        future_reset = _future_reset(decision_reset_at, checked_at)
        legacy_reset_at = (
            future_reset[1]
            if future_reset is not None
            else datetime.fromtimestamp(
                checked_at + LEGACY_QUOTA_RECHECK_SECONDS,
                timezone.utc,
            ).isoformat()
        )
    return {
        "policy": READINESS_POLICY,
        "wire_version": READINESS_WIRE_VERSION,
        **canonical,
        "decision_state": decision_state,
        "state": "available" if legacy_allowed else "reset",
        "decision_reset_at": decision_reset_at,
        "reset_at": legacy_reset_at,
    }


class QuotaGateError(RuntimeError):
    """Structured refusal for a new worker turn."""

    status_code = 429
    retryable = False

    def __init__(self, decision: QuotaDecision):
        if decision.state not in {"blocked", "unknown"}:
            raise ValueError(f"cannot refuse quota decision {decision.state!r}")
        self.decision = decision
        self.code = (
            "weekly_quota_blocked"
            if decision.state == "blocked"
            else "weekly_quota_unknown"
        )
        super().__init__(self._message())

    def _message(self) -> str:
        label = self.decision.provider_label or self.decision.provider or "provider"
        if self.decision.state == "blocked":
            cause = (
                f"{label} weekly quota is {self.decision.weekly_utilization:g}% "
                f"(new worker turns stop at {WORKER_WEEKLY_LIMIT_PCT:g}%)"
            )
        else:
            cause = f"{label} weekly quota status is unavailable or stale"
        if self.decision.alternatives:
            names = ", ".join(item["label"] for item in self.decision.alternatives)
            return f"New worker turn blocked: {cause}. Available provider: {names}."
        return f"New worker turn blocked: {cause}. Wait for quota telemetry or reset."

    def envelope(self) -> dict:
        details = self.decision.to_dict()
        return {
            "error": {
                "code": self.code,
                "message": str(self),
                "retryable": False,
                "details": details,
            }
        }


def _model_target(model: str) -> tuple[str, str | None, str]:
    if not isinstance(model, str):
        raise ValueError("model must be a string")
    resolved = resolve_model(model)
    runtime = backend_for_model(resolved)
    get_runtime(runtime)
    if runtime == "grok":
        return resolved, None, runtime
    if runtime == "claude":
        return resolved, "anthropic", runtime
    if runtime == "codex":
        return resolved, "codex_spark" if resolved == SPARK_MODEL else "codex", runtime
    raise ValueError(f"runtime '{runtime}' has no weekly worker quota policy")


def quota_bucket_for_model(model: str) -> str | None:
    """Return the exact quota bucket; only positively resolved Grok returns None."""
    _resolved, bucket, _runtime = _model_target(model)
    return bucket


def _timestamp(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        result = value.timestamp()
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        result = parsed.timestamp()
    else:
        return None
    return result if math.isfinite(result) and result > 0 else None


def _utilization(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    if not math.isfinite(result) or result < 0:
        return None
    return result


def _future_reset(value: object, now: float) -> tuple[float, str] | None:
    timestamp = _timestamp(value)
    if timestamp is None or timestamp <= now:
        return None
    if isinstance(value, str):
        rendered = value
    else:
        rendered = datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    return timestamp, rendered


def _weekly_status(
    provider: object,
    observed_at: object,
    now: float,
) -> tuple[str, float | None, float | None, str | None, str]:
    timestamp = _timestamp(observed_at)
    if timestamp is None:
        return "unknown", None, None, None, "weekly observation timestamp is missing or malformed"
    age = now - timestamp
    if age < 0:
        return "unknown", None, timestamp, None, "weekly observation timestamp is in the future"
    if age >= QUOTA_OBSERVATION_MAX_AGE:
        return "unknown", None, timestamp, None, "weekly observation is stale"
    if not isinstance(provider, Mapping):
        return "unknown", None, timestamp, None, "provider usage is missing"
    windows = provider.get("windows")
    if not isinstance(windows, list):
        return "unknown", None, timestamp, None, "weekly windows are missing"
    weekly = [
        item for item in windows
        if isinstance(item, Mapping) and item.get("window_minutes") == WEEKLY_WINDOW_MINUTES
    ]
    if not weekly:
        return "unknown", None, timestamp, None, "weekly window is missing"
    utilizations = [_utilization(item.get("utilization")) for item in weekly]
    if any(item is None for item in utilizations):
        return "unknown", None, timestamp, None, "weekly utilization is malformed"
    utilization = max(item for item in utilizations if item is not None)
    blocking_windows = [
        item for item, value in zip(weekly, utilizations)
        if value is not None and value >= WORKER_WEEKLY_LIMIT_PCT
    ]
    resets = [
        reset
        for reset in (
            _future_reset(item.get("resets_at"), now)
            for item in blocking_windows
        )
        if reset is not None
    ]
    reset_at = max(resets, default=None, key=lambda item: item[0])
    if utilization >= WORKER_WEEKLY_LIMIT_PCT:
        return "blocked", utilization, timestamp, reset_at[1] if reset_at else None, (
            f"weekly utilization {utilization:g}% is at or above "
            f"{WORKER_WEEKLY_LIMIT_PCT:g}%"
        )
    return "available", utilization, timestamp, None, (
        f"weekly utilization {utilization:g}% is below {WORKER_WEEKLY_LIMIT_PCT:g}%"
    )


def _alternatives(
    target: str,
    providers: Mapping[str, object],
    observed_at_by_provider: Mapping[str, object],
    now: float,
) -> tuple[dict[str, str], ...]:
    result = []
    for bucket in ("anthropic", "codex", "codex_spark"):
        if bucket == target:
            continue
        state, _usage, _observed, _reset, _reason = _weekly_status(
            providers.get(bucket), observed_at_by_provider.get(bucket), now,
        )
        if state == "available":
            data = providers.get(bucket)
            label = data.get("label") if isinstance(data, Mapping) else None
            result.append({"provider": bucket, "label": str(label or bucket)})
    return tuple(result)


def evaluate_worker_admission(
    model: str,
    providers: Mapping[str, object],
    observed_at_by_provider: Mapping[str, object],
    *,
    now: float | None = None,
) -> QuotaDecision:
    checked_at = time.time() if now is None else float(now)
    try:
        resolved, bucket, runtime = _model_target(model)
    except (TypeError, ValueError) as error:
        return QuotaDecision(
            state="unknown", model=str(model), provider="", provider_label="Unknown provider",
            weekly_utilization=None, observed_at=None, valid_until=None, reset_at=None,
            alternatives=(), reason=str(error),
        )
    if runtime == "grok" and bucket is None:
        return QuotaDecision(
            state="not_applicable", model=resolved, provider="grok", provider_label="Grok",
            weekly_utilization=None, observed_at=None, valid_until=None, reset_at=None,
            alternatives=(), reason="Grok is outside the subscription weekly quota policy",
        )
    provider = providers.get(bucket)
    observed_raw = observed_at_by_provider.get(bucket)
    state, utilization, observed_at, reset_at, reason = _weekly_status(
        provider, observed_raw, checked_at,
    )
    label = provider.get("label") if isinstance(provider, Mapping) else None
    alternatives = _alternatives(bucket, providers, observed_at_by_provider, checked_at)
    return QuotaDecision(
        state=state,
        model=resolved,
        provider=bucket,
        provider_label=str(label or bucket),
        weekly_utilization=utilization,
        observed_at=observed_at,
        valid_until=(observed_at + QUOTA_OBSERVATION_MAX_AGE) if observed_at is not None else None,
        reset_at=reset_at,
        alternatives=alternatives,
        reason=reason,
    )


ObservationLoader = Callable[..., Awaitable[Mapping[str, object]]]


async def get_worker_admission(
    model: str,
    observation_loader: ObservationLoader | None = None,
) -> QuotaDecision:
    try:
        bucket = quota_bucket_for_model(model)
    except (TypeError, ValueError):
        return evaluate_worker_admission(model, {}, {})
    if bucket is None:
        return evaluate_worker_admission(model, {}, {})
    if observation_loader is None:
        from app.routes.system import current_quota_observation

        observation_loader = current_quota_observation
    try:
        observation = await observation_loader(required_provider=bucket)
    except Exception as error:
        decision = evaluate_worker_admission(
            model,
            {bucket: {"label": bucket, "windows": []}},
            {},
        )
        return replace(
            decision,
            reason=f"quota observation failed: {type(error).__name__}: {error}",
        )
    providers = observation.get("providers")
    timestamps = observation.get("observed_at_by_provider")
    if not isinstance(providers, Mapping):
        providers = {}
    if not isinstance(timestamps, Mapping):
        timestamps = {}
    return evaluate_worker_admission(model, providers, timestamps)


def require_worker_admission(decision: QuotaDecision) -> None:
    if not decision.allowed:
        raise QuotaGateError(decision)
