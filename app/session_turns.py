"""TurnManager — turn lifecycle system over AgentSession state.

Stateless method-holder: turn generation, auto-report, turn-end processing.
All state stays on the session (persistence and event loop read it directly).
"""

import asyncio
import json
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


def _rewind_past_safeguard_refusal(s: "AgentSession") -> str:
    """Отрезать стенограмму до последнего ЧИСТОГО хода. Возвращает пустую строку при отказе.

    Забракованный текст остаётся в стенограмме CLI и едет в КАЖДЫЙ следующий запрос —
    замер #155: следующий ход на постороннюю тему («лол бля») получил тот же отказ слово
    в слово. Поэтому откат безусловный, а не по кнопке: без него сессия мертва навсегда.

    Режем не «последнее сообщение», а всю цепочку отказов: второй упавший ход был сам по
    себе безобидным, и откат только его оставил бы отраву на месте. Точка среза —
    последний ответ ассистента, который НЕ является отказом фильтра.

    Штатной операцией SDK (`fork_session`), а не правкой чужого файла: источник остаётся
    нетронутым, форк получает свежие UUID. Проверено на живой стенограмме seedon —
    1571 запись с 2 отравленными и 5 отказами → форк 1067 записей, 0 и 0.
    """
    from claude_agent_sdk import fork_session, get_session_messages

    from app.session import _is_safeguard_refusal  # noqa: PLC0415 — циклический импорт на модуле

    messages = get_session_messages(s.session_id, directory=s.cwd)
    cut_at, dropped = "", 0
    for message in reversed(messages):
        payload = message.message if isinstance(message.message, dict) else {}
        content = payload.get("content")
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        if payload.get("role") == "assistant" and not _is_safeguard_refusal(text):
            cut_at = message.uuid
            break
        dropped += 1
    if not cut_at:
        return ""
    fork = fork_session(s.session_id, directory=s.cwd, up_to_message_id=cut_at)
    s.session_id_history.append({
        "session_id": s.session_id,
        "runtime": s.backend_type,
        "model": s.model,
        "safeguard_rewind_at": datetime.now(timezone.utc).isoformat(),
        "dropped_messages": dropped,
    })
    s.session_id_history = s.session_id_history[-10:]
    s.session_id = fork.session_id
    s._persist()
    return f"{dropped}"


logger = logging.getLogger("app.session")


def _unknown_quota_state() -> dict:
    return {
        "quota_five_hour_pct": None,
        "quota_seven_day_pct": None,
        "quota_primary_pct": None,
        "quota_sampled_at": None,
    }


def _unknown_quota_snapshot() -> dict:
    return {"state": _unknown_quota_state(), "display": ()}


def _window_label(provider: str, window: object, fallback: str) -> str:
    minutes = window.get("window_minutes") if isinstance(window, dict) else None
    if isinstance(minutes, int) and minutes > 0:
        if minutes % 1440 == 0:
            span = f"{minutes // 1440}d"
        elif minutes % 60 == 0:
            span = f"{minutes // 60}h"
        else:
            span = f"{minutes}m"
    else:
        span = fallback
    return f"{provider} {span}"


def _cached_quota_snapshot(
    runtime: str,
    model: str,
    *,
    now: float | None = None,
) -> dict:
    """Select one fresh runtime cache for both DB columns and turn-end text."""
    from app.routes import system

    if runtime in {"claude", "anthropic"}:
        cache = system._usage_cache
        data = cache.get("data")
        if not isinstance(data, dict):
            return _unknown_quota_snapshot()
        five_hour = data.get("five_hour")
        seven_day = data.get("seven_day")
        windows = {
            "quota_five_hour_pct": five_hour,
            "quota_seven_day_pct": seven_day,
            "quota_primary_pct": None,
        }
        display = (("Claude 5h", five_hour), ("Claude 7d", seven_day))
    elif runtime in {"codex", "codex_spark"}:
        cache = system._codex_usage_cache
        data = cache.get("data")
        if not isinstance(data, dict):
            return _unknown_quota_snapshot()
        is_spark = runtime == "codex_spark" or model == "gpt-5.3-codex-spark"
        if is_spark:
            data = data.get("spark")
        if not isinstance(data, dict):
            return _unknown_quota_snapshot()
        primary = data.get("primary")
        secondary = data.get("secondary")
        windows = {
            "quota_five_hour_pct": None,
            "quota_seven_day_pct": None,
            "quota_primary_pct": primary,
        }
        provider = "Spark" if is_spark else "Codex"
        display = (
            (_window_label(provider, primary, "primary"), primary),
            (_window_label(provider, secondary, "secondary"), secondary),
        )
    elif runtime == "grok":
        cache = system._grok_usage_cache
        data = cache.get("data")
        if not isinstance(data, dict):
            return _unknown_quota_snapshot()
        primary = data.get("primary")
        windows = {
            "quota_five_hour_pct": None,
            "quota_seven_day_pct": None,
            "quota_primary_pct": primary,
        }
        display = ((_window_label("Grok", primary, "primary"), primary),)
    else:
        return _unknown_quota_snapshot()

    sampled_ts = cache.get("ts")
    if (
        isinstance(sampled_ts, bool)
        or not isinstance(sampled_ts, (int, float))
        or not math.isfinite(sampled_ts)
    ):
        return _unknown_quota_snapshot()
    checked_at = time.time() if now is None else now
    age = checked_at - sampled_ts
    if not math.isfinite(age) or age < 0 or age >= system._USAGE_CACHE_TTL:
        return _unknown_quota_snapshot()

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
        return _unknown_quota_snapshot()
    try:
        state["quota_sampled_at"] = datetime.fromtimestamp(
            sampled_ts, timezone.utc,
        ).isoformat()
    except (OSError, OverflowError, ValueError):
        return _unknown_quota_snapshot()
    return {"state": state, "display": display}


def _cached_quota_state(
    runtime: str,
    model: str,
    *,
    now: float | None = None,
) -> dict:
    return _cached_quota_snapshot(runtime, model, now=now)["state"]


def _format_limits(snapshot: dict, *, now: float | None = None) -> str:
    checked_at = time.time() if now is None else now
    parts = []
    for label, window in snapshot.get("display", ()):
        if not isinstance(window, dict):
            continue
        utilization = window.get("utilization")
        if (
            isinstance(utilization, bool)
            or not isinstance(utilization, (int, float))
            or not math.isfinite(utilization)
            or not 0 <= utilization <= 100
        ):
            continue
        reset_s = ""
        reset_at = window.get("resets_at")
        if reset_at:
            try:
                reset = datetime.fromisoformat(str(reset_at).replace("Z", "+00:00"))
                if reset.tzinfo is None:
                    raise ValueError("timezone missing")
                remaining = reset.timestamp() - checked_at
                if remaining > 0:
                    if remaining >= 86400:
                        days, remainder = divmod(int(remaining), 86400)
                        reset_s = f" reset {days}d{remainder // 3600}h"
                    else:
                        hours, minutes = divmod(int(remaining) // 60, 60)
                        reset_s = f" reset {hours}h{minutes:02d}m"
            except (OSError, OverflowError, TypeError, ValueError) as error:
                logger.debug(
                    "%s resets_at unparsable (%r): %s: %s",
                    label, reset_at, type(error).__name__, error,
                )
        parts.append(f"{label}:{utilization:g}%{reset_s}")
    return " | " + " ".join(parts) if parts else ""


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
        # #219 T1b, ГЕЙТ 2 из 2: молчаливое завершение хода. Через
        # `send_message` этот путь НЕ идёт, поэтому гейт в роуте его не ловит,
        # а случай типичный: ребёнок, не позвавший `send_message`, разбудил бы
        # родителя мимо барьера.
        from app import fan_barrier
        if fan_barrier.should_buffer(s.name):
            # #231: осушение проверяется В ТОЙ ЖЕ транзакции, что и фиксация терминала.
            # Раздельные «посмотреть» и «записать» пропускают `wake=False`, легший
            # между ними, — и веер отпустится по ребёнку, не видевшему своего входа.
            if fan_barrier.record_terminal(
                s.name, "done", require_drained_scope=s.scope
            ):
                fan_id = fan_barrier.fan_id_for_child(s.name, include_released=True)
                target = fan_barrier.parent_of(fan_id) if fan_id else None
                if target:
                    # #231 T6: адресат тот же, что и на явном пути. Иначе поведение
                    # зависело бы от того, позвал ребёнок `send_message` или промолчал,
                    # и молчаливый ребёнок будил бы дорогого родителя мимо редьюсера.
                    reducer = fan_barrier.reducer_of(fan_id)
                    recipient = reducer or target[0]

                    async def _deliver_manifest(name=recipient, scope=target[1],
                                                fid=fan_id):
                        from app.deps import manager
                        dest = await manager.ensure_loaded(name, scope)
                        if dest:
                            await manager.send(
                                dest.id, fan_barrier.manifest_text(fid)
                            )
                    s._auto_report_task = asyncio.create_task(_deliver_manifest())
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
        cost_unaccounted = meta.get("cost_unaccounted") is True
        s._turn_start = 0
        ok, sr, nt = s._cost.apply_turn_result(meta, event.usage)
        event_id = str(meta.get("event_id") or "")
        try:
            quota_snapshot = _cached_quota_snapshot(s.backend_type, s.model)
        except Exception as error:
            logger.warning(
                f"[{s.name}] quota cache read failed: "
                f"{type(error).__name__}: {error}"
            )
            quota_snapshot = _unknown_quota_snapshot()
        if event_id:
            cost_fields = {"cost_usd": s._turn_cost}
            if cost_unaccounted:
                cost_fields = {"cost_usd": None, "cost_unaccounted": True}
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
                **cost_fields,
                input_tokens=meta.get("input_tokens", 0),
                output_tokens=meta.get("output_tokens", 0),
                cache_read_tokens=meta.get("cache_read", 0),
                cache_create_tokens=meta.get("cache_create", 0),
                **quota_snapshot["state"],
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

        # Второй гард, независимый от текста: режем историю только у ХОДА, который реально
        # упал. 07.08 16:27:01 признак по одному тексту сработал на успешном `end_turn` —
        # агент цитировал фразу отказа, объясняя инцидент, и здоровой сессии срезали ход.
        if s._safeguard_refusal and not ok:
            from app.session import (  # noqa: PLC0415 — циклический импорт
                safeguard_guidance,
                safeguard_request_id,
                store_safeguard_refusal,
            )

            verbatim = s._safeguard_refusal
            s._safeguard_refusal = ""
            try:
                dropped = _rewind_past_safeguard_refusal(s)
            except Exception as e:
                dropped = ""
                logger.error(f"[{s.name}] safeguard rewind failed: {type(e).__name__}: {e}")
            if dropped:
                # Клиент CLI живёт между ходами и держит СТАРУЮ стенограмму: без разрыва
                # соединения новый `session_id` никуда не поедет, и откат остался бы записью
                # в журнале. Следующий `_ensure_backend()` поднимет CLI уже с форка.
                s._spawn_bg(s._disconnect_backend())
                # Громко: часть диалога исчезла не сама по себе.
                s._log("status", f"🛡 отравленный ход отрезан: {dropped} сообщ. "
                                 f"назад, сессия продолжена с форка {s.session_id}")
            else:
                s._log("error", "🛡 сессия отравлена забракованным текстом, откатить не удалось "
                                "— продолжать в ней нельзя, нужна новая сессия")
            try:
                dump_path = store_safeguard_refusal(s.name, verbatim)
            except Exception as e:
                dump_path = ""
                logger.error(f"[{s.name}] safeguard dump failed: {type(e).__name__}: {e}")
            s._log("error", safeguard_guidance(safeguard_request_id(verbatim), dump_path))

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
        limits_s = _format_limits(quota_snapshot)
        if cost_unaccounted:
            cost_summary = f"cost unaccounted for {s.model}"
        else:
            cost_summary = (
                f"${_fc(s._turn_cost)} turn, ${_fc(s._context_cost)} ctx, "
                f"${_fc(s._session_cost)} session, ${_fc(s.cost_usd)} total"
            )
        s._log(
            "status",
            f"turn ended ({sr}, {nt} turns, {cost_summary} {ctx_s}){limits_s}",
            event_id=event_id,
        )

        self.finish_turn_status()
        self.after_turn_idle_actions(
            live_pct,
            allow_auto_report=server_error_retry is None,
            allow_precompact=allow_context_compaction and context_known,
            subscription_limited=subscription_limited,
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
            allow_precompact: bool = True,
            subscription_limited: bool = False) -> None:
        """Post-turn actions: compact ack, scope idle, auto-compact, auto-report, flush/hibernate."""
        s = self.s

        # finish_turn_status() has already set IDLE/WAITING and persisted, so waking
        # here can never resume an agent mid-turn.
        if subscription_limited:
            from app.limit_wake import schedule_wake_auto

            s._spawn_bg(schedule_wake_auto())
        if s._compact_ack_event is not None and s._turn_gen == s._compact_ack_gen:
            s._compact_ack_event.set()

        if allow_precompact:
            self.schedule_context_compaction(live_pct)
        s._spawn_bg(s._notify_scope_idle())

        # #231 T3: накопленное в ящике выдаётся в КОНЦЕ уже оплаченного хода, поэтому
        # активация за него не платится второй раз (пробуждение стоит ~$0.15 плюс весь
        # развёрнутый ход — docs/tasks/231/research.md §3.1).
        # Идёт СТРОГО ДО `fire_auto_report`: под включённым барьером авто-отчёт фиксирует
        # терминальное состояние ребёнка и может отпустить веер, пока у этого же ребёнка
        # лежит невыданный вход, — родитель получит сводку по недоработавшему ребёнку.
        from app import mailbox
        try:
            queued = mailbox.claim(s.name, s.scope)
        except Exception as exc:
            # Ящик — побочная услуга, жизненный цикл хода важнее. Недоступная таблица
            # (не мигрированная БД, урезанный тестовый стенд) не имеет права ронять
            # завершение хода У ВСЕХ агентов: громко в журнал и обычным путём дальше.
            from app.errtext import err_text as _err
            s._log("error", f"mailbox недоступен, ход завершается обычным путём: {_err(exc)}")
            queued = []
        if queued:
            s._log("status", f"mailbox: {len(queued)} — продолжаю ход вместо пробуждения")
            s._spawn_bg(self._deliver_mailbox(
                queued, live_pct,
                allow_auto_report=allow_auto_report,
            ))
            return

        self._idle_tail(live_pct, allow_auto_report=allow_auto_report)

    def _idle_tail(self, live_pct: int, *, allow_auto_report: bool = True) -> None:
        """Обычное завершение простоя. Вынесено, чтобы его можно было доиграть после
        неудачной выдачи из ящика: иначе сессия зависает без авто-отчёта и гибернации."""
        s = self.s
        # Don't auto-report mid-flight: WAITING means a bg job (e.g. codex_review) is
        # still running and will wake the worker with its result — the turn isn't
        # really "done", so reporting now spams a half-status to the orchestrator.
        if allow_auto_report and s.status != AgentStatus.WAITING:
            self.fire_auto_report()

        if s._pending_messages:
            s._spawn_bg(s._flush_pending())
            return

        s._hibernate.schedule()

    async def _deliver_mailbox(self, queued: list[dict], live_pct: int = 0, *,
                               allow_auto_report: bool = True) -> None:
        """Гасить ПОСЛЕ фактической выдачи, а не при обнаружении (грабля #158).

        Цикл умеет переигрывать вход; флаг, погашенный в момент обнаружения, теряет
        сообщение именно на повторе — то есть под нагрузкой, когда оно нужнее всего.
        Поэтому `mark_delivered` стоит строго после успешного `send`, а на любом сбое
        строки остаются в ящике и выдадутся в конце следующего хода.
        """
        from app import mailbox
        from app.errtext import err_text
        s = self.s
        text = "\n\n".join(f"[from:{m['sender']}] {m['body']}" for m in queued)
        ids = [m["id"] for m in queued]
        try:
            await s.send(text)
        except asyncio.CancelledError:
            # `CancelledError` НЕ наследует `Exception` (3.8+): без отдельной ветки
            # отмена задачи оставляла бы строки под арендой до её протухания
            # (находка раунда 3 ревью реализации).
            mailbox.release_claim(ids)
            raise
        except Exception as exc:
            # Возвращаем строки в ящик и ДОИГРЫВАЕМ обычный хвост простоя. Без этого
            # сессия оставалась бы без авто-отчёта и без гибернации, а сообщения —
            # без следующего конца хода, который мог бы их выдать: `wake=False`
            # будущего пробуждения не создаёт по построению.
            mailbox.release_claim(ids)
            s._log("error", f"mailbox: выдача не удалась, {len(queued)} возвращены "
                            f"в ящик: {err_text(exc)}")
            # Эскалация: продолжить ход не вышло, поэтому доставляем обычным путём —
            # он загружает сессию и будит её. Без этого следующего конца хода может
            # не случиться никогда, и сообщения залягут (F3 ревью реализации).
            try:
                from app.deps import manager as _mgr
                await _mgr.send(s.id, text)
            except Exception as esc:
                s._log("error", f"mailbox: эскалация тоже не удалась, {len(queued)} "
                                f"ждут в ящике: {err_text(esc)}")
                self._idle_tail(live_pct, allow_auto_report=allow_auto_report)
                return
            mailbox.mark_delivered(ids)
            return
        mailbox.mark_delivered(ids)

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
