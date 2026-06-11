"""TurnManager — turn lifecycle system over AgentSession state.

Stateless method-holder: turn generation, auto-report, turn-end processing.
All state stays on the session (persistence and event loop read it directly).
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from app.events import AgentEvent
from app.session_state import AgentStatus

if TYPE_CHECKING:
    from app.session import AgentSession

logger = logging.getLogger("app.session")


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
        self.cancel_auto_report()

    def fire_auto_report(self) -> None:
        """Send auto-report to parent immediately when worker goes idle.
        Orchestrators don't auto-report — they reply to user directly.
        Skipped if worker already sent explicit send_message, has pending messages,
        or was interrupted/stopped by user.

        Without this, silent workers (those that don't call send_message) would
        leave the orchestrator waiting forever for a signal that never comes.
        """
        s = self.s
        if s.is_orchestrator or not s.on_idle or s._did_report:
            return
        if s._pending_messages or s._compacting:
            return
        if not s._last_turn_ok:
            return
        last_texts = s._turn_logs[-5:] if s._turn_logs else []
        stop_reason = s._last_stop_reason

        async def _do_report():
            try:
                await s.on_idle(s.name, s.scope, last_texts, stop_reason)
            except Exception as e:
                logger.error(f"Auto-report failed for {s.name}: {e}")

        s._auto_report_task = asyncio.create_task(_do_report())

    def handle_turn_end(self, event: AgentEvent) -> None:
        s = self.s
        meta = event.metadata
        s._turn_start = 0
        ok, sr, nt = s._cost.apply_turn_result(meta)
        s._cost.update_context_from_turn(meta)
        s._spawn_bg(s._refresh_context_from_api())

        if not ok:
            errors = meta.get("errors") or []
            err_txt = "; ".join(str(e) for e in errors) if errors else sr
            s._log("error", f"turn FAILED: {err_txt}")

        if sr in ("error_max_turns", "max_turns") and ok:
            # SDK has a per-turn limit; auto-continue so agents don't silently stop
            # mid-task when they hit it. The injected message gives them context.
            # Depth cap: without it an agent stuck at max_turns recurses unbounded.
            if s._auto_continue_count >= s.AUTO_CONTINUE_MAX:
                logger.warning(f"[{s.name}] auto-continue cap ({s.AUTO_CONTINUE_MAX}) reached — staying idle")
                s._log("error", f"auto-continue cap reached ({s.AUTO_CONTINUE_MAX}) — agent stuck at max_turns")
            else:
                s._auto_continue_count += 1
                s._log("status", f"max_turns reached ({nt}), auto-continuing "
                                 f"({s._auto_continue_count}/{s.AUTO_CONTINUE_MAX})")
                s._spawn_bg(s._auto_continue())
                return
        else:
            # consecutive counter: any non-max_turns turn end resets the cap
            s._auto_continue_count = 0

        live_pct = s._last_context.get("percentage", 0)
        ctx_s = f"ctx:{live_pct}%" if live_pct else ""
        s._log("status", f"turn ended ({sr}, {nt} turns, ${s._turn_cost:.2f} turn, ${s._context_cost:.2f} ctx, ${s.cost_usd:.2f} total {ctx_s})")

        self.finish_turn_status()
        self.after_turn_idle_actions(live_pct)

    def finish_turn_status(self) -> None:
        """Set IDLE or WAITING based on bg jobs, then persist."""
        s = self.s
        from app.bg_jobs import bg_manager
        if bg_manager and bg_manager.has_active_jobs(s.id):
            s.status = AgentStatus.WAITING
            s._log("status", "waiting for bg jobs")
        else:
            s.status = AgentStatus.IDLE
        s._persist()

    def after_turn_idle_actions(self, live_pct: int) -> None:
        """Post-turn actions: compact ack, scope idle, auto-compact, auto-report, flush/hibernate."""
        s = self.s
        if s._compact_ack_event is not None and s._turn_gen == s._compact_ack_gen:
            s._compact_ack_event.set()

        s._spawn_bg(s._notify_scope_idle())

        if live_pct > 90 and not s.is_orchestrator and not s._compacting:
            # Workers auto-compact to stay operational; orchestrators are left for
            # the user to compact manually since they hold long-running session state
            s._log("status", f"auto-compact triggered ({live_pct}%)")
            s._spawn_bg(s._auto_compact())

        self.fire_auto_report()

        if s._pending_messages:
            s._spawn_bg(s._flush_pending())
            return

        s._hibernate.schedule()
