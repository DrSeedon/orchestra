"""Admission policy for new subscription-backed worker turns."""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Awaitable, Callable, Mapping

from app.models import backend_for_model, resolve_model
from app.runtime_registry import get_runtime

logger = logging.getLogger(__name__)

WEEKLY_WINDOW_MINUTES = 10080
WORKER_WEEKLY_LIMIT_PCT = 95.0
LUNA_WORKER_WEEKLY_LIMIT_PCT = 98.0
# Абсолютный worker-стоп недельного пула Claude. ЗДЕСЬ живёт обоснование числа —
# в манифесте его больше нет (#329 вырезал оттуда всё про расход, чтобы у логики
# пулов остался один владелец):
#   последние 10 п.п. недели резервируются под ОРКЕСТРАТОРОВ и кеш. Упереться в
#   недельный лимит Claude больно — работать становится нечем, поэтому воркеры
#   останавливаются раньше, чем пул кончится. Оркестраторы этот гейт не проходят
#   вовсе (app/session.py:1207, :2032, :2248), то есть резерв достаётся им.
# Происхождение: политика #227 (там же был отменённый ныне гистерезис возврата 87%).
# Значение — только дефолт: действующий порог берётся из полосы `claude` таблицы
# `quota_controller_policy` и меняется оператором горячо.
CLAUDE_WORKER_WEEKLY_LIMIT_PCT = 90.0
# Совпадение с сидом БД (app/db.py QUOTA_POLICY_DEFAULTS) закреплено тестом.
LANE_DEFAULT_THRESHOLDS = {
    "sol": WORKER_WEEKLY_LIMIT_PCT,
    "luna": LUNA_WORKER_WEEKLY_LIMIT_PCT,
    "spark": WORKER_WEEKLY_LIMIT_PCT,
    "claude": CLAUDE_WORKER_WEEKLY_LIMIT_PCT,
}
QUOTA_OBSERVATION_MAX_AGE = 300.0
# Значения `QuotaDecision.binding_constraint` — что именно связало решение.
# `runway_deficit` НЕ является отказом: по нему полоса деградирует, а отказывает только
# процент (#314). Замер, стоящий за этим разделением, — `docs/tasks/314/research.md`.
BINDING_NONE = "none"
BINDING_STATIC_PCT = "static_pct"
BINDING_RUNWAY_DEFICIT = "runway_deficit"
BINDING_BLIND_NO_PACE = "blind_no_pace"
BINDING_RUNWAY_UNAVAILABLE = "runway_unavailable"
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
    threshold: float = WORKER_WEEKLY_LIMIT_PCT
    # Что именно связало решение. Отдельным полем, а не разбором `reason`: панель обязана
    # различать «отказал процент» и «закрыл дефицит», а свободный текст для этого негоден.
    # Значение ортогонально `state` — деградация по дефициту НЕ является отказом (#314).
    binding_constraint: str = BINDING_NONE
    # Измерение скользящего окна, если оно было доступно. Решения не несёт.
    runway: dict | None = None

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
            "threshold": self.threshold,
            "observed_at": self.observed_at,
            "valid_until": self.valid_until,
            "reset_at": self.reset_at,
            "alternatives": [dict(item) for item in self.alternatives],
            "reason": self.reason,
            "binding_constraint": self.binding_constraint,
            "runway": dict(self.runway) if self.runway else None,
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

    def __init__(self, decision: QuotaDecision, *, code: str | None = None):
        if decision.state not in {"blocked", "unknown"}:
            raise ValueError(f"cannot refuse quota decision {decision.state!r}")
        self.decision = decision
        self.code = code or (
            "weekly_quota_blocked"
            if decision.state == "blocked"
            else "weekly_quota_unknown"
        )
        super().__init__(self._message())

    def _message(self) -> str:
        label = self.decision.provider_label or self.decision.provider or "provider"
        if self.code == "adaptive_quota_hold":
            return (
                f"New worker turn held by adaptive quota controller: "
                f"{self.decision.reason or 'headroom policy'}"
            )
        if self.decision.state == "blocked":
            cause = (
                f"{label} weekly quota is {self.decision.weekly_utilization:g}% "
                f"(new worker turns stop at {self.decision.threshold:g}%)"
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


def parse_quota_timestamp(value: object) -> float | None:
    """Public name for the gate's own reset/observation timestamp parser."""
    return _timestamp(value)


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
    threshold: float = WORKER_WEEKLY_LIMIT_PCT,
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
        if value is not None and value >= threshold
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
    if utilization >= threshold:
        return "blocked", utilization, timestamp, reset_at[1] if reset_at else None, (
            f"weekly utilization {utilization:g}% is at or above "
            f"{threshold:g}%"
        )
    return "available", utilization, timestamp, None, (
        f"weekly utilization {utilization:g}% is below {threshold:g}%"
    )


def _alternatives(
    target: str,
    providers: Mapping[str, object],
    observed_at_by_provider: Mapping[str, object],
    now: float,
    policy: Mapping[str, object] | None = None,
) -> tuple[dict[str, str], ...]:
    result = []
    for bucket in ("anthropic", "codex", "codex_spark"):
        if bucket == target:
            continue
        # Полоса берётся по бакету: у codex это Sol, дефолтный worker-исполнитель.
        threshold = lane_threshold(policy, policy_lane_for_model("", bucket))
        state, _usage, _observed, _reset, _reason = _weekly_status(
            providers.get(bucket), observed_at_by_provider.get(bucket), now, threshold,
        )
        if state == "available":
            data = providers.get(bucket)
            label = data.get("label") if isinstance(data, Mapping) else None
            result.append({"provider": bucket, "label": str(label or bucket)})
    return tuple(result)


def policy_lane_for_model(resolved_model: str, bucket: str | None) -> str | None:
    """Map one resolved model to its operator policy lane (single owner)."""
    if bucket == "codex_spark":
        return "spark"
    if resolved_model == "gpt-5.6-luna":
        return "luna"
    if bucket == "codex":
        return "sol"
    if bucket in {"anthropic", "anthropic_fable"}:
        return "claude"
    return None


def lane_threshold(policy: Mapping[str, object] | None, lane: str | None) -> float:
    """Threshold in force for one lane: operator policy, else its default."""
    if lane is None:
        return WORKER_WEEKLY_LIMIT_PCT
    return _policy_threshold(
        policy, lane, LANE_DEFAULT_THRESHOLDS.get(lane, WORKER_WEEKLY_LIMIT_PCT),
    )


def _policy_threshold(
    policy: Mapping[str, object] | None,
    lane: str,
    fallback: float,
) -> float:
    if not isinstance(policy, Mapping):
        return fallback
    lanes = policy.get("lanes")
    item = lanes.get(lane) if isinstance(lanes, Mapping) else None
    value = item.get("threshold") if isinstance(item, Mapping) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    value = float(value)
    return value if math.isfinite(value) else fallback


def evaluate_worker_admission(
    model: str,
    providers: Mapping[str, object],
    observed_at_by_provider: Mapping[str, object],
    *,
    now: float | None = None,
    policy: Mapping[str, object] | None = None,
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
    threshold = lane_threshold(policy, policy_lane_for_model(resolved, bucket))
    state, utilization, observed_at, reset_at, reason = _weekly_status(
        provider, observed_raw, checked_at, threshold,
    )
    label = provider.get("label") if isinstance(provider, Mapping) else None
    alternatives = _alternatives(
        bucket, providers, observed_at_by_provider, checked_at, policy,
    )
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
        threshold=threshold,
        # Связывает только состоявшийся отказ по проценту. Все прочие состояния
        # (`available`, `unknown`, `not_applicable`) ничего не связывают.
        binding_constraint=BINDING_STATIC_PCT if state == "blocked" else BINDING_NONE,
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
    try:
        from app.db import quota_policy_snapshot

        policy = quota_policy_snapshot()
    except Exception:
        policy = None
    decision = evaluate_worker_admission(model, providers, timestamps, policy=policy)
    return _apply_runway_observation(decision, policy)


def current_runway_verdict(decision: QuotaDecision):
    """Измерение окна для полосы Claude: `(вердикт, набранные рабочие часы)` или None.

    Ничего не решает: сравнение с порогом делает `_apply_runway_observation`.
    """
    if decision.provider != "anthropic" or decision.weekly_utilization is None:
        return None
    from datetime import datetime, timezone

    from app.db import runway_window_start_pct
    from app.quota_runway import next_weekly_reset, weekly_runway, working_hours_between

    now = datetime.now(timezone.utc)
    reset_at = None
    if decision.reset_at:
        try:
            parsed = datetime.fromisoformat(decision.reset_at)
            reset_at = parsed if parsed > now else None
        except ValueError:
            reset_at = None
    if reset_at is None:
        reset_at = next_weekly_reset(now)
    baseline = runway_window_start_pct(reset_at)
    start_pct, start_at = baseline if baseline is not None else (None, None)
    if isinstance(start_at, str):
        start_at = datetime.fromisoformat(start_at)
    verdict = weekly_runway(
        utilization=decision.weekly_utilization,
        window_start_pct=start_pct,
        window_start_at=start_at,
        now=now,
        reset_at=reset_at,
    )
    # `work_used` из вердикта не выводится — в нём его нет, а восстановить его из
    # `runway_hours * pace` невозможно: это тождество, дающее обратно `runway_hours`.
    # Поэтому считаем здесь, где ещё видна база окна.
    work_used = (
        working_hours_between(start_at, now) if start_at is not None else None
    )
    return verdict, work_used


def current_runway_deficit(decision: QuotaDecision, observed=None) -> float | None:
    """Число, по которому принимается решение о деградации.

    Единственный seam, через который тест подменяет решающую величину, не подделывая всю
    историю `usage_snapshots`. Поэтому он обязан быть самодостаточным: если вердикт не
    передан, функция добывает его сама.
    """
    if observed is None:
        observed = current_runway_verdict(decision)
    verdict = observed[0] if isinstance(observed, tuple) else observed
    return None if verdict is None else verdict.deficit


def _apply_runway_observation(
    decision: QuotaDecision,
    policy: Mapping[str, object] | None,
) -> QuotaDecision:
    """Наблюдение скользящего окна: НАБЛЮДЕНИЕ, а не действие.

    Проставляет `binding_constraint` и блок `runway`, пишет строку журнала — и НИЧЕГО
    не меняет в `state`. Отказ остаётся исключительно за процентом: порог дефицита не
    откалиброван (правая половина матрицы ошибок пуста, `docs/tasks/314/research.md` §5.2),
    поэтому действовать по нему сейчас нельзя, а собирать наблюдения — нужно.
    """
    lane = policy_lane_for_model(decision.model, decision.provider)
    if lane != "claude" or decision.binding_constraint == BINDING_STATIC_PCT:
        return decision
    lanes = policy.get("lanes") if isinstance(policy, Mapping) else None
    item = lanes.get(lane) if isinstance(lanes, Mapping) else None
    deficit_limit = item.get("deficit_hours") if isinstance(item, Mapping) else None
    if not isinstance(deficit_limit, (int, float)) or isinstance(deficit_limit, bool):
        # Оператор не задал порог — механизм выключен, и это законное состояние.
        return decision
    min_work_hours = item.get("min_work_hours") if isinstance(item, Mapping) else None
    if not isinstance(min_work_hours, (int, float)) or isinstance(min_work_hours, bool):
        min_work_hours = 0.0

    # Деталь для панели — best-effort: её отсутствие не должно менять РЕШЕНИЕ.
    try:
        observed = current_runway_verdict(decision)
    except Exception as error:
        logger.warning("runway observation failed: %s: %s", type(error).__name__, error)
        observed = None
    verdict, work_used = observed if observed is not None else (None, None)

    deficit = current_runway_deficit(decision, observed)
    if deficit is None:
        # Различаем «окно ещё не созрело» и «измерить нечем»: оператору это разные строки.
        binding = BINDING_BLIND_NO_PACE if verdict is not None else BINDING_RUNWAY_UNAVAILABLE
    elif work_used is not None and work_used < float(min_work_hours):
        binding = BINDING_BLIND_NO_PACE
    elif deficit > float(deficit_limit):
        binding = BINDING_RUNWAY_DEFICIT
    else:
        binding = BINDING_NONE

    runway = {
        "deficit": deficit,
        "pace": getattr(verdict, "pace", None),
        "runway_hours": getattr(verdict, "runway_hours", None),
        "work_hours_left": getattr(verdict, "work_hours_left", None),
        "work_used": work_used,
        "window_id": getattr(verdict, "window_id", None),
        "threshold": float(deficit_limit),
        "min_work_hours": float(min_work_hours),
        "static_threshold": decision.threshold,
        "utilization": decision.weekly_utilization,
        "blind_until": _runway_blind_until(work_used, float(min_work_hours)),
    }
    _log_runway_decision(runway, binding, item)
    return replace(decision, binding_constraint=binding, runway=runway)


def _runway_blind_until(work_used: float | None, min_work_hours: float) -> str | None:
    """Момент, когда гейт по дефициту сможет впервые высказаться.

    Показывать обязательно: без него тишина гейта читается оператором как «всё хорошо»,
    то есть проверка даёт одинаковый вывод при успехе и при провале.
    """
    if min_work_hours <= 0:
        return None
    if work_used is not None and work_used >= min_work_hours:
        return None
    from datetime import datetime, timezone

    from app.quota_runway import moment_after_working_hours

    missing = min_work_hours - (work_used or 0.0)
    moment = moment_after_working_hours(datetime.now(timezone.utc), missing)
    return moment.isoformat() if moment is not None else None


def _log_runway_decision(runway: dict, binding: str, policy_item: object) -> None:
    """Журнал не имеет права уронить допуск: учёт побочен, результат — нет."""
    try:
        from app.db import record_runway_decision

        revision = policy_item.get("revision") if isinstance(policy_item, Mapping) else None
        record_runway_decision(
            window_id=str(runway.get("window_id") or ""),
            binding_constraint=binding,
            deficit=runway.get("deficit"),
            pace=runway.get("pace"),
            work_used=runway.get("work_used"),
            work_hours_left=runway.get("work_hours_left"),
            utilization=runway.get("utilization"),
            threshold=runway.get("threshold"),
            threshold_revision=int(revision) if isinstance(revision, int) else None,
            outcome="observed_shadow",
        )
    except Exception as error:
        logger.warning(
            "runway decision log failed: %s: %s", type(error).__name__, error,
        )


def require_worker_admission(decision: QuotaDecision) -> None:
    if not decision.allowed:
        raise QuotaGateError(decision)
