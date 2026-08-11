"""Deterministic server-owned runtime selection from fresh quota telemetry."""

from __future__ import annotations

import asyncio
import json
import math
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import AsyncIterator, Awaitable, Callable, Literal, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import get_model_spec, resolve_model
from app.quota_runway import RunwayVerdict, as_utc, next_weekly_reset, weekly_runway


ROUTING_CONTRACT_VERSION = "routing-v1"
ROUTING_POLICY_SCHEMA_VERSION = 1
QUOTA_OBSERVATION_MAX_AGE_SECONDS = 300.0
FIVE_HOUR_WINDOW_MINUTES = 300
WEEKLY_WINDOW_MINUTES = 10080

TaskClass = Literal[
    "worker_general",
    "orchestrator_free_text",
    "review",
    "continuation",
]
CandidateState = Literal["normal", "reserve_only", "unavailable", "excluded"]
PROCESS_STARTED_AT = datetime.now(timezone.utc).isoformat()


class _StrictPolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RoutingModelsV1(_StrictPolicyModel):
    claude: str
    codex: str | None = None

    @model_validator(mode="after")
    def validate_runtimes(self) -> "RoutingModelsV1":
        claude = resolve_model(self.claude)
        if get_model_spec(claude).runtime != "claude":
            raise ValueError("models.claude must resolve to the Claude runtime")
        object.__setattr__(self, "claude", claude)
        if self.codex is not None:
            codex = resolve_model(self.codex)
            if get_model_spec(codex).runtime != "codex":
                raise ValueError("models.codex must resolve to the Codex runtime")
            if codex == "gpt-5.3-codex-spark":
                raise ValueError("Spark is not eligible for quota routing")
            object.__setattr__(self, "codex", codex)
        return self


class ClaudeQuotaPolicyV1(_StrictPolicyModel):
    alert_deficit_hours: float = Field(ge=0, le=100)
    weekly_unavailable_pct: float = Field(ge=0, le=100)
    weekly_min_remaining_pp: float = Field(ge=0, le=100)
    five_hour_unavailable_pct: float = Field(ge=0, le=100)

    @field_validator("*", mode="before")
    @classmethod
    def validate_number(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("quota threshold must be numeric")
        if not math.isfinite(float(value)):
            raise ValueError("quota threshold must be finite")
        return value


class CodexQuotaPolicyV1(_StrictPolicyModel):
    normal_below_pct: float = Field(ge=0, le=100)
    unavailable_at_pct: float = Field(ge=0, le=100)

    @field_validator("*", mode="before")
    @classmethod
    def validate_number(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("quota threshold must be numeric")
        if not math.isfinite(float(value)):
            raise ValueError("quota threshold must be finite")
        return value

    @model_validator(mode="after")
    def validate_order(self) -> "CodexQuotaPolicyV1":
        if self.normal_below_pct >= self.unavailable_at_pct:
            raise ValueError("codex.normal_below_pct must be below unavailable_at_pct")
        return self


class RoutingPolicyV1(_StrictPolicyModel):
    schema_version: Literal[1]
    revision: int = Field(ge=0)
    mode: Literal["manifest_default", "quota"]
    codex_access: Literal["all", "review_only", "off"] = "all"
    models: RoutingModelsV1 | None = None
    claude: ClaudeQuotaPolicyV1 | None = None
    codex: CodexQuotaPolicyV1 | None = None

    @field_validator("schema_version", "revision", mode="before")
    @classmethod
    def validate_integer(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("schema_version and revision must be integers")
        return value

    @model_validator(mode="after")
    def validate_activation(self) -> "RoutingPolicyV1":
        if self.mode == "manifest_default":
            return self
        if self.models is None or self.claude is None:
            raise ValueError("quota mode requires models and claude thresholds")
        if self.codex_access != "off" and (
            self.models.codex is None or self.codex is None
        ):
            raise ValueError(
                "quota mode with Codex access requires models.codex and codex thresholds"
            )
        return self

    @classmethod
    def manifest_default(cls, revision: int = 0) -> "RoutingPolicyV1":
        return cls(
            schema_version=ROUTING_POLICY_SCHEMA_VERSION,
            revision=revision,
            mode="manifest_default",
        )


@dataclass(frozen=True)
class RoutingInput:
    task_class: TaskClass
    logical_work_id: str = ""
    manifest_model: str | None = None
    current_model: str | None = None
    review_default_model: str | None = None
    requesting_runtime: str | None = None
    implementation_runtimes: frozenset[str] = frozenset()
    reserve_reason: Literal["continuation", "emergency"] | None = None

    def __post_init__(self) -> None:
        if self.task_class not in {
            "worker_general",
            "orchestrator_free_text",
            "review",
            "continuation",
        }:
            raise ValueError(f"unknown server-owned task class {self.task_class!r}")
        if any(runtime not in {"claude", "codex"} for runtime in self.implementation_runtimes):
            raise ValueError("implementation_runtimes contains an unsupported runtime")
        if self.requesting_runtime not in {None, "claude", "codex"}:
            raise ValueError(f"unsupported requesting runtime {self.requesting_runtime!r}")
        if self.reserve_reason not in {None, "continuation", "emergency"}:
            raise ValueError(f"unknown reserve reason {self.reserve_reason!r}")


@dataclass(frozen=True)
class CandidateVerdict:
    runtime: str
    model: str
    state: CandidateState
    reason: str
    utilization: float | None = None
    observed_at: float | None = None
    reset_at: str | None = None
    window_id: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class RoutingDecision:
    policy_revision: int
    policy_mode: str
    task_class: str
    state: Literal["selected", "queued"]
    selected_runtime: str | None
    selected_model: str | None
    reason: str
    candidates: tuple[CandidateVerdict, ...]
    latch_window_ids: tuple[str, ...] = ()
    degraded_review_independence: str | None = None
    best_effort_threshold: bool = False

    def to_dict(self) -> dict:
        result = asdict(self)
        result["candidates"] = [asdict(item) for item in self.candidates]
        result["latch_window_ids"] = list(self.latch_window_ids)
        return result


@dataclass(frozen=True)
class RoutingAdmission:
    decision_id: str
    request: RoutingInput
    decision: RoutingDecision

    def to_dict(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "request": _request_dict(self.request),
            "decision": self.decision.to_dict(),
        }


class RoutingStore(Protocol):
    def policy_document(self) -> str | None: ...

    def replace_policy_document(
        self,
        *,
        expected_revision: int,
        document: str,
    ) -> None: ...

    def latched_window_ids(self, provider: str) -> frozenset[str]: ...

    def commit_decision(
        self,
        *,
        expected_policy_revision: int,
        decision_id: str,
        created_at: str,
        process_started_at: str,
        policy_mode: str,
        task_class: str,
        logical_work_id: str,
        request_json: str,
        decision_json: str,
        latch_window_ids: tuple[str, ...],
    ) -> None: ...

    def last_decision(self) -> dict | None: ...

    def latches(self) -> list[dict]: ...


ObservationLoader = Callable[..., Awaitable[Mapping[str, object]]]
BaselineLoader = Callable[[datetime], tuple[float, str] | None]


class PolicyRevisionError(RuntimeError):
    pass


class DatabaseRoutingStore:
    """Narrow adapter over the DB-owned routing transaction helpers."""

    def policy_document(self) -> str | None:
        from app.db import routing_policy_document

        return routing_policy_document()

    def replace_policy_document(self, **kwargs) -> None:
        from app.db import replace_routing_policy_document

        replace_routing_policy_document(**kwargs)

    def latched_window_ids(self, provider: str) -> frozenset[str]:
        from app.db import routing_latched_window_ids

        return routing_latched_window_ids(provider)

    def commit_decision(self, **kwargs) -> None:
        from app.db import commit_runtime_routing_decision

        commit_runtime_routing_decision(**kwargs)

    def last_decision(self) -> dict | None:
        from app.db import routing_last_decision

        return routing_last_decision()

    def latches(self) -> list[dict]:
        from app.db import routing_latches

        return routing_latches()


class RuntimeRouter:
    """Serialize policy changes with durable admission decisions."""

    def __init__(
        self,
        *,
        store: RoutingStore,
        observation_loader: ObservationLoader,
        baseline_loader: BaselineLoader,
        process_started_at: str = PROCESS_STARTED_AT,
    ) -> None:
        self._store = store
        self._observation_loader = observation_loader
        self._baseline_loader = baseline_loader
        self._process_started_at = process_started_at
        self._policy_lock = asyncio.Lock()

    def policy(self) -> RoutingPolicyV1:
        raw = self._store.policy_document()
        if raw is None:
            return RoutingPolicyV1.manifest_default()
        return RoutingPolicyV1.model_validate_json(raw)

    async def replace_policy(self, payload: Mapping[str, object]) -> RoutingPolicyV1:
        candidate = RoutingPolicyV1.model_validate(payload)
        async with self._policy_lock:
            current = self.policy()
            if candidate.revision != current.revision + 1:
                raise PolicyRevisionError(
                    f"policy revision must be {current.revision + 1}, got {candidate.revision}"
                )
            self._store.replace_policy_document(
                expected_revision=current.revision,
                document=candidate.model_dump_json(exclude_none=True),
            )
        return candidate

    async def status(self) -> dict:
        policy = self.policy()
        return {
            "contract_version": ROUTING_CONTRACT_VERSION,
            "process_started_at": self._process_started_at,
            "policy": policy.model_dump(mode="json", exclude_none=True),
            "latches": self._store.latches(),
            "last_decision": self._store.last_decision(),
        }

    async def explain(
        self,
        request: RoutingInput,
        observation: Mapping[str, object] | None,
        *,
        claude_baseline: tuple[float, datetime] | None = None,
        latched_window_ids: frozenset[str] = frozenset(),
        terminal_limited_runtimes: frozenset[str] = frozenset(),
        now: datetime | None = None,
    ) -> RoutingDecision:
        async with self._policy_lock:
            return evaluate_routing(
                self.policy(),
                request,
                observation,
                claude_baseline=claude_baseline,
                latched_window_ids=latched_window_ids,
                terminal_limited_runtimes=terminal_limited_runtimes,
                now=now,
            )

    @asynccontextmanager
    async def admission(self, request: RoutingInput) -> AsyncIterator[RoutingAdmission]:
        """Hold the policy lock until the caller durably queues or submits work."""
        async with self._policy_lock:
            policy = self.policy()
            now = datetime.now(timezone.utc)
            observation = await self._load_observation(policy, request)
            baseline = self._load_baseline(policy, observation, now)
            latches = self._store.latched_window_ids("anthropic")
            decision = evaluate_routing(
                policy,
                request,
                observation,
                claude_baseline=baseline,
                latched_window_ids=latches,
                now=now,
            )
            decision_id = str(uuid.uuid4())
            created_at = now.isoformat()
            self._store.commit_decision(
                expected_policy_revision=policy.revision,
                decision_id=decision_id,
                created_at=created_at,
                process_started_at=self._process_started_at,
                policy_mode=policy.mode,
                task_class=request.task_class,
                logical_work_id=request.logical_work_id,
                request_json=json.dumps(_request_dict(request), sort_keys=True),
                decision_json=json.dumps(decision.to_dict(), sort_keys=True),
                latch_window_ids=decision.latch_window_ids,
            )
            yield RoutingAdmission(decision_id, request, decision)

    async def _load_observation(
        self,
        policy: RoutingPolicyV1,
        request: RoutingInput,
    ) -> dict:
        if policy.mode == "manifest_default":
            return {}
        providers: dict[str, object] = {}
        timestamps: dict[str, object] = {}
        required = ["anthropic"]
        if policy.codex_access == "all" or (
            policy.codex_access == "review_only" and request.task_class == "review"
        ):
            required.append("codex")
        for provider_id in required:
            snapshot = await self._observation_loader(required_provider=provider_id)
            snapshot_providers, snapshot_timestamps = _observation_parts(snapshot)
            if provider_id in snapshot_providers:
                providers[provider_id] = snapshot_providers[provider_id]
            if provider_id in snapshot_timestamps:
                timestamps[provider_id] = snapshot_timestamps[provider_id]
        return {
            "providers": providers,
            "observed_at_by_provider": timestamps,
        }

    def _load_baseline(
        self,
        policy: RoutingPolicyV1,
        observation: Mapping[str, object],
        now: datetime,
    ) -> tuple[float, datetime] | None:
        if policy.mode == "manifest_default":
            return None
        providers, _timestamps = _observation_parts(observation)
        weekly, error = _quota_window(providers.get("anthropic"), WEEKLY_WINDOW_MINUTES)
        if error or weekly is None:
            return None
        reset_at = _future_datetime(weekly.get("resets_at"), now) or next_weekly_reset(now)
        baseline = self._baseline_loader(reset_at)
        if baseline is None:
            return None
        pct, timestamp = baseline
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return pct, as_utc(parsed, "runway baseline timestamp")


_runtime_router: RuntimeRouter | None = None


def get_runtime_router() -> RuntimeRouter:
    global _runtime_router
    if _runtime_router is None:
        from app.db import runway_window_start_pct
        from app.routes.system import current_quota_observation

        _runtime_router = RuntimeRouter(
            store=DatabaseRoutingStore(),
            observation_loader=current_quota_observation,
            baseline_loader=runway_window_start_pct,
        )
    return _runtime_router


def routing_input_from_dict(payload: object) -> RoutingInput:
    if not isinstance(payload, Mapping):
        raise ValueError("request must be an object")
    allowed = {
        "task_class",
        "logical_work_id",
        "manifest_model",
        "current_model",
        "review_default_model",
        "requesting_runtime",
        "implementation_runtimes",
        "reserve_reason",
    }
    extra = set(payload) - allowed
    if extra:
        raise ValueError(f"unknown request fields: {', '.join(sorted(extra))}")
    values = dict(payload)
    values["implementation_runtimes"] = _string_set(
        values.get("implementation_runtimes"),
        "implementation_runtimes",
    )
    return RoutingInput(**values)


def explain_inputs_from_dict(payload: object) -> tuple[
    RoutingInput,
    Mapping[str, object],
    tuple[float, datetime] | None,
    frozenset[str],
    frozenset[str],
    datetime | None,
]:
    if not isinstance(payload, Mapping):
        raise ValueError("explain payload must be an object")
    allowed = {
        "request",
        "observation",
        "claude_baseline",
        "latched_window_ids",
        "terminal_limited_runtimes",
        "now",
    }
    extra = set(payload) - allowed
    if extra:
        raise ValueError(f"unknown explain fields: {', '.join(sorted(extra))}")
    request = routing_input_from_dict(payload.get("request"))
    observation = payload.get("observation")
    if not isinstance(observation, Mapping):
        raise ValueError("observation must be an object")
    baseline = _baseline_from_dict(payload.get("claude_baseline"))
    latches = _string_set(payload.get("latched_window_ids"), "latched_window_ids")
    terminal = _string_set(
        payload.get("terminal_limited_runtimes"),
        "terminal_limited_runtimes",
    )
    if any(runtime not in {"claude", "codex"} for runtime in terminal):
        raise ValueError("terminal_limited_runtimes contains an unsupported runtime")
    now = _iso_datetime(payload.get("now"), "now") if payload.get("now") else None
    return request, observation, baseline, latches, terminal, now


def evaluate_routing(
    policy: RoutingPolicyV1,
    request: RoutingInput,
    observation: Mapping[str, object] | None = None,
    *,
    claude_baseline: tuple[float, datetime] | None = None,
    latched_window_ids: frozenset[str] = frozenset(),
    terminal_limited_runtimes: frozenset[str] = frozenset(),
    now: datetime | None = None,
) -> RoutingDecision:
    """Evaluate one decision without IO or mutation."""
    if policy.mode == "manifest_default":
        return _manifest_decision(policy, request)

    assert policy.models is not None and policy.claude is not None
    checked_at = _utc_now(now)
    providers, observed_at = _observation_parts(observation)
    candidates: dict[str, CandidateVerdict] = {
        "claude": _claude_candidate(
            policy,
            providers.get("anthropic"),
            observed_at.get("anthropic"),
            claude_baseline,
            latched_window_ids,
            "claude" in terminal_limited_runtimes,
            checked_at,
        )
    }

    codex_allowed = policy.codex_access == "all" or (
        policy.codex_access == "review_only" and request.task_class == "review"
    )
    if codex_allowed:
        candidates["codex"] = _codex_candidate(
            policy,
            providers.get("codex"),
            observed_at.get("codex"),
            "codex" in terminal_limited_runtimes,
            checked_at,
        )
    else:
        candidates["codex"] = CandidateVerdict(
            runtime="codex",
            model=policy.models.codex or "",
            state="excluded",
            reason=f"codex_access={policy.codex_access} excludes {request.task_class}",
        )

    ordered = tuple(candidates[runtime] for runtime in ("codex", "claude"))
    chosen, degraded = _choose_candidate(request, candidates)
    latches = tuple(
        candidate.window_id
        for candidate in ordered
        if candidate.runtime == "claude"
        and candidate.state == "reserve_only"
        and candidate.window_id is not None
        and candidate.window_id not in latched_window_ids
    )
    if chosen is None:
        return RoutingDecision(
            policy_revision=policy.revision,
            policy_mode=policy.mode,
            task_class=request.task_class,
            state="queued",
            selected_runtime=None,
            selected_model=None,
            reason="no quota-eligible runtime",
            candidates=ordered,
            latch_window_ids=latches,
            degraded_review_independence=degraded,
            best_effort_threshold=codex_allowed,
        )
    return RoutingDecision(
        policy_revision=policy.revision,
        policy_mode=policy.mode,
        task_class=request.task_class,
        state="selected",
        selected_runtime=chosen.runtime,
        selected_model=chosen.model,
        reason=f"selected {chosen.runtime}: {chosen.reason}",
        candidates=ordered,
        latch_window_ids=latches,
        degraded_review_independence=degraded,
        best_effort_threshold=codex_allowed,
    )


def _manifest_decision(
    policy: RoutingPolicyV1,
    request: RoutingInput,
) -> RoutingDecision:
    if request.task_class == "worker_general":
        model = request.manifest_model
        source = "role manifest"
        selectable = True
    elif request.task_class == "review":
        model = request.review_default_model
        source = "review default"
        selectable = True
    else:
        model = request.current_model
        source = "current session"
        selectable = False
    if not model:
        raise ValueError(f"manifest_default requires {source} model for {request.task_class}")
    resolved = resolve_model(model) if selectable else get_model_spec(model).id
    runtime = get_model_spec(resolved).runtime
    candidate = CandidateVerdict(
        runtime=runtime,
        model=resolved,
        state="normal",
        reason=f"manifest_default keeps {source}",
    )
    return RoutingDecision(
        policy_revision=policy.revision,
        policy_mode=policy.mode,
        task_class=request.task_class,
        state="selected",
        selected_runtime=runtime,
        selected_model=resolved,
        reason=candidate.reason,
        candidates=(candidate,),
    )


def _choose_candidate(
    request: RoutingInput,
    candidates: Mapping[str, CandidateVerdict],
) -> tuple[CandidateVerdict | None, str | None]:
    if request.task_class == "continuation" and request.current_model:
        current = get_model_spec(request.current_model).runtime
        candidate = candidates.get(current)
        if candidate and candidate.state in {"normal", "reserve_only"}:
            return candidate, None

    usable_states = {"normal"}
    if request.reserve_reason == "emergency":
        usable_states.add("reserve_only")
    usable = [
        candidates[runtime]
        for runtime in ("codex", "claude")
        if candidates[runtime].state in usable_states
    ]
    if request.task_class != "review":
        return (usable[0], None) if usable else (None, None)

    if not request.implementation_runtimes:
        return (usable[0], "unknown") if usable else (None, "unknown")

    independent = [
        candidate
        for candidate in usable
        if candidate.runtime not in request.implementation_runtimes
    ]
    if independent:
        return independent[0], None
    if not usable:
        return None, None
    if len(request.implementation_runtimes) > 1:
        degraded = "mixed"
    else:
        degraded = "same_runtime"
    return usable[0], degraded


def _claude_candidate(
    policy: RoutingPolicyV1,
    provider: object,
    observed_at: object,
    baseline: tuple[float, datetime] | None,
    latched_window_ids: frozenset[str],
    terminal_limited: bool,
    now: datetime,
) -> CandidateVerdict:
    assert policy.models is not None and policy.claude is not None
    model = policy.models.claude
    if terminal_limited:
        return CandidateVerdict("claude", model, "unavailable", "claude_terminal_limit")
    fresh, timestamp, reason = _fresh_provider(provider, observed_at, now)
    if not fresh:
        return CandidateVerdict("claude", model, "unavailable", reason, observed_at=timestamp)
    five, error = _quota_window(provider, FIVE_HOUR_WINDOW_MINUTES)
    if error:
        return CandidateVerdict("claude", model, "unavailable", f"claude_five_hour_{error}", observed_at=timestamp)
    weekly, error = _quota_window(provider, WEEKLY_WINDOW_MINUTES)
    if error:
        return CandidateVerdict("claude", model, "unavailable", f"claude_weekly_{error}", observed_at=timestamp)
    assert five is not None and weekly is not None
    five_reset = _future_datetime(five.get("resets_at"), now)
    if five_reset is None:
        return CandidateVerdict(
            "claude", model, "unavailable", "claude_five_hour_reset_missing",
            utilization=weekly["utilization"], observed_at=timestamp,
        )
    weekly_pct = weekly["utilization"]
    weekly_reset = _future_datetime(weekly.get("resets_at"), now)
    reset_at = weekly_reset.isoformat() if weekly_reset is not None else None
    if weekly_pct >= policy.claude.weekly_unavailable_pct:
        return CandidateVerdict(
            "claude", model, "unavailable", "claude_weekly_hard_stop",
            weekly_pct, timestamp, reset_at,
        )
    if 100.0 - weekly_pct < policy.claude.weekly_min_remaining_pp:
        return CandidateVerdict(
            "claude", model, "unavailable", "claude_weekly_remaining_below_minimum",
            weekly_pct, timestamp, reset_at,
        )
    if five["utilization"] >= policy.claude.five_hour_unavailable_pct:
        return CandidateVerdict(
            "claude", model, "unavailable", "claude_five_hour_hard_stop",
            weekly_pct, timestamp, reset_at,
        )

    start_pct, start_at = baseline if baseline is not None else (None, None)
    runway = weekly_runway(
        utilization=weekly_pct,
        window_start_pct=start_pct,
        window_start_at=start_at,
        now=now,
        reset_at=weekly_reset,
    )
    if runway.state == "no_data":
        return _claude_runway_verdict(
            model,
            "unavailable",
            runway,
            weekly_pct,
            timestamp,
            "claude_weekly_runway_no_data",
        )
    if runway.window_id in latched_window_ids:
        return _claude_runway_verdict(model, "reserve_only", runway, weekly_pct, timestamp, "claude_weekly_latched")
    if runway.deficit is not None and runway.deficit > policy.claude.alert_deficit_hours:
        return _claude_runway_verdict(model, "reserve_only", runway, weekly_pct, timestamp, "claude_weekly_deficit")
    return _claude_runway_verdict(model, "normal", runway, weekly_pct, timestamp, "claude_quota_normal")


def _claude_runway_verdict(
    model: str,
    state: CandidateState,
    runway: RunwayVerdict,
    utilization: float,
    observed_at: float | None,
    reason: str | None = None,
) -> CandidateVerdict:
    return CandidateVerdict(
        runtime="claude",
        model=model,
        state=state,
        reason=reason or f"claude_runway_{runway.reason}",
        utilization=utilization,
        observed_at=observed_at,
        reset_at=runway.window_end,
        window_id=runway.window_id,
        detail=runway.reason,
    )


def _codex_candidate(
    policy: RoutingPolicyV1,
    provider: object,
    observed_at: object,
    terminal_limited: bool,
    now: datetime,
) -> CandidateVerdict:
    assert policy.models is not None and policy.models.codex is not None and policy.codex is not None
    model = policy.models.codex
    if terminal_limited:
        return CandidateVerdict("codex", model, "unavailable", "codex_terminal_limit")
    fresh, timestamp, reason = _fresh_provider(provider, observed_at, now)
    if not fresh:
        return CandidateVerdict("codex", model, "unavailable", reason, observed_at=timestamp)
    weekly, error = _quota_window(provider, WEEKLY_WINDOW_MINUTES)
    if error:
        return CandidateVerdict("codex", model, "unavailable", f"codex_weekly_{error}", observed_at=timestamp)
    assert weekly is not None
    utilization = weekly["utilization"]
    reset = _future_datetime(weekly.get("resets_at"), now)
    reset_at = reset.isoformat() if reset is not None else None
    if utilization >= policy.codex.unavailable_at_pct:
        state: CandidateState = "unavailable"
        reason = "codex_weekly_hard_stop"
    elif utilization >= policy.codex.normal_below_pct:
        state = "reserve_only"
        reason = "codex_weekly_reserve"
    else:
        state = "normal"
        reason = "codex_quota_normal"
    return CandidateVerdict(
        "codex", model, state, reason, utilization, timestamp, reset_at,
    )


def _observation_parts(
    observation: Mapping[str, object] | None,
) -> tuple[Mapping[str, object], Mapping[str, object]]:
    if not isinstance(observation, Mapping):
        return {}, {}
    providers = observation.get("providers")
    timestamps = observation.get("observed_at_by_provider")
    return (
        providers if isinstance(providers, Mapping) else {},
        timestamps if isinstance(timestamps, Mapping) else {},
    )


def _fresh_provider(
    provider: object,
    observed_at: object,
    now: datetime,
) -> tuple[bool, float | None, str]:
    timestamp = _finite_number(observed_at)
    if timestamp is None:
        return False, None, "quota_observation_timestamp_missing"
    age = now.timestamp() - timestamp
    if age < 0:
        return False, timestamp, "quota_observation_timestamp_future"
    if age >= QUOTA_OBSERVATION_MAX_AGE_SECONDS:
        return False, timestamp, "quota_observation_stale"
    if not isinstance(provider, Mapping):
        return False, timestamp, "quota_provider_missing"
    return True, timestamp, ""


def _quota_window(
    provider: object,
    minutes: int,
) -> tuple[dict[str, object] | None, str | None]:
    if not isinstance(provider, Mapping) or not isinstance(provider.get("windows"), list):
        return None, "window_missing"
    matches: list[dict[str, object]] = []
    for raw in provider["windows"]:
        if not isinstance(raw, Mapping) or raw.get("window_minutes") != minutes:
            continue
        utilization = _finite_number(raw.get("utilization"))
        if utilization is None or not 0 <= utilization <= 100:
            return None, "utilization_malformed"
        item = dict(raw)
        item["utilization"] = utilization
        matches.append(item)
    if not matches:
        return None, "window_missing"
    return max(matches, key=lambda item: float(item["utilization"])), None


def _future_datetime(value: object, now: datetime) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        parsed = as_utc(parsed, "reset_at")
    except ValueError:
        return None
    return parsed if parsed > now else None


def _baseline_from_dict(value: object) -> tuple[float, datetime] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"pct", "ts"}:
        raise ValueError("claude_baseline must contain exactly pct and ts")
    pct = _finite_number(value["pct"])
    if pct is None or not 0 <= pct <= 100:
        raise ValueError("claude_baseline.pct must be a finite percentage")
    return pct, _iso_datetime(value["ts"], "claude_baseline.ts")


def _string_set(value: object, name: str) -> frozenset[str]:
    if value is None:
        return frozenset()
    if not isinstance(value, (list, tuple, set, frozenset)) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ValueError(f"{name} must be a list of non-empty strings")
    return frozenset(value)


def _iso_datetime(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{name} must be an ISO datetime") from error
    return as_utc(parsed, name)


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _utc_now(value: datetime | None) -> datetime:
    result = value or datetime.now(timezone.utc)
    return as_utc(result, "now")


def _request_dict(request: RoutingInput) -> dict:
    result = asdict(request)
    result["implementation_runtimes"] = sorted(request.implementation_runtimes)
    return result
