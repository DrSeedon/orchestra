"""Единственное правило допуска воркеров по квоте пула (#343).

Для пула считаются две величины в процентах:

* **норма** — доля окна, прошедшая по времени: 0% в начале окна, 100% в момент сброса;
* **допуск** — линейно ``TOLERANCE_START_PP`` п.п. в начале окна → ``TOLERANCE_END_PP``
  п.п. в момент сброса.

Гейтящиеся полосы (Sol и Claude-воркеры) блокируются, когда расход ушёл выше суммы
нормы и допуска; поверх этого на всех воркеров действуют жёсткие ``HARD_STOP_PCT``.
Luna и Spark диагональ не проходят вовсе — они дешёвые, их единственный стоп жёсткий.
Оркестраторы гейт не проходят никогда: это свойство ВЫЗЫВАЮЩЕГО, и здесь его нет —
`is_orchestrator` проверяется в `app/session.py` и `app/manager.py` до вызова гейта.

Правило смотрит ТОЛЬКО на текущую точку и истории не помнит: обнуление счётчика оно
переживает само, потому что после сброса и расход, и доля окна начинаются заново.

Неизвестная квота ПРОПУСКАЕТ. Это сквозное решение, а не послабление одного вызова:
отказ на `unknown` при спавне создавал сессию, которую следующий обязательный `/send`
отбивал 429 — мёртвую (#227).
"""

from __future__ import annotations

import math
import time
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Awaitable, Callable, Mapping

from app.models import backend_for_model, resolve_model
from app.runtime_registry import get_runtime


def _env_float_var(name: str, default: float, *, minimum: float, maximum: float) -> float:
    if name not in os.environ:
        return default
    raw = os.environ[name].strip()
    if not raw:
        raise ValueError(f"{name}: value must be a finite number in [{minimum}, {maximum}]")
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{name}: value must be a finite number in [{minimum}, {maximum}], got {raw!r}") from error
    if not math.isfinite(value) or not (minimum <= value <= maximum):
        raise ValueError(f"{name}: value must be in [{minimum}, {maximum}], got {raw!r}")
    return value


def _env_gated_lanes(name: str, default: tuple[str, ...]) -> frozenset[str]:
    if name not in os.environ:
        return frozenset(default)
    raw = os.environ[name]
    if raw == "":
        return frozenset()
    raw_parts = [part.strip() for part in raw.split(",")]
    if any(part == "" for part in raw_parts):
        raise ValueError(f"{name}: empty lane name in {raw!r}")
    return frozenset(part.lower() for part in raw_parts)

_ENV_TOLERANCE_START_DEFAULT = 10.0
_ENV_TOLERANCE_END_DEFAULT = 1.0
_ENV_HARD_STOP_DEFAULT = 99.0
_ENV_GATED_LANES_DEFAULT = ("claude", "sol")

# Жёсткий стоп для ВСЕХ воркеров в обоих пулах, поверх диагонали.
HARD_STOP_PCT = _env_float_var(
    "QUOTA_HARD_STOP_PCT", _ENV_HARD_STOP_DEFAULT, minimum=1.0, maximum=100.0,
)
# Допуск: линейная интерполяция от начала окна к моменту сброса.
TOLERANCE_START_PP = _env_float_var(
    "QUOTA_TOLERANCE_START_PP", _ENV_TOLERANCE_START_DEFAULT, minimum=0.0, maximum=100.0,
)
TOLERANCE_END_PP = _env_float_var(
    "QUOTA_TOLERANCE_END_PP", _ENV_TOLERANCE_END_DEFAULT, minimum=0.0, maximum=100.0,
)
# Наблюдение старше этого возраста считается отсутствующим.
QUOTA_OBSERVATION_MAX_AGE = 300.0

WEEKLY_WINDOW_MINUTES = 10080
SPARK_MODEL = "gpt-5.3-codex-spark"
LUNA_MODEL = "gpt-5.6-luna"

# Полосы, которым диагональ применяется. Всё, чего здесь нет, ограничено только
# жёстким стопом.
GATED_LANES = _env_gated_lanes("QUOTA_GATED_LANES", _ENV_GATED_LANES_DEFAULT)

LANE_LABELS = {
    "claude": "Claude-воркеры",
    "sol": "Sol",
    "luna": "Luna",
    "spark": "Spark",
}


def tolerance_pp(progress: float) -> float:
    """Допуск в п.п. в точке окна."""
    return TOLERANCE_START_PP + (TOLERANCE_END_PP - TOLERANCE_START_PP) * progress


def line_limit(progress: float) -> float:
    """Порог гейтящейся полосы: диагональ + допуск, но никогда выше жёсткого стопа."""
    return min(HARD_STOP_PCT, progress * 100.0 + tolerance_pp(progress))


def line_release_progress(utilization: float) -> float:
    """Доля окна, где линия достигает `utilization`."""
    line_denominator = 100.0 + TOLERANCE_END_PP - TOLERANCE_START_PP
    if line_denominator == 0:
        return float("inf")
    return (utilization - TOLERANCE_START_PP) / line_denominator


def _line_release_in_seconds(
    utilization: float,
    progress: float | None,
    gated: bool,
    hard_stop_pct: float,
    window_minutes: float | None,
    reset_at: float | None,
    *,
    now: float,
) -> tuple[str, float | None]:
    """Возвращает статус открытия и секунды до открытия/сброса окна.

    - open: уже открыто или не гейтингуется;
    - opens_in: откроется до конца окна;
    - at_reset: откроется только после сброса окна;
    - no_data: нельзя посчитать.
    """
    if utilization >= hard_stop_pct:
        if reset_at is None:
            return "at_reset", 0.0
        return "at_reset", max(0.0, reset_at - now)

    if not gated:
        return "open", None
    if not gated_window_open(progress, window_minutes):
        return "no_data", None

    p_release = line_release_progress(utilization)
    if p_release <= progress:
        return "open", None
    if p_release <= 1.0:
        return "opens_in", (p_release - progress) * window_minutes * 60.0
    if reset_at is None:
        return "at_reset", None
    return "at_reset", max(0.0, reset_at - now)


def gated_window_open(progress: float | None, window_minutes: float | None) -> bool:
    """Есть ли параметры окна для вычисления времени до открытия полосы."""
    return (
        progress is not None
        and window_minutes is not None
        and progress >= 0
        and window_minutes > 0
    )


@dataclass(frozen=True)
class QuotaDecision:
    state: str
    model: str
    provider: str
    provider_label: str
    lane: str | None
    gated: bool
    utilization: float | None
    progress: float | None
    tolerance_pp: float | None
    limit_pct: float | None
    observed_at: float | None
    valid_until: float | None
    reset_at: str | None
    window_starts_at: str | None
    reason: str
    hard_limit_pct: float = HARD_STOP_PCT
    release_status: str = "open"
    release_in_seconds: float | None = None

    @property
    def allowed(self) -> bool:
        return self.state != "blocked"

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "allowed": self.allowed,
            "model": self.model,
            "provider": self.provider,
            "provider_label": self.provider_label,
            "lane": self.lane,
            "gated": self.gated,
            "utilization": self.utilization,
            "progress": self.progress,
            "tolerance_pp": self.tolerance_pp,
            "limit_pct": self.limit_pct,
            "hard_limit_pct": self.hard_limit_pct,
            "observed_at": self.observed_at,
            "valid_until": self.valid_until,
            "reset_at": self.reset_at,
            "window_starts_at": self.window_starts_at,
            "reason": self.reason,
            "release_status": self.release_status,
            "release_in_seconds": self.release_in_seconds,
        }


class QuotaGateError(RuntimeError):
    """Структурированный отказ новому ходу воркера."""

    status_code = 429
    retryable = False
    code = "weekly_quota_blocked"

    def __init__(self, decision: QuotaDecision):
        if decision.state != "blocked":
            raise ValueError(f"cannot refuse quota decision {decision.state!r}")
        self.decision = decision
        super().__init__(
            f"New worker turn blocked: {decision.provider_label} quota is "
            f"{decision.utilization:g}% — {decision.reason}."
        )

    def envelope(self) -> dict:
        return {
            "error": {
                "code": self.code,
                "message": str(self),
                "retryable": False,
                "details": self.decision.to_dict(),
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
    raise ValueError(f"runtime '{runtime}' has no worker quota policy")


def quota_bucket_for_model(model: str) -> str | None:
    """Точный бакет квоты; None отдаёт только положительно опознанный Grok."""
    _resolved, bucket, _runtime = _model_target(model)
    return bucket


def lane_for_model(resolved_model: str, bucket: str | None) -> str | None:
    """Полоса одной модели — единственный владелец этого отображения."""
    if bucket == "codex_spark":
        return "spark"
    if resolved_model == LUNA_MODEL:
        return "luna"
    if bucket == "codex":
        return "sol"
    if bucket in {"anthropic", "anthropic_fable"}:
        return "claude"
    return None


def parse_quota_timestamp(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        result = value.timestamp()
    elif isinstance(value, str):
        trimmed = value.strip()
        if not trimmed:
            return None
        try:
            result = float(trimmed)
        except ValueError:
            parsed = None
        else:
            return result if math.isfinite(result) and result > 0 else None
        try:
            parsed = datetime.fromisoformat(trimmed.replace("Z", "+00:00"))
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


def deciding_window(provider: object, bucket: str) -> Mapping | None:
    """Окно, по которому принимается решение для бакета.

    Решает НЕДЕЛЬНОЕ окно — оно длиннее и упирается первым; пятичасовое остаётся
    справочным. Выбор идёт по `window_minutes`, а НЕ по имени поля: 19.08.2026 OpenAI
    переставил Spark с одного окна (`primary` = 7d) на два (`primary` = 5h,
    `secondary` = 7d), и выбор по имени показал 0% при выжранном на 100% недельном —
    гейт пропускал воркеров в мёртвый пул (#360). Имена принадлежат провайдеру,
    длина принадлежит смыслу.

    У Claude недельное окно обязательно: его отсутствие — «данных нет», подставлять
    пятичасовое нельзя. У пулов Codex состав окон задаёт провайдер, поэтому берём
    самое ДЛИННОЕ из присланных — оно и упирается первым.
    """
    if not isinstance(provider, Mapping):
        return None
    windows = provider.get("windows")
    if not isinstance(windows, list):
        return None
    candidates = [item for item in windows if isinstance(item, Mapping)]

    def _length(item: Mapping) -> float:
        value = item.get("window_minutes")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return float(value)
        return 0.0

    if bucket in {"anthropic", "anthropic_fable"}:
        for item in candidates:
            if item.get("window_minutes") == WEEKLY_WINDOW_MINUTES:
                return item
        return None
    sized = [item for item in candidates if _length(item) > 0]
    return max(sized, key=_length) if sized else None


def window_progress(window: Mapping, now: float) -> tuple[float | None, str | None]:
    """Доля пройденного окна и его начало в ISO.

    Начало окна = `resets_at − window_minutes`: у Claude это фиксированный вторник,
    у Codex — скользящее окно, и одна формула покрывает оба случая.
    """
    reset_at = parse_quota_timestamp(window.get("resets_at"))
    minutes = window.get("window_minutes")
    if reset_at is None or isinstance(minutes, bool):
        return None, None
    if not isinstance(minutes, (int, float)) or minutes <= 0:
        return None, None
    span = float(minutes) * 60.0
    start = reset_at - span
    started_at = datetime.fromtimestamp(start, timezone.utc).isoformat()
    # Зажим намеренный: окно, чей сброс уже прошёл, пройдено целиком — и правило
    # вырождается в жёсткий стоп, потому что `line_limit(1.0)` равен ему.
    return min(1.0, max(0.0, (now - start) / span)), started_at


def evaluate_worker_admission(
    model: str,
    providers: Mapping[str, object],
    observed_at_by_provider: Mapping[str, object],
    *,
    now: float | None = None,
) -> QuotaDecision:
    checked_at = time.time() if now is None else float(now)

    def unknown(
        reason: str,
        *,
        resolved: str = "",
        bucket: str = "",
        label: str = "",
        lane: str | None = None,
        observed_at: float | None = None,
        utilization: float | None = None,
    ) -> QuotaDecision:
        return QuotaDecision(
            state="unknown", model=resolved or str(model), provider=bucket,
            provider_label=label or bucket or "Unknown provider",
            lane=lane, gated=lane in GATED_LANES,
            utilization=utilization, progress=None, tolerance_pp=None, limit_pct=None,
            release_status="no_data", release_in_seconds=None,
            observed_at=observed_at, valid_until=None, reset_at=None,
            window_starts_at=None, reason=reason,
        )

    try:
        resolved, bucket, runtime = _model_target(model)
    except (TypeError, ValueError) as error:
        return unknown(str(error))
    if runtime == "grok" and bucket is None:
        return QuotaDecision(
            state="not_applicable", model=resolved, provider="grok", provider_label="Grok",
            lane=None, gated=False, utilization=None, progress=None,
            tolerance_pp=None, limit_pct=None, observed_at=None, valid_until=None,
            reset_at=None, window_starts_at=None, release_status="not_applicable",
            release_in_seconds=None,
            reason="Grok is outside the subscription quota policy",
        )

    lane = lane_for_model(resolved, bucket)
    gated = lane in GATED_LANES
    provider = providers.get(bucket)
    label = provider.get("label") if isinstance(provider, Mapping) else None
    label = str(label or bucket)

    observed_at = parse_quota_timestamp(observed_at_by_provider.get(bucket))
    if observed_at is None:
        return unknown("observation timestamp is missing or malformed",
                       resolved=resolved, bucket=bucket, label=label, lane=lane)
    age = checked_at - observed_at
    if age < 0:
        return unknown("observation timestamp is in the future", resolved=resolved,
                       bucket=bucket, label=label, lane=lane, observed_at=observed_at)
    if age >= QUOTA_OBSERVATION_MAX_AGE:
        return unknown("observation is stale", resolved=resolved, bucket=bucket,
                       label=label, lane=lane, observed_at=observed_at)

    window = deciding_window(provider, bucket)
    if window is None:
        return unknown("deciding window is missing", resolved=resolved, bucket=bucket,
                       label=label, lane=lane, observed_at=observed_at)
    utilization = _utilization(window.get("utilization"))
    if utilization is None:
        return unknown("utilization is missing or malformed", resolved=resolved,
                       bucket=bucket, label=label, lane=lane, observed_at=observed_at)

    progress, started_at = window_progress(window, checked_at)
    reset_at = parse_quota_timestamp(window.get("resets_at"))
    reset_at_str = str(window.get("resets_at")) if reset_at else None
    window_minutes = window.get("window_minutes")
    window_minutes = (
        float(window_minutes)
        if isinstance(window_minutes, (int, float)) and not isinstance(window_minutes, bool) and window_minutes > 0
        else None
    )
    tolerance = None if progress is None else tolerance_pp(progress)
    limit = None if (progress is None or not gated) else line_limit(progress)
    release_status, release_in_seconds = _line_release_in_seconds(
        utilization=utilization,
        progress=progress,
        gated=gated,
        hard_stop_pct=HARD_STOP_PCT,
        window_minutes=window_minutes,
        reset_at=reset_at,
        now=checked_at,
    )

    if utilization >= HARD_STOP_PCT:
        state = "blocked"
        reason = (
            f"utilization {utilization:g}% is at or above the hard stop "
            f"{HARD_STOP_PCT:g}%"
        )
    elif limit is not None and utilization > limit:
        state = "blocked"
        reason = (
            f"utilization {utilization:g}% is above the line limit {limit:.4g}% "
            f"(norm {progress * 100:.4g}% + tolerance {tolerance:.4g} pp)"
        )
    elif gated and limit is None:
        state = "available"
        reason = (
            f"utilization {utilization:g}% is below the hard stop {HARD_STOP_PCT:g}%; "
            "the window has no parseable reset, so the line is not applied"
        )
    elif gated:
        state = "available"
        reason = f"utilization {utilization:g}% is at or below the line limit {limit:.4g}%"
    else:
        state = "available"
        reason = (
            f"lane '{lane}' is not gated by the line; utilization {utilization:g}% "
            f"is below the hard stop {HARD_STOP_PCT:g}%"
        )

    return QuotaDecision(
        state=state, model=resolved, provider=bucket, provider_label=label,
        lane=lane, gated=gated, utilization=utilization, progress=progress,
        tolerance_pp=tolerance, limit_pct=limit, observed_at=observed_at,
        valid_until=observed_at + QUOTA_OBSERVATION_MAX_AGE,
        reset_at=reset_at_str, window_starts_at=started_at, reason=reason,
        release_status=release_status, release_in_seconds=release_in_seconds,
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
        return replace(
            evaluate_worker_admission(model, {}, {}),
            reason=f"quota observation failed: {type(error).__name__}: {error}",
        )
    providers = observation.get("providers")
    timestamps = observation.get("observed_at_by_provider")
    return evaluate_worker_admission(
        model,
        providers if isinstance(providers, Mapping) else {},
        timestamps if isinstance(timestamps, Mapping) else {},
    )


def require_worker_admission(decision: QuotaDecision) -> None:
    """Отказать только состоявшемуся блоку. `unknown` пропускает — см. модуль."""
    if decision.state == "blocked":
        raise QuotaGateError(decision)
