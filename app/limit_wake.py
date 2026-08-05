"""Schedule and execute subscription-limit wake-ups."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

from app.db import (
    _conn,
    bg_finish_trigger,
    bg_get_active_all,
    bg_claim_trigger,
    bg_update_config,
    get_all_sessions,
)
from app.models import backend_for_model
from app.session import _subscription_limit_kind
from app.session_state import AgentStatus

logger = logging.getLogger(__name__)

WAKE_ACTION = "wake_subscription_limited"
WAKE_JOB_PREFIX = "wake-limit-"
WAKE_STAGGER_SECONDS = 30
MANUAL_ACTION_URL = "https://claude.ai/settings/usage"
WAKE_MESSAGE_PREFIX = "[system wake:"
ANTHROPIC_BASE_WINDOWS = ("five_hour", "seven_day")
WAKE_AUTO_DEBOUNCE_SECONDS = 60
_schedule_lock = asyncio.Lock()
_last_auto_schedule: datetime | None = None


def _provider_for_model(model: str) -> str:
    if backend_for_model(model) == "claude":
        return "anthropic"
    if model == "gpt-5.3-codex-spark":
        return "codex_spark"
    return "codex"


def _latest_limit_turn(logs: list[dict]) -> tuple[str, int] | None:
    use_timestamps = all(row.get("ts") for row in logs)
    key = (
        (lambda row: (row["ts"], row["id"]))
        if use_timestamps
        else (lambda row: row["id"])
    )
    ordered = sorted(logs, key=key)
    turn_ends = [
        row for row in ordered
        if row["type"] == "status" and row["content"].startswith("turn ended")
    ]
    if not turn_ends:
        return None
    latest = turn_ends[-1]
    latest_key = key(latest)
    if any(
        key(row) > latest_key
        and row["type"] == "user_message"
        and not row["content"].startswith(WAKE_MESSAGE_PREFIX)
        for row in ordered
    ):
        return None
    if "stop_sequence" not in latest["content"]:
        return None
    previous_key = key(turn_ends[-2]) if len(turn_ends) > 1 else None
    turn_logs = [
        row for row in ordered
        if (previous_key is None or key(row) > previous_key)
        and key(row) <= latest_key
        and row["type"] in {"text", "error", "status"}
    ]
    terminal_marker = any(
        row["type"] in {"error", "status"}
        and "subscription limit — ждём сброса квоты" in row["content"].lower()
        for row in turn_logs
    )
    if not terminal_marker:
        return None
    monthly = any(
        _subscription_limit_kind(row["content"]) == "monthly"
        for row in turn_logs
    )
    return ("monthly" if monthly else "timed", latest["id"])


def find_limit_stopped_agents(
    sessions: list[dict],
    logs_by_session: dict[str, list[dict]],
) -> list[dict]:
    """Return idle agents whose most recent completed turn hit a subscription limit."""
    result = []
    for session in sessions:
        if session.get("status") in {"running", "starting", "archived"}:
            continue
        limit = _latest_limit_turn(logs_by_session.get(session["id"], []))
        if not limit:
            continue
        kind, turn_id = limit
        result.append({
            **session,
            "limit_kind": kind,
            "provider": _provider_for_model(session["model"]),
            "limit_turn_id": turn_id,
        })
    return result


def _parse_reset(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def provider_readiness(
    provider_envelope: dict,
    provider: str,
    *,
    now: datetime | None = None,
) -> dict:
    """Return the single capacity decision used by planning and delivery."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not provider_envelope.get("fresh"):
        return {
            "state": "unavailable",
            "reason": provider_envelope.get("error")
            or "fresh provider usage unavailable",
        }

    usage = provider_envelope.get("usage")
    if not isinstance(usage, dict):
        return {"state": "unavailable", "reason": "provider usage missing"}
    windows = usage.get("windows")
    if not isinstance(windows, list):
        return {"state": "unavailable", "reason": "usage windows missing"}

    if provider == "anthropic":
        by_id = {
            window.get("id"): window
            for window in windows
            if isinstance(window, dict)
        }
        required = []
        for window_id in ANTHROPIC_BASE_WINDOWS:
            window = by_id.get(window_id)
            if not isinstance(window, dict) or not isinstance(
                window.get("utilization"), (int, float)
            ):
                return {
                    "state": "unavailable",
                    "reason": f"required {window_id} usage is incomplete",
                }
            required.append(window)

        exhausted = [
            window for window in required if window["utilization"] >= 100
        ]
        if not exhausted:
            return {"state": "available", "reason": "base capacity is open"}

        resets = [_parse_reset(window.get("resets_at")) for window in exhausted]
        if any(reset is None or reset <= now for reset in resets):
            return {
                "state": "manual",
                "reason": "base capacity has no timed reset",
            }
        return {
            "state": "reset",
            "reason": "base capacity is exhausted",
            "reset_at": max(resets).isoformat(),
        }

    observed = [
        window
        for window in windows
        if isinstance(window, dict)
        and isinstance(window.get("utilization"), (int, float))
    ]
    if not observed:
        return {
            "state": "unavailable",
            "reason": "provider usage windows are incomplete",
        }
    exhausted = [
        window for window in observed if window["utilization"] >= 100
    ]
    if not exhausted:
        return {"state": "available", "reason": "provider capacity is open"}
    resets = [
        reset
        for reset in (
            _parse_reset(window.get("resets_at")) for window in exhausted
        )
        if reset is not None and reset > now
    ]
    if not resets:
        return {
            "state": "unavailable",
            "reason": "exhausted windows have no future reset",
        }
    return {
        "state": "reset",
        "reason": "provider capacity is exhausted",
        "reset_at": max(resets).isoformat(),
    }


def build_wake_plan(
    agents: list[dict],
    provider_envelopes: dict,
    *,
    now: datetime | None = None,
) -> dict:
    """Classify every stopped agent from current provider capacity."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    schedules = []
    manual = []
    unavailable = []
    for provider in sorted({agent["provider"] for agent in agents}):
        provider_agents = sorted(
            (agent for agent in agents if agent["provider"] == provider),
            key=lambda agent: agent["name"],
        )
        readiness = provider_readiness(
            provider_envelopes.get(provider) or {
                "fresh": False,
                "usage": None,
                "error": "fresh provider usage unavailable",
            },
            provider,
            now=now,
        )
        agent_targets = [
            {
                "id": agent["id"],
                "name": agent["name"],
                "scope": agent["scope"],
                "limit_turn_id": agent["limit_turn_id"],
            }
            for agent in provider_agents
        ]
        names = [agent["name"] for agent in provider_agents]
        if readiness["state"] in {"available", "reset"}:
            schedules.append({
                "provider": provider,
                "reason": (
                    "available_now"
                    if readiness["state"] == "available"
                    else "base_reset"
                ),
                "reset_at": readiness.get("reset_at"),
                "agents": agent_targets,
            })
        elif readiness["state"] == "manual":
            manual.append({
                "provider": provider,
                "reason": readiness["reason"],
                "agents": names,
                "manual_action_url": (
                    MANUAL_ACTION_URL if provider == "anthropic" else None
                ),
            })
        else:
            unavailable.append({
                "provider": provider,
                "reason": readiness["reason"],
                "agents": names,
            })

    manual_agents = sorted(
        name for group in manual for name in group["agents"]
    )
    unavailable_agents = sorted(
        name for group in unavailable for name in group["agents"]
    )
    return {
        "schedules": schedules,
        "manual": manual,
        "unavailable": unavailable,
        "warnings": [],
        "manual_agents": manual_agents,
        "manual_action_url": MANUAL_ACTION_URL if manual_agents else None,
        "unavailable_agents": unavailable_agents,
    }


def _load_limit_stopped_agents() -> list[dict]:
    sessions = get_all_sessions()
    logs_by_session: dict[str, list[dict]] = {}
    with _conn() as connection:
        rows = connection.execute(
            """
            WITH ranked_ends AS (
                SELECT session_id, id, ts,
                    ROW_NUMBER() OVER (
                        PARTITION BY session_id ORDER BY ts DESC, id DESC
                    ) AS rank
                FROM logs
                WHERE type='status' AND content LIKE 'turn ended%'
            ),
            bounds AS (
                SELECT session_id,
                    MAX(CASE WHEN rank=2 THEN ts END) AS previous_ts
                FROM ranked_ends
                WHERE rank <= 2
                GROUP BY session_id
            )
            SELECT logs.session_id, logs.id, logs.ts, logs.type, logs.content
            FROM logs
            JOIN bounds ON bounds.session_id=logs.session_id
            WHERE bounds.previous_ts IS NULL OR logs.ts > bounds.previous_ts
            ORDER BY logs.session_id, logs.ts, logs.id
            """
        ).fetchall()
        for row in rows:
            item = dict(row)
            logs_by_session.setdefault(item.pop("session_id"), []).append(item)
    return find_limit_stopped_agents(sessions, logs_by_session)


def _active_wake_jobs() -> list[dict]:
    result = []
    for job in bg_get_active_all():
        try:
            config = json.loads(job["config"])
        except (json.JSONDecodeError, TypeError):
            continue
        if config.get("action") == WAKE_ACTION:
            result.append({**job, "config": config})
    return result


def wake_status() -> dict:
    agents = _load_limit_stopped_agents()
    jobs = _active_wake_jobs()
    monthly = sorted(
        agent["name"] for agent in agents if agent["limit_kind"] == "monthly"
    )
    scheduled = []
    for job in jobs:
        config = job["config"]
        targets = config.get("agents") or []
        scheduled.append({
            "provider": config.get("provider"),
            "reason": config.get("reason") or "base_reset",
            "reset_at": job.get("trigger_at"),
            "agents": [target.get("name") for target in targets if target.get("name")],
            "agent_count": len(targets),
            "preserved": False,
        })
    return {
        "candidate_count": len(agents),
        "monthly_agents": monthly,
        "manual_action_url": MANUAL_ACTION_URL if monthly else None,
        "scheduled": scheduled,
        "manual": [],
        "unavailable": [],
        "warnings": [],
    }


async def schedule_wake_auto() -> None:
    """Debounced automatic entry point used when a turn ends on a subscription limit.

    The manual dashboard button calls schedule_wake_after_reset directly and is never
    debounced — a human clicked it deliberately.
    """
    global _last_auto_schedule
    now = datetime.now(timezone.utc)
    if (
        _last_auto_schedule is not None
        and (now - _last_auto_schedule).total_seconds() < WAKE_AUTO_DEBOUNCE_SECONDS
    ):
        return
    # Stamped BEFORE the await: a burst of limited agents lands in one event-loop
    # tick, and stamping afterwards would let every one of them through into its
    # own force_refresh of provider usage.
    _last_auto_schedule = now
    try:
        await schedule_wake_after_reset()
    except Exception as error:
        # Waking is best-effort and must never break the turn that triggered it.
        logger.warning(
            "automatic wake scheduling failed: %s: %s",
            type(error).__name__,
            error,
        )


async def schedule_wake_after_reset() -> dict:
    """Freshly classify candidates and atomically replace provider wake timers."""
    from app.bg_jobs import bg_manager
    from app.routes.system import current_provider_usage

    async with _schedule_lock:
        agents = _load_limit_stopped_agents()
        existing_jobs = _active_wake_jobs()
        existing_by_provider = {
            job["config"].get("provider"): job
            for job in existing_jobs
            if job["config"].get("provider")
        }
        providers = sorted({agent["provider"] for agent in agents})
        envelopes = {}
        for provider in providers:
            try:
                snapshot = await current_provider_usage(
                    provider=provider,
                    force_refresh=True,
                )
                provider_usage = snapshot.get(provider)
                if not isinstance(provider_usage, dict):
                    raise ValueError(
                        f"fresh {provider} usage payload is missing"
                    )
            except Exception as error:
                logger.warning("wake usage refresh failed for %s: %s", provider, error)
                envelopes[provider] = {
                    "fresh": False,
                    "usage": None,
                    "error": str(error) or type(error).__name__,
                }
            else:
                envelopes[provider] = {
                    "fresh": True,
                    "usage": provider_usage,
                    "error": None,
                }

        now = datetime.now(timezone.utc)
        plan = build_wake_plan(agents, envelopes, now=now)
        scheduled = []
        planned_providers = set()
        for schedule in plan["schedules"]:
            provider = schedule["provider"]
            planned_providers.add(provider)
            reset = _parse_reset(schedule.get("reset_at"))
            delay = (
                0.1
                if schedule["reason"] == "available_now"
                else max(0.1, (reset - now).total_seconds())
            )
            result = await bg_manager.create(
                "timer",
                {
                    "delay_seconds": delay,
                    "action": WAKE_ACTION,
                    "provider": provider,
                    "reason": schedule["reason"],
                    "reset_at": schedule.get("reset_at"),
                    "agents": schedule["agents"],
                },
                "",
                "__system__",
                "__system__",
                "__global__",
                "dashboard",
                replace_key=f"{WAKE_JOB_PREFIX}{provider}",
            )
            if result.get("error"):
                raise RuntimeError(result["error"])
            scheduled.append({
                "provider": provider,
                "reason": schedule["reason"],
                "reset_at": schedule.get("reset_at"),
                "agents": [agent["name"] for agent in schedule["agents"]],
                "preserved": False,
            })

        unavailable = [
            {**group, "agents": list(group["agents"])}
            for group in plan["unavailable"]
        ]
        warnings = list(plan["warnings"])
        failed_providers = {
            provider
            for provider, envelope in envelopes.items()
            if not envelope["fresh"]
        }
        active_after_refresh = {}
        if failed_providers:
            active_after_refresh = {
                job["id"]: job for job in _active_wake_jobs()
            }
        for provider in failed_providers:
            old_job = existing_by_provider.get(provider)
            if not old_job or old_job["id"] not in active_after_refresh:
                continue
            old_job = active_after_refresh[old_job["id"]]
            old_targets = old_job["config"].get("agents") or []
            old_pairs = {
                (target.get("id"), target.get("limit_turn_id"))
                for target in old_targets
            }
            current_targets = [
                agent for agent in agents if agent["provider"] == provider
            ]
            covered = [
                agent["name"]
                for agent in current_targets
                if (agent["id"], agent["limit_turn_id"]) in old_pairs
            ]
            uncovered = [
                agent["name"]
                for agent in current_targets
                if (agent["id"], agent["limit_turn_id"]) not in old_pairs
            ]
            for group in list(unavailable):
                if group["provider"] != provider:
                    continue
                group["agents"] = uncovered
                if not uncovered:
                    unavailable.remove(group)
                break
            scheduled.append({
                "provider": provider,
                "reason": old_job["config"].get("reason") or "base_reset",
                "reset_at": old_job.get("trigger_at"),
                "agents": covered,
                "stored_agents": [
                    target.get("name")
                    for target in old_targets
                    if target.get("name")
                ],
                "preserved": True,
            })
            if uncovered:
                warnings.append({
                    "provider": provider,
                    "reason": (
                        "usage refresh failed; existing timer does not cover "
                        "the current limited turn"
                    ),
                    "agents": uncovered,
                })

        for job in existing_jobs:
            provider = job["config"].get("provider")
            if provider in failed_providers:
                continue
            if provider not in planned_providers:
                await bg_manager.cancel(job["id"])

        manual_agents = sorted(
            name for group in plan["manual"] for name in group["agents"]
        )
        unavailable_agents = sorted(
            name for group in unavailable for name in group["agents"]
        )
        decision = {
            "candidate_count": len(agents),
            "scheduled_count": len(scheduled),
            "scheduled": scheduled,
            "manual": plan["manual"],
            "unavailable": unavailable,
            "warnings": warnings,
            "manual_agents": manual_agents,
            "manual_action_url": MANUAL_ACTION_URL if manual_agents else None,
            "unavailable_agents": unavailable_agents,
        }
        decision["state"] = wake_status()
        return decision


def _wake_token_seen(session_id: str, token: str) -> bool:
    with _conn() as connection:
        row = connection.execute(
            "SELECT 1 FROM logs WHERE session_id=? AND type='user_message' "
            "AND content LIKE ? LIMIT 1",
            (session_id, f"{WAKE_MESSAGE_PREFIX}{token}]%"),
        ).fetchone()
    return row is not None


def _persist_deliveries(
    job_id: str,
    config: dict,
    deliveries: dict,
    output: str,
) -> None:
    config["deliveries"] = deliveries
    if not bg_update_config(job_id, config, output):
        raise RuntimeError("wake job is no longer triggering")


async def run_wake_job(
    job_id: str,
    config: dict,
    session_manager,
    *,
    stagger_seconds: float = WAKE_STAGGER_SECONDS,
) -> None:
    """Wake a persisted cohort, stopping immediately if capacity closes again."""
    if not bg_claim_trigger(job_id):
        return
    provider = config["provider"]
    target_turns = {
        agent["id"]: agent["limit_turn_id"]
        for agent in config.get("agents") or []
    }
    deliveries = config.setdefault("deliveries", {})
    sent = [
        agent_id
        for agent_id, delivery in deliveries.items()
        if delivery.get("state") == "delivered"
    ]
    outcome = ""
    try:
        targets = config.get("agents") or []
        for index, target in enumerate(targets):
            from app.routes.system import current_provider_usage

            try:
                provider_usage = await current_provider_usage(
                    provider=provider,
                    force_refresh=True,
                )
                provider_snapshot = provider_usage.get(provider)
            except Exception as error:
                readiness = provider_readiness(
                    {
                        "fresh": False,
                        "usage": None,
                        "error": str(error) or type(error).__name__,
                    },
                    provider,
                )
            else:
                readiness = provider_readiness(
                    {
                        "fresh": True,
                        "usage": provider_snapshot,
                        "error": None,
                    },
                    provider,
                )
            if readiness["state"] != "available":
                outcome = f"stopped: {provider}: {readiness['reason']}"
                break

            current = {
                agent["id"]: agent for agent in _load_limit_stopped_agents()
            }
            for awakened_id in sent:
                agent = current.get(awakened_id)
                if (
                    agent
                    and agent["provider"] == provider
                    and agent["limit_turn_id"] > target_turns[awakened_id]
                ):
                    outcome = f"stopped: {agent['name']} hit the limit again"
                    break
            if outcome:
                break

            target_id = target["id"]
            delivery = deliveries.get(target_id) or {}
            if delivery.get("state") == "delivered":
                continue
            if delivery.get("state") == "claimed":
                if _wake_token_seen(target_id, delivery["token"]):
                    delivery["state"] = "delivered"
                    if target_id not in sent:
                        sent.append(target_id)
                    _persist_deliveries(
                        job_id,
                        config,
                        deliveries,
                        f"woke {len(sent)} agents",
                    )
                    continue
                deliveries.pop(target_id, None)

            agent = current.get(target["id"])
            if not agent or agent["limit_turn_id"] != target["limit_turn_id"]:
                continue
            session = await session_manager.ensure_loaded(
                target["name"], target["scope"]
            )
            if not session or session.status == AgentStatus.RUNNING:
                continue
            token = uuid4().hex
            deliveries[target_id] = {"state": "claimed", "token": token}
            _persist_deliveries(
                job_id,
                config,
                deliveries,
                f"claiming {target['name']}",
            )
            message = (
                f"{WAKE_MESSAGE_PREFIX}{token}] Лимит подписки сброшен. "
                "Продолжай с того места, где остановился."
            )
            try:
                await session_manager.send(session.id, message)
            except Exception as delivery_error:
                # Непроснувшийся воркер — это остановленная работа, а не косметика (#30).
                # Запись в состоянии джоба остаётся, но у неё появляется адресат.
                from app.notify import report_undelivered

                outcome = await report_undelivered(
                    session_manager,
                    scope=target["scope"],
                    worker=target["name"],
                    what="пробуждение после сброса лимита",
                    reason=f"{type(delivery_error).__name__}: {delivery_error}",
                    dedupe_key=f"wake:{job_id}:{target_id}",
                )
                deliveries.pop(target_id, None)
                _persist_deliveries(
                    job_id,
                    config,
                    deliveries,
                    f"delivery failed for {target['name']}; {outcome}",
                )
                raise
            deliveries[target_id]["state"] = "delivered"
            sent.append(target_id)
            _persist_deliveries(
                job_id,
                config,
                deliveries,
                f"woke {len(sent)} agents",
            )
            if stagger_seconds and index < len(targets) - 1:
                await asyncio.sleep(stagger_seconds)
    except Exception as error:
        logger.exception("wake job %s failed", job_id)
        from app.db import bg_fail_job

        bg_fail_job(job_id, str(error)[:500])
        raise
    else:
        summary = outcome or f"woke {len(sent)} agents"
        bg_finish_trigger(job_id, summary)
