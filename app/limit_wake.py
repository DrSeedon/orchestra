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
    usage_get_latest_provider_usage,
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


def build_wake_plan(
    agents: list[dict],
    provider_usage: dict,
    *,
    now: datetime | None = None,
) -> dict:
    """Map stopped agents to the latest reset among their exhausted windows."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    manual_agents = sorted(
        agent["name"] for agent in agents if agent["limit_kind"] == "monthly"
    )
    schedules = []
    unavailable_agents = []
    providers = sorted({
        agent["provider"]
        for agent in agents
        if agent["limit_kind"] == "timed"
        and not (
            agent["provider"] == "anthropic"
            and manual_agents
        )
    })
    for provider in providers:
        provider_agents = [
            agent for agent in agents
            if agent["provider"] == provider and agent["limit_kind"] == "timed"
        ]
        windows = (provider_usage.get(provider) or {}).get("windows") or []
        exhausted = []
        for window in windows:
            utilization = window.get("utilization")
            reset = _parse_reset(window.get("resets_at"))
            if (
                isinstance(utilization, (int, float))
                and utilization >= 100
                and reset
                and reset > now
            ):
                exhausted.append((reset, window))
        if not exhausted:
            unavailable_agents.extend(agent["name"] for agent in provider_agents)
            continue
        reset, _window = max(exhausted, key=lambda item: item[0])
        schedules.append({
            "provider": provider,
            "reset_at": reset.isoformat(),
            "agents": [
                {
                    "id": agent["id"],
                    "name": agent["name"],
                    "scope": agent["scope"],
                    "limit_turn_id": agent["limit_turn_id"],
                }
                for agent in provider_agents
            ],
        })
    return {
        "schedules": schedules,
        "manual_agents": manual_agents,
        "manual_action_url": MANUAL_ACTION_URL if manual_agents else None,
        "unavailable_agents": sorted(unavailable_agents),
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
    return {
        "candidate_count": len(agents),
        "monthly_agents": monthly,
        "manual_action_url": MANUAL_ACTION_URL if monthly else None,
        "scheduled": [
            {
                "provider": job["config"].get("provider"),
                "reset_at": job.get("trigger_at"),
                "agent_count": len(job["config"].get("agents") or []),
            }
            for job in jobs
        ],
    }


async def schedule_wake_after_reset() -> dict:
    """Replace provider wake timers using the latest persisted usage snapshot."""
    from app.bg_jobs import bg_manager

    agents = _load_limit_stopped_agents()
    plan = build_wake_plan(agents, usage_get_latest_provider_usage())
    planned_keys = set()
    now = datetime.now(timezone.utc)
    for schedule in plan["schedules"]:
        provider = schedule["provider"]
        replace_key = f"{WAKE_JOB_PREFIX}{provider}"
        planned_keys.add(replace_key)
        reset = _parse_reset(schedule["reset_at"])
        delay = max(0.1, (reset - now).total_seconds())
        result = await bg_manager.create(
            "timer",
            {
                "delay_seconds": delay,
                "action": WAKE_ACTION,
                "provider": provider,
                "agents": schedule["agents"],
            },
            "",
            "__system__",
            "__system__",
            "__global__",
            "dashboard",
            replace_key=replace_key,
        )
        if result.get("error"):
            raise RuntimeError(result["error"])

    for job in _active_wake_jobs():
        replace_key = job["config"].get("replace_key")
        if replace_key not in planned_keys:
            await bg_manager.cancel(job["id"])

    state = wake_status()
    state["unavailable_agents"] = plan["unavailable_agents"]
    return {
        **plan,
        "candidate_count": len(agents),
        "scheduled_count": len(plan["schedules"]),
        "state": state,
    }


def provider_is_available(provider_usage: dict, provider: str) -> bool:
    windows = (provider_usage.get(provider) or {}).get("windows") or []
    observed = [
        window["utilization"]
        for window in windows
        if isinstance(window.get("utilization"), (int, float))
    ]
    return bool(observed) and all(utilization < 100 for utilization in observed)


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

            provider_usage = await current_provider_usage(
                provider=provider,
                force_refresh=True,
            )
            if not provider_is_available(provider_usage, provider):
                outcome = f"stopped: {provider} limit is still active"
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
                await session.send(message)
            except Exception:
                deliveries.pop(target_id, None)
                _persist_deliveries(
                    job_id,
                    config,
                    deliveries,
                    f"delivery failed for {target['name']}",
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
