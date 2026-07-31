"""TurnManager — turn lifecycle system over AgentSession state.

Stateless method-holder: turn generation, auto-report, turn-end processing.
All state stays on the session (persistence and event loop read it directly).
"""

import asyncio
import logging
import math
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.db import turn_usage_add
from app.events import AgentEvent
from app.session_state import AgentStatus

if TYPE_CHECKING:
    from app.session import AgentSession


def _format_limits() -> str:
    """Format current 5h/7d usage limits from cached usage data for turn-ended log."""
    try:
        from app.routes.system import _usage_cache
        data = _usage_cache.get("data")
        if not data:
            return ""
        parts = []
        fh = data.get("five_hour") or {}
        sd = data.get("seven_day") or {}
        fh_pct = fh.get("utilization")
        sd_pct = sd.get("utilization")
        if fh_pct is not None:
            fh_reset = fh.get("resets_at", "")
            reset_s = ""
            if fh_reset:
                from datetime import datetime, timezone
                try:
                    dt = datetime.fromisoformat(fh_reset)
                    remaining = (dt - datetime.now(timezone.utc)).total_seconds()
                    if remaining > 0:
                        h, m = divmod(int(remaining) // 60, 60)
                        reset_s = f" reset {h}h{m:02d}m"
                except Exception as e:
                    # Метрика, которая молча теряет часть себя, хуже отсутствующей.
                    logger.debug(f"5h resets_at unparsable ({fh_reset!r}): {type(e).__name__}: {e}")
            parts.append(f"5h:{fh_pct:.0f}%{reset_s}")
        if sd_pct is not None:
            sd_reset = sd.get("resets_at", "")
            reset_s = ""
            if sd_reset:
                from datetime import datetime, timezone
                try:
                    dt = datetime.fromisoformat(sd_reset)
                    remaining = (dt - datetime.now(timezone.utc)).total_seconds()
                    if remaining > 0:
                        d, rem = divmod(int(remaining), 86400)
                        h = rem // 3600
                        reset_s = f" reset {d}d{h}h" if d else f" reset {h}h"
                except Exception as e:
                    logger.debug(f"7d resets_at unparsable ({sd_reset!r}): {type(e).__name__}: {e}")
            parts.append(f"7d:{sd_pct:.0f}%{reset_s}")
        return " | " + " ".join(parts) if parts else ""
    except Exception:
        return ""

logger = logging.getLogger("app.session")


def _unknown_quota_state() -> dict:
    return {
        "quota_five_hour_pct": None,
        "quota_seven_day_pct": None,
        "quota_primary_pct": None,
        "quota_sampled_at": None,
    }


def _cached_quota_state(
    runtime: str,
    model: str,
    *,
    now: float | None = None,
) -> dict:
    from app.routes import system

    if runtime in {"claude", "anthropic"}:
        cache = system._usage_cache
        data = cache.get("data")
        windows = {
            "quota_five_hour_pct": (data or {}).get("five_hour"),
            "quota_seven_day_pct": (data or {}).get("seven_day"),
            "quota_primary_pct": None,
        }
    elif runtime in {"codex", "codex_spark"}:
        cache = system._codex_usage_cache
        data = cache.get("data")
        if runtime == "codex_spark" or model == "gpt-5.3-codex-spark":
            data = (data or {}).get("spark")
        windows = {
            "quota_five_hour_pct": None,
            "quota_seven_day_pct": None,
            "quota_primary_pct": (data or {}).get("primary"),
        }
    elif runtime == "grok":
        cache = system._grok_usage_cache
        data = cache.get("data")
        windows = {
            "quota_five_hour_pct": None,
            "quota_seven_day_pct": None,
            "quota_primary_pct": (data or {}).get("primary"),
        }
    else:
        return _unknown_quota_state()

    sampled_ts = cache.get("ts")
    if (
        isinstance(sampled_ts, bool)
        or not isinstance(sampled_ts, (int, float))
        or not math.isfinite(sampled_ts)
    ):
        return _unknown_quota_state()
    age = (time.time() if now is None else now) - sampled_ts
    if not math.isfinite(age) or age < 0 or age >= system._USAGE_CACHE_TTL:
        return _unknown_quota_state()

    state = _unknown_quota_state()
    for column, window in windows.items():
        value = window.get("utilization") if isinstance(window, dict) else None
        if (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            and 0 <= value <= 100
        ):
            state[column] = value
    if all(value is None for key, value in state.items() if key != "quota_sampled_at"):
        return _unknown_quota_state()
    try:
        state["quota_sampled_at"] = datetime.fromtimestamp(
            sampled_ts, timezone.utc,
        ).isoformat()
    except (OSError, OverflowError, ValueError):
        return _unknown_quota_state()
    return state


class TurnManager:
    def __init__(self, s: "AgentSession") -> None:
        self.s = s

    def cancel_auto_report(self) -> None:
        s = self.s
        if s._auto_report_task and not s._auto_report_task.done():
            s._auto_report_task.cancel()
        s._auto_report_task = None

    def bump_turn_gen(self) -> None:
        """Новый ход начался — инвалидируем отложенный авто-репорт прошлого хода."""
        self.s._turn_gen += 1
        self.s._turn_finished_event.clear()
        self.cancel_auto_report()

    def publish_turn_finished(self) -> None:
        self.s._turn_finished_event.set()

    def fire_auto_report(self) -> None:
        """Send auto-report to parent immediately when worker goes idle.
        Orchestrators don't auto-report — they reply to user directly.
        Skipped if worker already sent explicit send_message, has pending messages,
        completed a successful silent turn, or was interrupted/stopped by user.

        Without this, silent workers (those that don't call send_message) would
        leave the orchestrator waiting forever for a signal that never comes.
        """
        s = self.s
        if s.is_orchestrator or not s.on_idle or s._did_report or s._manually_interrupted:
            return
        if s._pending_messages or s._compacting:
            return
        if s._last_turn_ok and not s._turn_logs:
            return
        # An unparented worker started directly from dashboard/TG has nobody to report
        # to. A parented child must still report: parent_name survives service restarts
        # even when the transient last_task_sender metadata does not.
        if not s.last_task_sender and not s.parent_name:
            return
        last_texts = s._turn_logs[-5:] if s._turn_logs else []
        stop_reason = s._last_stop_reason

        async def _do_report():
            try:
                await s.on_idle(
                    s.name,
                    s.scope,
                    last_texts,
                    stop_reason,
                    s._last_turn_ok,
                )
            except Exception as e:
                logger.error(f"Auto-report failed for {s.name}: {e}")

        s._auto_report_task = asyncio.create_task(_do_report())

    def handle_turn_end(self, event: AgentEvent) -> None:
        s = self.s
        meta = event.metadata
        s._turn_start = 0
        ok, sr, nt = s._cost.apply_turn_result(meta, event.usage)
        event_id = str(meta.get("event_id") or "")
        if event_id:
            try:
                quota_state = _cached_quota_state(s.backend_type, s.model)
            except Exception as error:
                logger.warning(
                    f"[{s.name}] quota cache read failed: "
                    f"{type(error).__name__}: {error}"
                )
                quota_state = _unknown_quota_state()
            s._submit_db_write(
                turn_usage_add,
                event_id=event_id,
                session_id=s.id,
                scope=s.scope,
                task_id=s.task_id,
                runtime=s.backend_type,
                model=s.model,
                ok=ok,
                stop_reason=sr,
                cost_usd=s._turn_cost,
                input_tokens=meta.get("input_tokens", 0),
                output_tokens=meta.get("output_tokens", 0),
                cache_read_tokens=meta.get("cache_read", 0),
                cache_create_tokens=meta.get("cache_create", 0),
                **quota_state,
            )
        context_known, context_reason = s._cost.update_context_from_turn(
            meta, event.usage,
        )
        if context_reason:
            s._log(
                "status",
                f"context unknown ({context_reason}); automatic compaction skipped",
            )
        if not context_known:
            s._cancel_precompact_timer("context_unknown")
        subscription_limited = s._session_limit_hit
        will_auto_continue = (
            sr in ("error_max_turns", "max_turns")
            and ok
            and s._auto_continue_count < s.AUTO_CONTINUE_MAX
        )
        allow_context_compaction = (
            not subscription_limited and not will_auto_continue
        )
        s._spawn_bg(
            s._refresh_context_from_api(
                schedule_compaction_on_success=(
                    allow_context_compaction and not context_known
                ),
            )
        )

        if not ok:
            # CLI injects [ede_diagnostic] telemetry on interrupt — cosmetic noise, not real errors
            errors = [e for e in (meta.get("errors") or []) if not str(e).startswith("[ede_diagnostic]")]
            if errors and not (
                subscription_limited
                and all(str(error).lower() == "rate_limit" for error in errors)
            ):
                s._log("error", f"turn FAILED: {'; '.join(str(e) for e in errors)}")
            elif not subscription_limited:
                s._log("status", f"turn interrupted ({sr})")

        # max_turns: SDK hit per-turn ceiling — auto-continue so agent doesn't stop mid-task.
        # tool_use is NOT included: it means external interrupt (stop/kill/permission), not agent wanting more.
        if sr in ("error_max_turns", "max_turns") and ok:
            if s._auto_continue_count >= s.AUTO_CONTINUE_MAX:
                logger.warning(f"[{s.name}] auto-continue cap ({s.AUTO_CONTINUE_MAX}) reached — staying idle")
                s._log("error", f"auto-continue cap reached ({s.AUTO_CONTINUE_MAX}) — agent stuck at {sr}")
            else:
                s._auto_continue_count += 1
                s._log("status", f"{sr} ({nt} turns), auto-continuing "
                                 f"({s._auto_continue_count}/{s.AUTO_CONTINUE_MAX})")
                s._spawn_bg(s._auto_continue())
                return
        else:
            s._auto_continue_count = 0

        server_error_retry = None
        model_error = str(meta.get("model_error") or "")
        if not ok and model_error == "server_error":
            if s._server_error_retries < s.SERVER_ERROR_MAX_RETRIES:
                s._server_error_retries += 1
                delay = s.SERVER_ERROR_RETRY_DELAY * s._server_error_retries
                server_error_retry = (delay, s._turn_gen)
                s._log(
                    "status",
                    f"transient server_error — fresh-backend retry in {delay}s "
                    f"({s._server_error_retries}/{s.SERVER_ERROR_MAX_RETRIES})",
                )
            else:
                s._log(
                    "error",
                    f"server_error — gave up after {s.SERVER_ERROR_MAX_RETRIES} retries",
                )

        live_pct = s._last_context.get("percentage", 0)
        ctx_s = f"ctx:{live_pct}%" if live_pct else ""
        def _fc(v):
            return f"{v:.4f}" if v < 0.01 and v > 0 else f"{v:.2f}"
        limits_s = _format_limits()
        s._log(
            "status",
            f"turn ended ({sr}, {nt} turns, ${_fc(s._turn_cost)} turn, "
            f"${_fc(s._context_cost)} ctx, ${_fc(s._session_cost)} session, "
            f"${_fc(s.cost_usd)} total {ctx_s}){limits_s}",
            event_id=event_id,
        )

        self.finish_turn_status()
        self.after_turn_idle_actions(
            live_pct,
            allow_auto_report=server_error_retry is None,
            allow_precompact=allow_context_compaction and context_known,
        )
        if server_error_retry is not None:
            s._spawn_bg(s._retry_after_server_error(*server_error_retry))

    def finish_turn_status(self) -> None:
        """Set IDLE or WAITING based on bg jobs, then persist."""
        s = self.s
        from app.bg_jobs import bg_manager
        if bg_manager and bg_manager.has_active_jobs(s.id):
            s.status = AgentStatus.WAITING
            s._log("status", "waiting for bg jobs")
        else:
            s.status = AgentStatus.IDLE
            s.progress_pct = 0
            s.progress_status = ""
        s._persist()
        self.publish_turn_finished()

    def after_turn_idle_actions(
            self, live_pct: int, *, allow_auto_report: bool = True,
            allow_precompact: bool = True) -> None:
        """Post-turn actions: compact ack, scope idle, auto-compact, auto-report, flush/hibernate."""
        s = self.s
        if s._compact_ack_event is not None and s._turn_gen == s._compact_ack_gen:
            s._compact_ack_event.set()

        if allow_precompact:
            self.schedule_context_compaction(live_pct)
        s._spawn_bg(s._notify_scope_idle())

        # Don't auto-report mid-flight: WAITING means a bg job (e.g. codex_review) is
        # still running and will wake the worker with its result — the turn isn't
        # really "done", so reporting now spams a half-status to the orchestrator.
        if allow_auto_report and s.status != AgentStatus.WAITING:
            self.fire_auto_report()

        if s._pending_messages:
            s._spawn_bg(s._flush_pending())
            return

        s._hibernate.schedule()

    def schedule_context_compaction(self, live_pct: int) -> None:
        """Run both automatic compaction decisions from one validated context."""
        s = self.s
        s._schedule_precompact_timer(live_pct)
        if (
            live_pct > 90
            and s.backend_type != "codex"
            and not s.is_orchestrator
            and not s._compacting
        ):
            # Workers auto-compact to stay operational; orchestrators are left for
            # the user to compact manually since they hold long-running session state.
            # Codex app-server compacts the current thread natively; replacing that
            # thread with Orchestra's generic handoff loses native thread continuity.
            s._log("status", f"auto-compact triggered ({live_pct}%)")
            s._spawn_bg(s._auto_compact())
