"""AgentSession — backend-agnostic wrapper with persistent event loop."""

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.events import AgentEvent
from app.models import backend_for_model, get_model_spec
from app.prompting import (
    inject_skills_to_worktree, is_orchestrator_role, prompt_template_hash,
    refresh_worker_memory,
)
from app.runtime_registry import (
    BackendBuildContext,
    _load_scope_mcp_servers,
    _load_user_mcp_servers,
    build_backend,
    get_runtime,
)
from app.session_cost import CostTracker
from app.session_hibernate import HibernateManager
from app.session_state import (  # noqa: F401 — re-exported: importers use app.session.AgentStatus
    AgentStatus, IDLE_TIMEOUT_ORCHESTRATOR, IDLE_TIMEOUT_WORKER,
)
from app.session_turns import TurnManager
from app.usage_contract import KnownContext, current_context

if TYPE_CHECKING:
    from app.backend_protocol import BackendLike
from app.db import add_log, get_logs, save_session, tool_error_add
from app.errtext import err_text


logger = logging.getLogger(__name__)


def _subscription_limit_kind(text: str) -> str | None:
    """Classify the canonical non-transient subscription-limit messages."""
    lowered = text.lower()
    if "monthly spend limit" in lowered:
        return "monthly"
    if any(marker in lowered for marker in (
        "session limit",
        "hit your session",
        "hit your usage limit",
        "usage limit",
        "subscription limit — ждём сброса квоты",
        "weekly usage limit",
        "weekly limit",
    )):
        return "timed"
    return None


def _is_terminal_subscription_limit(text: str) -> bool:
    """Known non-transient subscription limits that must never enter server retry."""
    return _subscription_limit_kind(text) is not None


# Провайдер бракует ФОРМУЛИРОВКУ до модели, а наружу отдаёт тот же безликий
# `invalid_request`, что и «плохой параметр» — по коду эти случаи неразличимы.
# Fail-open: не совпало → ведём себя как раньше; ложно принять обычную ошибку за
# фильтр хуже, чем не распознать фильтр.
_SAFEGUARD_MARKER = "safeguards flagged this message"
# Отказ печатает CLI, и он ВСЕГДА начинается с этого префикса, занимая всё событие целиком.
# Одной фразы-маркера мало: агент, объясняющий инцидент, цитирует её в своём обычном ответе —
# так и вышло 07.08 в 16:27:01, когда УСПЕШНЫЙ ход (`end_turn`) был принят за отказ и сессии
# срезали историю. Признак берём из тела: чужая цитата стоит внутри текста, а не открывает его.
_SAFEGUARD_PREFIX = "api error:"
_REQUEST_ID_RE = re.compile(r"\breq_[A-Za-z0-9]+")


def _is_safeguard_refusal(text: str) -> bool:
    """Отказ фильтра провайдера на формулировку запроса (#155, ужесточён в #161)."""
    lowered = text.lstrip().lower()
    return lowered.startswith(_SAFEGUARD_PREFIX) and _SAFEGUARD_MARKER in lowered


def safeguard_request_id(text: str) -> str:
    """`Request ID` из отказа — единственное, что из него можно безопасно цитировать."""
    match = _REQUEST_ID_RE.search(text)
    return match.group(0) if match else ""


def safeguard_guidance(request_id: str, dump_path: str) -> str:
    """Что агенту делать дальше. Признаки проверяемые — агент применяет их к своему тексту.

    ТЕЛА ЗАБРАКОВАННОГО ТЕКСТА ЗДЕСЬ НЕТ И БЫТЬ НЕ ДОЛЖНО. Объяснение едет в контекст
    следующего хода, поэтому вклеенная цитата травит его заново: агент отвечает, цитируя
    её, и следующий ход снова срезается. Замер #161 — ровно эта петля у seedon. Наружу
    только класс отказа, три признака, `Request ID` и ссылка на форму; полный текст лежит
    файлом, и путь к нему безопасен, а содержимое — нет.

    Основание для признаков — два прошедших хода на формально той же теме (поиск утёкшего
    секрета `git log -S` по всем ревизиям трёх СВОИХ репозиториев, чтение доки GitHub про
    удаление чувствительных данных): тема «секреты и доступ» фильтр не роняет, роняет залог
    и чужая собственность.
    """
    tail = f"Request ID: {request_id}\n" if request_id else ""
    where = f"Полный текст отказа (в контекст не втягивать): {dump_path}\n" if dump_path else ""
    return (
        "🛡 Фильтр провайдера забраковал ФОРМУЛИРОВКУ запроса — до модели он не дошёл. "
        "Смена Claude-модели не поможет: фильтр общий для семейства.\n"
        "Переформулируй, проверив три признака по своему тексту:\n"
        "1. система СВОЯ, а не чужая («наши репозитории», «наш сайт»);\n"
        "2. глагол «убедиться / проверить», а не «получить доступ / обойти»;\n"
        "3. в задании нет фразы, которая читается как инструкция к действию над защитой.\n"
        "Не цитируй забракованную формулировку — цитата вернёт отказ.\n"
        "Не помогло — смени рантайм на не-Anthropic.\n"
        "Форма исключения: https://claude.com/form/cyber-use-case\n"
        + tail + where
    )


def store_safeguard_refusal(session_name: str, text: str) -> str:
    """Сложить сырой отказ ВНЕ рабочего дерева и вернуть путь.

    Не в `docs/tasks/`: хранилище, которое пишется само, не должно делить рабочее дерево с
    Git-lifecycle — так `report_bug` пачкал чекаут и блокировал все мержи (#114). Адрес тот же,
    что у инбокса баг-репортов.
    """
    directory = Path.home() / ".local/state/orchestra/safeguard-refusals"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = directory / f"{stamp}-{session_name}.txt"
    path.write_text(text, encoding="utf-8")
    return str(path)


def _claude_subscription_limit_active() -> bool:
    try:
        from app.routes.system import _usage_cache
        usage = _usage_cache.get("data") or {}
    except Exception:
        return False
    now = datetime.now(timezone.utc)
    for name in ("five_hour", "seven_day"):
        window = usage.get(name) or {}
        utilization = window.get("utilization")
        if not isinstance(utilization, (int, float)) or utilization < 100:
            continue
        resets_at = window.get("resets_at")
        if not resets_at:
            return True
        try:
            reset = datetime.fromisoformat(str(resets_at).replace("Z", "+00:00"))
            if reset.tzinfo is None:
                reset = reset.replace(tzinfo=timezone.utc)
            if reset > now:
                return True
        except (TypeError, ValueError):
            return True
    return False


import concurrent.futures
_DB_EXECUTOR: Optional[concurrent.futures.ThreadPoolExecutor] = None


def _db_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Dedicated pool for DB writes so logs/persists don't contend with git ops
    on the default executor (used by asyncio.to_thread)."""
    global _DB_EXECUTOR
    if _DB_EXECUTOR is None:
        # 4 workers: enough for concurrent log/persist bursts without starving the event loop
        _DB_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="db")
    return _DB_EXECUTOR


_LAST_SUMMARY_MAX_CHARS = 4_000
# Where each runtime's CLI discovers project skills. A runtime absent here gets no injection —
# an `else: ".claude"` default would silently plant Claude files for the next new backend.
_SKILL_HOME_DIRS = {"claude": ".claude", "codex": ".codex"}

# Compact summary is a multi-KB wall of text; logging it as "text" mirrors it to TG
# as agent speech. Off by default — the summary already lives in the agent's context
# and in the compact_worker result.
LOG_COMPACT_SUMMARY = os.getenv("LOG_COMPACT_SUMMARY", "0").strip().lower() in ("1", "true", "yes")
_AUTO_COMPACT_WINDOW_START_DEFAULT = "21:00"
_AUTO_COMPACT_WINDOW_END_DEFAULT = "06:00"
_AUTO_COMPACT_TIMEZONE_DEFAULT = "Asia/Krasnoyarsk"


def _configured_auto_compact_window_state(
        now_utc: datetime, start_raw: str, end_raw: str,
        timezone_name: str) -> dict:
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", start_raw):
        raise RuntimeError(
            "AUTO_COMPACT_WINDOW_START must use HH:MM (24-hour time)"
        )
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", end_raw):
        raise RuntimeError(
            "AUTO_COMPACT_WINDOW_END must use HH:MM (24-hour time)"
        )
    start = datetime.strptime(start_raw, "%H:%M").time()
    end = datetime.strptime(end_raw, "%H:%M").time()
    if start == end:
        raise RuntimeError(
            "AUTO_COMPACT_WINDOW_START and AUTO_COMPACT_WINDOW_END must differ"
        )
    try:
        configured_tz = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise RuntimeError(
            f"AUTO_COMPACT_TIMEZONE must be an IANA timezone, "
            f"got {timezone_name!r}"
        ) from exc
    if now_utc.tzinfo is None:
        raise RuntimeError("auto-compact window requires an aware datetime")

    local_now = now_utc.astimezone(configured_tz)
    local_clock = local_now.time().replace(tzinfo=None)
    if start < end:
        allowed = start <= local_clock < end
    else:
        allowed = local_clock >= start or local_clock < end
    return {
        "allowed": allowed,
        "local_time": local_now.isoformat(timespec="minutes"),
        "timezone": timezone_name,
        "window": f"{start_raw}-{end_raw}",
    }


def auto_compact_enabled() -> bool:
    """`AUTO_COMPACT_ENABLED=0` полностью выключает АВТОМАТИЧЕСКИЙ компакт оркестратора.

    Ручной `compact_worker` не затрагивается — это аварийный выход. Воркерский автокомпакт
    по >90% тоже: он держит воркера работоспособным, а жалоба была про оркестратора, который
    к утру приходил с компакта посреди начатой ночью работы.

    Читается на КАЖДОМ решении, а не при импорте: иначе значение застывает на момент старта
    процесса, и правка `.env` не действует до перезапуска даже там, где могла бы.
    """
    return os.getenv("AUTO_COMPACT_ENABLED", "1").strip().lower() in ("1", "true", "yes")


def validate_auto_compact_window_config() -> None:
    _configured_auto_compact_window_state(
        datetime.now(timezone.utc),
        os.getenv(
            "AUTO_COMPACT_WINDOW_START",
            _AUTO_COMPACT_WINDOW_START_DEFAULT,
        ).strip(),
        os.getenv(
            "AUTO_COMPACT_WINDOW_END",
            _AUTO_COMPACT_WINDOW_END_DEFAULT,
        ).strip(),
        os.getenv(
            "AUTO_COMPACT_TIMEZONE",
            _AUTO_COMPACT_TIMEZONE_DEFAULT,
        ).strip(),
    )


def _bounded_summary(summary: str) -> str:
    summary = summary.strip()
    if len(summary) <= _LAST_SUMMARY_MAX_CHARS:
        return summary
    marker = "\n\n[… summary truncated …]\n\n"
    head = (_LAST_SUMMARY_MAX_CHARS - len(marker)) // 2
    tail = _LAST_SUMMARY_MAX_CHARS - len(marker) - head
    return summary[:head] + marker + summary[-tail:]


@dataclass
class AgentSession:
    id: str
    name: str
    scope: str
    cwd: str
    model: str = "claude-sonnet-5[1m]"
    system_prompt: str = ""
    status: AgentStatus = AgentStatus.IDLE
    session_id: str | None = None
    session_id_history: list = field(default_factory=list, repr=False)
    cost_usd: float = 0.0
    cost_usd_cached: float = 0.0
    worktree_path: str | None = None
    branch: str | None = None
    base_branch: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    role: str = "worker"
    parent_id: str = ""
    parent_name: str = ""
    pipeline: str = ""
    profile: str = ""
    _is_orchestrator: bool | None = field(default=None, repr=False)
    color: str = ""
    mcp_servers: dict = field(default_factory=dict, repr=False)
    mcp_servers_custom: dict = field(default_factory=dict, repr=False)
    on_error: Optional[callable] = field(default=None, repr=False)
    backend_type: str = "claude"
    effort: str | None = None
    runtime_handoff: str = ""
    last_summary: str = ""
    task_id: str = ""
    description: str = ""
    owned_dirs: list = field(default_factory=list, repr=False)
    tg_topic: bool = False

    needs_switch: bool = False
    last_task_sender: str = ""

    # Имя сменилось, пока жил этот коннект. env MCP-подпроцесса замораживается при его
    # старте, поэтому подпроцесс надо поднять заново — но только на ГРАНИЦЕ хода:
    # дисконнект внутри хода оборвал бы живой ход. Флаг идемпотентен: два переименования
    # за ход дают одну пересборку.
    _identity_stale: bool = field(default=False, repr=False)

    # False → detached DB-hydrate (manager._hydrate_row): data only, no backend/tasks.
    # NEVER call start()/send()/_persist() on a detached session.
    loaded: bool = True
    # raw DB row of a detached session — preserves legacy response shape (richer than to_dict)
    db_row: Optional[dict] = field(default=None, repr=False)

    progress_pct: int = 0
    progress_status: str = ""

    total_turns: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_create_tokens: int = 0
    total_tool_calls: int = 0

    _backend: Optional["BackendLike"] = field(default=None, repr=False)
    _listen_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _heartbeat_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _background_tasks: set = field(default_factory=set, repr=False)
    _log_futures: set = field(default_factory=set, repr=False)
    _last_context: dict = field(default_factory=lambda: {"percentage": 0, "total_tokens": 0, "max_tokens": 0}, repr=False)
    _did_report: bool = field(default=False, repr=False)
    _turn_logs: list = field(default_factory=list, repr=False)
    _tool_names_by_id: dict = field(default_factory=dict, repr=False)
    _prompt_injected: bool = field(default=False, repr=False)
    _current_prompt: str = field(default="", repr=False)
    _template_hash: str = field(default="", repr=False)
    _turn_start: float = field(default=0.0, repr=False)
    _last_msg_time: float = field(default=0.0, repr=False)
    _pending_messages: list = field(default_factory=list, repr=False)
    on_idle: Optional[callable] = field(default=None, repr=False)
    _hibernate_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _hibernated: bool = field(default=False, repr=False)
    _compacting: bool = field(default=False, repr=False)
    _compact_ack_event: Optional[asyncio.Event] = field(default=None, repr=False)
    _compact_ack_gen: int = field(default=-1, repr=False)
    _last_cost: float = field(default=0.0, repr=False)
    _turn_cost: float = field(default=0.0, repr=False)
    _context_cost: float = field(default=0.0, repr=False)
    _session_cost: float = field(default=0.0, repr=False)
    _last_cost_cached: float = field(default=0.0, repr=False)
    _last_turn_ok: bool = field(default=True, repr=False)
    _last_stop_reason: str = field(default="", repr=False)
    _lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _persist_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _persist_dirty: bool = field(default=False, repr=False)
    _turn_gen: int = field(default=0, repr=False)
    _turn_finished_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _auto_report_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _spawn_warning: str = field(default="", repr=False)
    _spawn_repo_path: str = field(default="", repr=False)
    _spawn_git_common_dir: str = field(default="", repr=False)
    _auto_continue_count: int = field(default=0, repr=False)
    _rate_limit_retries: int = field(default=0, repr=False)
    _server_error_retries: int = field(default=0, repr=False)
    _session_limit_hit: bool = field(default=False, repr=False)
    _safeguard_refusal: str = field(default="", repr=False)
    _manually_interrupted: bool = field(default=False, repr=False)
    _precompact_timer_task: asyncio.Task | None = field(default=None, repr=False)
    _precompact_timer: dict | None = field(default=None, repr=False)
    # Одна строка в журнал на сессию: решение принимается каждый ход, а причина не меняется.
    _auto_compact_off_logged: bool = field(default=False, repr=False)

    AUTO_CONTINUE_MAX = 5
    RATE_LIMIT_MAX_RETRIES = 3
    RATE_LIMIT_DELAY = 30
    SERVER_ERROR_MAX_RETRIES = 3
    SERVER_ERROR_RETRY_DELAY = 5
    PRECOMPACT_DELAY_SECONDS = 55 * 60
    PRECOMPACT_CONTEXT_THRESHOLD = 20
    CODEX_PRECOMPACT_DELAY_SECONDS = 25 * 60
    CODEX_PRECOMPACT_CONTEXT_THRESHOLD = 60
    CLAUDE_CACHE_WINDOW_SECONDS = 60 * 60
    # ChatGPT-auth Codex publishes no contractual cache TTL. Keep a five-minute
    # safety margin before the observed/documented ~30-minute reference window.
    CODEX_CACHE_WINDOW_SECONDS = 30 * 60
    AUTO_COMPACT_WINDOW_START = _AUTO_COMPACT_WINDOW_START_DEFAULT
    AUTO_COMPACT_WINDOW_END = _AUTO_COMPACT_WINDOW_END_DEFAULT
    AUTO_COMPACT_TIMEZONE = _AUTO_COMPACT_TIMEZONE_DEFAULT

    def _precompact_payload(self, payload: dict) -> str:
        return json.dumps(payload, ensure_ascii=False)

    def _precompact_policy(self) -> dict | None:
        if self.backend_type == "claude":
            return {
                "delay_seconds": self.PRECOMPACT_DELAY_SECONDS,
                "cache_window_seconds": self.CLAUDE_CACHE_WINDOW_SECONDS,
                "context_threshold": self.PRECOMPACT_CONTEXT_THRESHOLD,
                "arm_threshold": 0,
                "compact_mode": "handoff",
            }
        if self.backend_type == "codex":
            return {
                "delay_seconds": self.CODEX_PRECOMPACT_DELAY_SECONDS,
                "cache_window_seconds": self.CODEX_CACHE_WINDOW_SECONDS,
                "context_threshold": self.CODEX_PRECOMPACT_CONTEXT_THRESHOLD,
                "arm_threshold": self.CODEX_PRECOMPACT_CONTEXT_THRESHOLD,
                "compact_mode": "native",
            }
        return None

    def _auto_compact_window_state(
            self, now_utc: datetime | None = None) -> dict:
        return _configured_auto_compact_window_state(
            now_utc or datetime.now(timezone.utc),
            os.getenv(
                "AUTO_COMPACT_WINDOW_START", self.AUTO_COMPACT_WINDOW_START,
            ).strip(),
            os.getenv(
                "AUTO_COMPACT_WINDOW_END", self.AUTO_COMPACT_WINDOW_END,
            ).strip(),
            os.getenv(
                "AUTO_COMPACT_TIMEZONE", self.AUTO_COMPACT_TIMEZONE,
            ).strip(),
        )

    def _auto_compact_window_blocked(
            self, context_pct: int, now_utc: datetime | None = None,
            *, log_status: bool = True, deferred: bool = False) -> bool:
        if not self.is_orchestrator:
            return False
        if not auto_compact_enabled():
            # Таймер мог быть взведён до того, как флаг выставили: решение о компакте
            # принимается здесь, поэтому здесь же он и обязан гаситься.
            if log_status:
                self._log(
                    "status",
                    "auto-compact disabled (AUTO_COMPACT_ENABLED=0); "
                    "manual compact remains available",
                )
            return True
        state = self._auto_compact_window_state(now_utc)
        if state["allowed"]:
            return False
        if not log_status:
            return True
        risk = (
            "; context is critically high and may hit the runtime limit"
            if context_pct > 90
            else ""
        )
        outcome = "deferred" if deferred else "blocked"
        self._log(
            "status",
            f"auto-compact {outcome} outside configured window: "
            f"context {context_pct}%, local {state['local_time']}, "
            f"window {state['window']} {state['timezone']}{risk}; "
            "manual compact remains available",
        )
        return True

    def _cancel_precompact_timer(self, reason: str = "activity") -> None:
        if self._precompact_timer_task and not self._precompact_timer_task.done():
            self._precompact_timer_task.cancel()
        self._precompact_timer_task = None
        if self._precompact_timer:
            payload = {
                "event": "precompact_timer_cancelled",
                "scheduled_at": self._precompact_timer.get("scheduled_at"),
                "reason": reason,
            }
            self._log("status", f"precompact timer cancelled: {self._precompact_payload(payload)}")
        self._precompact_timer = None

    def _note_next_precompact_activity(self) -> None:
        if not self._precompact_timer:
            return
        fired_at = self._precompact_timer.get("fired_at")
        if not fired_at:
            self._cancel_precompact_timer(reason="activity_before_fire")
            return
        if not self._precompact_timer.get("next_activity"):
            next_activity = datetime.now(timezone.utc)
            try:
                elapsed = (
                    next_activity
                    - datetime.fromisoformat(self._precompact_timer["scheduled_at"])
                )
                cache_window_seconds = int(
                    self._precompact_timer.get(
                        "cache_window_seconds",
                        self.CLAUDE_CACHE_WINDOW_SECONDS,
                    )
                )
                crossed_cache_window = (
                    elapsed >= timedelta(seconds=cache_window_seconds)
                )
                crossed_60m = elapsed >= timedelta(minutes=60)
            except Exception:
                crossed_cache_window = False
                crossed_60m = False
            self._precompact_timer["next_activity"] = next_activity.isoformat()
            self._precompact_timer["crossed_cache_window"] = crossed_cache_window
            self._precompact_timer["crossed_60m"] = crossed_60m
            self._log(
                "status",
                f"precompact timer outcome: {self._precompact_payload(self._precompact_timer)}",
            )
            self._precompact_timer = None

    def _context_is_known(self) -> bool:
        if "known" in self._last_context:
            return bool(self._last_context["known"])
        return bool(
            self._last_context.get("percentage", 0)
            or self._last_context.get("total_tokens", 0)
        )

    def _schedule_precompact_timer(self, context_pct: int) -> None:
        if self._precompact_timer is not None:
            return
        policy = self._precompact_policy()
        if policy is None or context_pct < policy["arm_threshold"]:
            return
        if self.is_orchestrator and not auto_compact_enabled():
            # Не взводим вовсе: гейт ниже по течению отменил бы компакт, но таймер писал бы
            # в журнал «запланирован» и «пропущен» на каждом ходу.
            if not self._auto_compact_off_logged:
                self._auto_compact_off_logged = True
                self._log(
                    "status",
                    "auto-compact disabled (AUTO_COMPACT_ENABLED=0): precompact timer not "
                    "scheduled; manual compact remains available",
                )
            return
        window_warning_logged = False
        if context_pct > 90:
            window_warning_logged = self._auto_compact_window_blocked(
                context_pct, deferred=True,
            )
        self._precompact_timer = {
            "scheduled_at": datetime.now(timezone.utc).isoformat(),
            "role": self.role,
            "backend": self.backend_type,
            "context_pct": context_pct,
            "window_warning_logged": window_warning_logged,
            **policy,
        }
        self._log(
            "status",
            f"precompact timer scheduled: {self._precompact_payload(self._precompact_timer)}",
        )
        self._precompact_timer_task = self._spawn_bg(self._run_precompact_timer())

    async def _run_precompact_timer(self) -> None:
        try:
            delay = (
                self._precompact_timer.get("delay_seconds")
                if self._precompact_timer
                else self.PRECOMPACT_DELAY_SECONDS
            )
            await asyncio.sleep(delay)
            await self._fire_precompact_timer()
        except asyncio.CancelledError:
            pass

    async def _fire_precompact_timer(self) -> None:
        state = self._precompact_timer
        self._precompact_timer_task = None
        if not state:
            return

        fired_at = datetime.now(timezone.utc)
        state["fired_at"] = fired_at.isoformat()
        state["context_pct"] = self._last_context.get("percentage", 0)

        if self.status != AgentStatus.IDLE:
            state["skip_reason"] = "not_idle"
            self._log(
                "status",
                f"precompact timer skipped: {self._precompact_payload(state)}",
            )
            self._precompact_timer = None
            return

        from app.bg_jobs import bg_manager
        if bg_manager and bg_manager.has_active_jobs(self.id):
            state["skip_reason"] = "active_bg_jobs"
            self._log(
                "status",
                f"precompact timer skipped: {self._precompact_payload(state)}",
            )
            self._precompact_timer = None
            return

        policy = self._precompact_policy()
        if policy is None or state.get("backend") != self.backend_type:
            state["skip_reason"] = "backend_changed"
            self._log(
                "status",
                f"precompact timer skipped: {self._precompact_payload(state)}",
            )
            self._precompact_timer = None
            return

        if not self._context_is_known():
            state["skip_reason"] = "unknown_context"
            self._log(
                "status",
                f"precompact timer skipped: {self._precompact_payload(state)}",
            )
            self._precompact_timer = None
            return

        threshold = int(state.get("context_threshold", policy["context_threshold"]))
        if self._last_context.get("percentage", 0) < threshold:
            state["skip_reason"] = "low_context"
            self._log(
                "status",
                f"precompact timer skipped: {self._precompact_payload(state)}",
            )
            self._precompact_timer = None
            return

        if self._auto_compact_window_blocked(
                self._last_context.get("percentage", 0), fired_at,
                log_status=not state.get("window_warning_logged", False)):
            state["skip_reason"] = "outside_auto_compact_window"
            self._precompact_timer = None
            return

        state["role"] = self.role
        state["backend"] = self.backend_type
        self._log(
            "status",
            f"precompact timer fired: {self._precompact_payload(state)}",
        )
        result = await self.compact()
        state["compact_result"] = result
        self._log(
            "status",
            f"precompact timer compacted: {self._precompact_payload(state)}",
        )

    def __post_init__(self) -> None:
        # Systems over state (ECS): cost/turn/hibernate methods live in systems,
        # all fields stay on the session (persistence reads them directly)
        self._cost = CostTracker(self)
        self._turns = TurnManager(self)
        self._hibernate = HibernateManager(self)

    @property
    def is_orchestrator(self) -> bool:
        if self._is_orchestrator is not None:
            return self._is_orchestrator
        return is_orchestrator_role(self.role)

    @is_orchestrator.setter
    def is_orchestrator(self, value: bool) -> None:
        self._is_orchestrator = value

    def _make_backend(self, force_fresh: bool = False):
        spec = get_model_spec(self.model)
        context = BackendBuildContext(
            model=self.model,
            provider=spec.provider,
            cwd=self.cwd,
            system_prompt=self.system_prompt,
            resume_session_id=None if force_fresh else self.session_id,
            mcp_servers=self.mcp_servers,
            is_orchestrator=self.is_orchestrator,
            scope=self.scope,
            pipeline=self.pipeline,
            role=self.role,
            profile=self.profile,
            effort=self.effort,
            context_limit=spec.context_length,
        )
        return build_backend(self.backend_type, context)

    def _attach_pending_facts(self, message: str) -> tuple[str, list[str]]:
        """Приписать к сообщению ФАКТЫ о недоставке, накопленные для этой сессии (#50).

        Это НЕ ретрай: исходные сообщения не пересылаются, едет только факт, что они не
        дошли. Иначе ждущий агент не узнаёт о недоставке никогда — запись в `logs` типа
        `system` в контекст не попадает (измерено в #47).

        Не бросает НИЧЕГО: сообщение важнее факта. Сбой очереди → уходит как раньше.
        """
        try:
            from app.db import peek_facts

            pending = peek_facts(self.id)
        except Exception as error:
            logger.warning(f"[{self.name}] pending facts unavailable: "
                           f"{type(error).__name__}: {error}")
            return message, []
        if not pending["facts"]:
            return message, []
        lines = [f"- {f['created_at'][11:16]} {f['text']}" for f in pending["facts"]]
        if pending["collapsed"]:
            lines.append(f"- …и ещё {pending['collapsed']} событий, свёрнуто; "
                         f"полностью — в истории сессии")
        head = (
            f"[Orchestra platform note: пока тебя не было, до тебя не дошло "
            f"{len(pending['facts']) + pending['collapsed']} событий. Это факты, а не "
            f"повтор сообщений — исходные сообщения НЕ пересылались.]"
        )
        return f"{head}\n" + "\n".join(lines) + f"\n---\n{message}", pending["keys"]

    def _ack_pending_facts(self, keys: list[str]) -> None:
        """Погасить факты, которые уехали в бэкенд. Только после возврата из send."""
        if not keys:
            return
        try:
            from app.db import ack_facts

            ack_facts(self.id, keys)
        except Exception as error:
            logger.warning(f"[{self.name}] could not ack delivered facts: "
                           f"{type(error).__name__}: {error}")

    def _spawn_bg(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        def _on_done(t):
            self._background_tasks.discard(t)
            if not t.cancelled():
                exc = t.exception()
                if exc:
                    logger.warning(f"[{self.name}] background task failed: {exc}")
        task.add_done_callback(_on_done)
        return task

    async def start(
        self,
        initial_message: str | None = None,
        *,
        persist: bool = True,
    ) -> None:
        if initial_message and not persist:
            raise ValueError("unpublished session cannot accept an initial message")
        if initial_message:
            await self.send(initial_message)
        else:
            self.status = AgentStatus.IDLE
            if persist:
                self._persist()

    async def abort_unpublished(self) -> None:
        """Close preparation resources without logs or database persistence."""
        self._turns.cancel_auto_report()
        if self._precompact_timer_task and not self._precompact_timer_task.done():
            self._precompact_timer_task.cancel()
        self._precompact_timer_task = None
        self._precompact_timer = None
        current = asyncio.current_task()
        tasks = [
            task for task in (*self._background_tasks, self._persist_task)
            if task is not None and task is not current and not task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._background_tasks.clear()
        self._persist_task = None
        self._persist_dirty = False
        await self._disconnect_backend()
        self._listen_task = None
        self._heartbeat_task = None
        self._hibernate_task = None
        self.status = AgentStatus.IDLE

    async def wait_for_turn_completion(self) -> bool:
        """Wait for the active logical turn to publish its terminal status."""
        while self.status == AgentStatus.RUNNING:
            await self._turn_finished_event.wait()
        return self.status == AgentStatus.IDLE

    async def send(self, message: str) -> None:
        original_user_message = message
        # Retry budgets belong to one logical request. A real new message resets both;
        # each internal retry preserves only its own failure class.
        if not message.startswith("[system] Retrying after rate limit."):
            self._rate_limit_retries = 0
        if not message.startswith("[system] Retrying after transient server error."):
            self._server_error_retries = 0
            self._session_limit_hit = False
        self._safeguard_refusal = ""

        self._note_next_precompact_activity()
        capabilities = get_runtime(self.backend_type).capabilities
        async with self._lifecycle_lock:
            if self._compacting:
                self._pending_messages.append(message)
                self._log("user_message", message)
                self._log("status", f"message queued (compact in progress, {len(self._pending_messages)} pending)")
                return
            if self.status == AgentStatus.RUNNING:
                self._log("user_message", message)
                if not capabilities.mid_turn_inject:
                    self._pending_messages.append(message)
                    self._log("status", f"message queued ({len(self._pending_messages)} pending)")
                    return
                try:
                    backend = await self._ensure_backend()
                    injected, fact_keys = self._attach_pending_facts(message)
                    await backend.send(injected)
                    self._ack_pending_facts(fact_keys)
                    if self.backend_type == "codex":
                        self._log("status", "message steered into active Codex turn")
                    return
                except Exception as e:
                    logger.warning(f"[{self.name}] mid-turn inject failed, queueing: {e}")
                    self._pending_messages.append(message)
                    self._log("status", f"inject failed, queued ({len(self._pending_messages)} pending)")
                    if self.status != AgentStatus.RUNNING and not self._compacting:
                        self._spawn_bg(self._flush_pending())
                return

            if self._hibernate_task and not self._hibernate_task.done():
                self._hibernate_task.cancel()
                self._hibernate_task = None

            if self._hibernated:
                logger.info(f"[{self.name}] waking from hibernate")
                self._hibernated = False

            self.progress_pct = 0
            self.progress_status = ""
            self._log("user_message", message)

            did_inject = False
            pending_th = ""
            templates_changed = False
            if self.session_id and self._current_prompt and not self._prompt_injected:
                # Inject updated system prompt once per session — workers list, role
                # catalog, and template content drift as other agents spawn/die.
                # Only on first message after resume; subsequent turns use cached prompt.
                current_th = prompt_template_hash(self.role)
                old_th = self._template_hash or current_th
                templates_changed = old_th != current_th
                pending_th = current_th
                # Personal memory is re-read here, not reused from the assembled string:
                # the prompt is built at spawn / _load_from_db, so anything the agent
                # wrote to its own memory since then would otherwise wait for a restart.
                self._current_prompt = refresh_worker_memory(
                    self._current_prompt, self.name, self.role, self.scope
                )
                message = f"[Orchestra platform note: {'your role instructions were updated.' if templates_changed else 'refreshed context (worker list, etc.).'} This is from the server, not another agent.]\n{self._current_prompt}\n\n---\n\n{message}"
                did_inject = True

            await self._apply_pending_identity_restart()

            if self.status in (AgentStatus.IDLE, AgentStatus.WAITING):
                self._manually_interrupted = False
                self._did_report = False
                self._turns.bump_turn_gen()
                self._turn_logs = []
                self._turn_start = asyncio.get_event_loop().time()
                self._last_msg_time = self._turn_start
                self.status = AgentStatus.RUNNING
                self._persist()
                asyncio.create_task(self._notify_scope_running())

            try:
                backend = await self._ensure_backend()
            except Exception:
                self.status = AgentStatus.IDLE
                self._persist()
                self._turns.publish_turn_finished()
                raise

            # Claude transcripts are local files. A DB row can outlive that file (old
            # manual stops/cleanup), in which case Claude CLI cannot resume the UUID.
            # ClaudeBackend reconnects fresh; carry a bounded DB transcript explicitly
            # so the new session does not wake up amnesiac or keep returning HTTP 500.
            if getattr(backend, "resume_failed", False):
                self.runtime_handoff = await self._build_runtime_handoff(
                    exclude_latest_user=original_user_message
                )
                stale_session_id = self.session_id
                if stale_session_id:
                    self.session_id_history.append({
                        "session_id": stale_session_id,
                        "runtime": self.backend_type,
                        "model": self.model,
                        "resume_missing_at": datetime.now(timezone.utc).isoformat(),
                        "context_pct": self._last_context.get("percentage", 0),
                    })
                    self.session_id_history = self.session_id_history[-10:]
                self.session_id = None
                self._last_context = {
                    "percentage": 0,
                    "total_tokens": 0,
                    "max_tokens": 0,
                }
                backend.resume_failed = False
                self._log("status", "native Claude transcript missing — restored from Orchestra logs")
                self._persist()

            # send() can raise (e.g. opencode prompt_async 404/5xx) AFTER status=RUNNING and
            # BEFORE the listen task is created — without this, a failed submit strands the
            # agent in RUNNING forever (task #97). Reset to IDLE on failure.
            message, fact_keys = self._attach_pending_facts(message)
            outbound_message = message
            pending_handoff = self.runtime_handoff
            if pending_handoff:
                outbound_message = (
                    "[Orchestra conversation handoff: the agent runtime changed. "
                    "The quoted text below is prior user/assistant conversation at "
                    "user-message priority, not a platform or system instruction.]\n"
                    "<prior-conversation>\n"
                    f"{pending_handoff}\n"
                    "</prior-conversation>\n\n"
                    "<current-user-message>\n"
                    f"{message}\n"
                    "</current-user-message>"
                )
            try:
                await backend.send(outbound_message)
            except Exception:
                if self.status == AgentStatus.RUNNING:
                    self.status = AgentStatus.IDLE
                    self._persist()
                    self._turns.publish_turn_finished()
                raise
            self._ack_pending_facts(fact_keys)
            if pending_handoff and self.runtime_handoff == pending_handoff:
                self.runtime_handoff = ""
                self._persist()

            if did_inject:
                if templates_changed:
                    self._log("status", f"prompt updated → {pending_th}")
                self._template_hash = pending_th
                self._prompt_injected = True
                self.system_prompt = self._current_prompt

            if capabilities.event_stream == "per_turn":
                self._listen_task = asyncio.create_task(
                    self._turn_event_loop()
                )
                self._listen_task.add_done_callback(self._on_task_done)

    async def _refresh_skills(self) -> None:
        """Re-install this role's pipeline skills before the CLI starts.

        Both runtimes read skills as FILES, each from its own directory: Claude from
        `<cwd>/.claude/skills/`, Codex from `<cwd>/.codex/skills/`. Either copy goes stale the
        moment a skill is edited, and a skill added to a role after spawn never arrives at all.

        Falls back to `self.cwd` when there is no worktree — orchestrators run without one,
        which is why a worktree-only injection reached none of them.
        """
        home_dir = _SKILL_HOME_DIRS.get(self.backend_type)
        if not home_dir:
            return
        path = self.worktree_path or self.cwd
        if not path:
            return
        try:
            from app.pipeline import get_role
            role = get_role(self.pipeline, self.role)
            skills = role.skills if role else None
            # "all" means the CLI discovers skills itself — nothing to copy.
            if not skills or skills == "all":
                return
            await asyncio.to_thread(inject_skills_to_worktree, skills, path, home_dir)
        except Exception as e:
            logger.warning(f"[{self.name}] skill refresh failed: {e}")
    async def _apply_pending_identity_restart(self) -> bool:
        """Погасить бэкенд, если имя сменилось, — но только на ГРАНИЦЕ хода.

        Дисконнект внутри живого хода оборвал бы его, поэтому в RUNNING только копим
        флаг. Упавший ход флаг не съедает: он доживает до начала следующего, а если
        коннекта не станет вовсе (гибернация, рестарт), новый бэкенд и так строится из
        уже пересобранного `mcp_servers`. Повторный вызов — no-op.
        """
        if not self._identity_stale or self.status == AgentStatus.RUNNING:
            return False
        self._identity_stale = False
        self._log("status", "identity changed — restarting MCP subprocess")
        await self._disconnect_backend()
        return True

    async def _ensure_backend(self, force_fresh: bool = False):
        if self._backend is not None:
            if not force_fresh:
                return self._backend
            await self._disconnect_backend()
        if self.worktree_path:
            # Codex reads AGENTS.md, not CLAUDE.md. Refresh the mirror before the CLI starts,
            # otherwise a long-lived worker keeps the project rules from its spawn day.
            try:
                from app.workspace import sync_agents_md
                await asyncio.to_thread(sync_agents_md, self.worktree_path)
            except Exception as e:
                logger.warning(f"[{self.name}] AGENTS.md mirror refresh failed: {e}")
        await self._refresh_skills()
        self._backend = self._make_backend(force_fresh=force_fresh)
        candidate = self._backend
        try:
            await candidate.connect()
        except Exception as e:
            logger.error(f"[{self.name}] backend connect failed: {err_text(e)}")
            self._log("error", f"connect failed: {err_text(e)}")
            if not getattr(candidate, "has_owned_processes", False):
                self._backend = None
            raise
        capabilities = get_runtime(self.backend_type).capabilities
        if capabilities.event_stream == "persistent":
            self._listen_task = asyncio.create_task(self._persistent_event_loop())
            self._listen_task.add_done_callback(self._on_task_done)
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._hibernate.heartbeat_loop())
        return self._backend

    # ── Event loops ──

    MAX_CONSECUTIVE_FAILURES = 5

    async def _persistent_event_loop(self) -> None:
        logger.info(f"[{self.name}] {self.backend_type} persistent event loop started")
        consecutive_failures = 0
        while True:
            try:
                if self._backend is None:
                    logger.warning(f"[{self.name}] event loop: backend is None, exiting")
                    return
                async for event in self._backend.events():
                    self._last_msg_time = asyncio.get_event_loop().time()
                    self._handle_event(event)
                    consecutive_failures = 0
                # Persistent streams may return without error when the upstream closes.
                # During shutdown/restart this is normal — don't spam the user
                if self.status == AgentStatus.IDLE:
                    logger.info(f"[{self.name}] listener stream ended (agent idle/stopped — normal on restart)")
                    return
                consecutive_failures += 1
                logger.warning(f"[{self.name}] events() exhausted normally (attempt {consecutive_failures}/{self.MAX_CONSECUTIVE_FAILURES})")
                self._log("status", f"listener stream ended unexpectedly (attempt {consecutive_failures})")
            except asyncio.CancelledError:
                logger.info(f"[{self.name}] persistent event loop cancelled")
                return
            except Exception as e:
                consecutive_failures += 1
                import traceback
                tb = traceback.format_exc()
                logger.error(f"[{self.name}] persistent event loop died: {e}\n{tb}")
                self._log("error", f"listener died (attempt {consecutive_failures}): {e}")

            if consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                logger.error(f"[{self.name}] reconnect limit reached ({consecutive_failures} consecutive failures), giving up")
                self._log("error", f"backend unstable: {consecutive_failures} consecutive failures, giving up")
                self._turn_start = 0
                await self._disconnect_backend()
                if self.status == AgentStatus.RUNNING:
                    self.status = AgentStatus.IDLE
                    self._persist()
                    self._turns.publish_turn_finished()
                return

            try:
                if self._backend is None:
                    return
                await self._backend.reconnect()
                logger.info(f"[{self.name}] listener reconnected after error")
                self._log("status", "listener reconnected")
                if self.status == AgentStatus.RUNNING:
                    await self._backend.send("[system] Connection was restored after interruption. Continue your work.")
                continue
            except Exception as re_err:
                logger.error(f"[{self.name}] listener reconnect failed: {err_text(re_err)}")
                self._log("error", f"listener reconnect failed: {err_text(re_err)}")
                self._backend = None
                if self.status == AgentStatus.RUNNING:
                    self.status = AgentStatus.IDLE
                    self._persist()
                    self._turns.publish_turn_finished()
                return

    async def _turn_event_loop(self) -> None:
        logger.info(f"[{self.name}] {self.backend_type} turn started")
        try:
            async for event in self._backend.events():
                self._last_msg_time = asyncio.get_event_loop().time()
                # thread.started is emitted before turn.completed. Store it now so an
                # interrupted long turn can resume instead of silently starting fresh.
                early_session_id = event.metadata.get("session_id") if event.type == "status" else None
                if early_session_id and early_session_id != self.session_id:
                    self.session_id = early_session_id
                    self._persist()
                self._handle_event(event)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f"[{self.name}] {self.backend_type} turn error: {e}")
            self._log("error", f"{self.backend_type} turn error: {e}")
        finally:
            if self.status == AgentStatus.RUNNING:
                self.status = AgentStatus.IDLE
                self._persist()
                if self._pending_messages:
                    self._spawn_bg(self._flush_pending())
                else:
                    self._hibernate.schedule()

    # ── Unified event handler ──

    def _handle_event(self, event: AgentEvent) -> None:
        if event.type == "stream":
            # Live partials: push to in-memory broker for SSE fan-out, NEVER persist.
            # The final "text" event (below) is the DB source of truth.
            from app.live_broker import broker
            broker.publish(self.id, {"type": "stream", "content": event.content})
            return
        if event.type == "subagent_stream":
            # Live sub-agent output → broker only (ephemeral, like main stream).
            # subagent_id lets the UI nest it under the right sub-agent block.
            from app.live_broker import broker
            broker.publish(self.id, {"type": "subagent_stream", "content": event.content,
                                     "subagent_id": event.metadata.get("subagent_id", "")})
            return
        if event.type in ("thinking_stream", "tool_stream", "tool_patch", "turn_diff"):
            # Codex app-server exposes fine-grained activity that is valuable live but
            # would flood the DB. The authoritative thinking/tool/file events are still
            # persisted when their item completes.
            from app.live_broker import broker
            payload = {"type": event.type, "content": event.content}
            for key in ("activity", "item_id", "tool_use_id", "turn_id", "stream"):
                value = event.metadata.get(key)
                if value:
                    payload[key] = value
            broker.publish(self.id, payload)
            return
        tool_use_id = str(event.metadata.get("tool_use_id") or "")
        if event.type == "tool_use" and tool_use_id:
            self._tool_names_by_id[tool_use_id] = (
                event.metadata.get("tool_name") or "unknown"
            )
        elif event.type == "tool_result" and tool_use_id:
            remembered_name = self._tool_names_by_id.pop(tool_use_id, "unknown")
            tool_name = event.metadata.get("tool_name") or remembered_name
            if event.metadata.get("is_error"):
                self._submit_db_write(
                    tool_error_add,
                    self.name,
                    self.scope,
                    tool_name,
                    event.content,
                    runtime=self.backend_type,
                    tool_use_id=tool_use_id,
                )
        # Sub-agent tool_use/text/tool_result (tagged with subagent_id) → broker ONLY
        # (ephemeral live nesting under the sub-agent block). NOT persisted — the DB
        # record is subagent_start/end; persisting these too would double-render them
        # (once in the accordion via broker, once in the main flow on reload).
        sub_id = event.metadata.get("subagent_id")
        if sub_id and event.type in ("tool_use", "tool_result", "text", "thinking"):
            from app.live_broker import broker
            broker.publish(self.id, {"type": "subagent_event", "event_type": event.type,
                                     "content": event.content[:2000], "subagent_id": sub_id})
            return
        if event.type == "text":
            from app.live_broker import broker
            broker.clear_accum(self.id)
            # Subscription limits arrive as text before the generic rate_limit error.
            if _is_terminal_subscription_limit(event.content):
                self._session_limit_hit = True
            # Отказ фильтра приходит текстом; относительно события `error` его порядок
            # НЕПОСТОЯНЕН (замер #155: в одном ходе текст раньше, в другом позже), поэтому
            # здесь только ставим флаг, а решение принимаем на turn_end — он всегда последний.
            if _is_safeguard_refusal(event.content):
                self._safeguard_refusal = event.content
            self._log("text", event.content)
            self._turn_logs.append(event.content)
        elif event.type == "thinking":
            self._log("thinking", event.content)
        elif event.type == "tool_use":
            self.total_tool_calls += 1
            self._log("tool", event.content)
            short = event.content[:80]
            self._turn_logs.append(f"[tool] {short}")
            tool_name = event.metadata.get("tool_name", event.content)
            if "send_message" in tool_name or "mcp__orchestra__send_message" in tool_name:
                self._did_report = True
        elif event.type == "tool_result":
            # Запись картинок в блобы (#78) ВЫКЛЮЧЕНА: клиентской половины нет — фронт не
            # знает типа `blob`, и первая же картинка перестала бы показываться. Хранилище
            # и чтение (`app/blobs.py`, `GET /api/blobs/...`) оставлены инертными до
            # разморозки #78; включать запись только вместе с фронтом.
            self._log("tool_result", event.content)
        elif event.type == "file_change":
            self._log("tool", f"file: {event.content}")
            self._turn_logs.append(f"[tool] file: {event.content[:60]}")
        elif event.type in ("plan", "warning", "review"):
            self._log(event.type, event.content)
        elif event.type == "turn_end":
            self._turns.handle_turn_end(event)
        elif event.type == "error":
            # rate_limit → single retry-status log (skip raw error to avoid duplicate
            # "model error: rate_limit" + "rate limited — retry" on one event)
            if "rate_limit" in event.content:
                # Terminal subscription/usage limits — never retry
                if self._session_limit_hit or _is_terminal_subscription_limit(event.content):
                    self._log("error", "⏳ subscription limit — ждём сброса квоты. НЕ ретраим")
                elif self._rate_limit_retries < self.RATE_LIMIT_MAX_RETRIES:
                    self._rate_limit_retries += 1
                    delay = self.RATE_LIMIT_DELAY * self._rate_limit_retries
                    self._log("status", f"⏳ rate limit (Anthropic сервер) — повтор через {delay}s ({self._rate_limit_retries}/{self.RATE_LIMIT_MAX_RETRIES})")
                    self._spawn_bg(self._rate_limit_retry(delay))
                else:
                    self._log("error", f"rate limit — gave up after {self.RATE_LIMIT_MAX_RETRIES} retries")
            else:
                self._log("error", event.content)
        elif event.type == "subagent_start":
            self._log("subagent_start", event.content)
            self._persist_subagent(event.metadata)
        elif event.type == "subagent_progress":
            self._log("subagent_progress", event.content)
            self._persist_subagent(event.metadata)
        elif event.type == "subagent_end":
            self._log("subagent_end", event.content)
            self._persist_subagent(event.metadata, ended=True)
        elif event.type == "status":
            self._log("status", event.content)

    async def _flush_pending(self) -> None:
        # Brief delay: let the just-finished turn fully settle (persist, hibernate schedule)
        # before starting the next one — avoids nested lock acquisition from the same coroutine
        await asyncio.sleep(0.3)
        async with self._lifecycle_lock:
            if self._compacting or self.status == AgentStatus.RUNNING:
                return
            if not self._pending_messages:
                return
            msgs = list(self._pending_messages)
            self._pending_messages.clear()
            if len(msgs) == 1:
                combined = msgs[0]
            else:
                # Batch queued messages into one turn to avoid spawning N sequential turns —
                # each turn has ~3s round-trip overhead and occupies the lifecycle lock
                combined = "\n".join(
                    f"--- message {i+1}/{len(msgs)} ---\n{m}"
                    for i, m in enumerate(msgs)
                )
            self._log("status", f"delivering {len(msgs)} queued message(s)")
            try:
                self._manually_interrupted = False
                self._did_report = False
                self._turns.bump_turn_gen()
                self._turn_logs = []
                self._turn_start = asyncio.get_event_loop().time()
                self._last_msg_time = self._turn_start
                self.status = AgentStatus.RUNNING
                self._persist()
                self._hibernated = False
                backend = await self._ensure_backend()
                combined, fact_keys = self._attach_pending_facts(combined)
                await backend.send(combined)
                self._ack_pending_facts(fact_keys)
                if get_runtime(self.backend_type).capabilities.event_stream == "per_turn":
                    self._listen_task = asyncio.create_task(self._turn_event_loop())
                    self._listen_task.add_done_callback(self._on_task_done)
            except Exception as e:
                logger.error(f"[{self.name}] flush pending failed: {e}")
                self._pending_messages[0:0] = msgs
                self.status = AgentStatus.IDLE
                self._persist()
                self._turns.publish_turn_finished()

    def _on_task_done(self, task: asyncio.Task) -> None:
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc:
            import traceback
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            logger.error(f"[{self.name}] listen task died with exception: {exc}\n{tb}")
            self._log("error", f"listen task died: {exc}")
            self._turn_start = 0
            self.status = AgentStatus.IDLE
            self._log("error", f"listen task exception: {exc}")
            self._persist()
        else:
            logger.warning(f"[{self.name}] listen task exited without exception (silent death), status={self.status}")
            if self.status == AgentStatus.RUNNING:
                self._log("error", "listen task exited unexpectedly while RUNNING")
                self._turn_start = 0
                self.status = AgentStatus.IDLE
                self._persist()
        if self.status != AgentStatus.RUNNING and self._auto_continue_count == 0:
            self._turns.publish_turn_finished()

    # ── Session operations ──

    async def hibernate_now(self) -> dict:
        return await self._hibernate.hibernate_now(manual=True)

    async def interrupt(self) -> None:
        async with self._lifecycle_lock:
            backend = self._backend if self.status == AgentStatus.RUNNING else None
            # Publish the stop before waiting for the SDK control acknowledgement. This
            # prevents concurrent messages from being injected into the turn being
            # interrupted; they will start a clean turn after this lock is released.
            self._turns.cancel_auto_report()
            self._cancel_precompact_timer("interrupt")
            self._turn_start = 0
            self._manually_interrupted = True
            self.status = AgentStatus.IDLE
            self._log("status", "interrupted")
            self._persist()
            self._turns.publish_turn_finished()

            if backend:
                acknowledged = await backend.interrupt()
                if acknowledged is False and self._backend is backend:
                    self._log("error", "interrupt was not acknowledged; disconnecting backend")
                    await self._disconnect_backend()

    async def _compact_codex_context(self) -> dict:
        if self._compacting:
            return {"ok": False, "error": "compact already in progress"}
        if self.status == AgentStatus.RUNNING:
            return {"ok": False, "error": "cannot compact while agent is running"}

        if self._precompact_timer and not self._precompact_timer.get("fired_at"):
            self._cancel_precompact_timer("manual_compact")
        self._compacting = True
        before_pct = self._last_context.get("percentage", 0)
        thread_id = self.session_id
        self._log(
            "status",
            f"compact started (native Codex, context {before_pct}%, thread={thread_id})",
        )
        try:
            async with self._lifecycle_lock:
                backend = await self._ensure_backend()
                compact_context = getattr(backend, "compact_context", None)
                if not callable(compact_context):
                    raise RuntimeError("Codex backend does not support native compact")
                self._hibernated = False
            result = await compact_context()

            context_tokens = result.get("context_tokens")
            max_tokens = result.get("max_tokens")
            if isinstance(max_tokens, int) and max_tokens > 0:
                self._last_context["max_tokens"] = max_tokens
            if isinstance(context_tokens, int) and context_tokens >= 0:
                self._last_context["total_tokens"] = context_tokens
                if isinstance(max_tokens, int) and max_tokens > 0:
                    self._last_context["percentage"] = round(
                        context_tokens * 100 / max_tokens
                    )

            after_pct = self._last_context.get("percentage", 0)
            summary = result.get("summary")
            if not summary:
                try:
                    summary = await self._build_runtime_handoff()
                except Exception as exc:
                    logger.debug(f"[{self.name}] Codex compact handoff snapshot failed: {exc}")
            if summary:
                self.last_summary = _bounded_summary(summary)
            self._persist()
            await self._drain_persist()
            self._log(
                "status",
                f"compact done (native Codex): {before_pct}% → {after_pct}%, "
                f"thread={self.session_id}",
            )
            return {
                "ok": True,
                "mode": "native",
                "before_pct": before_pct,
                "after_pct": after_pct,
                "thread_id": self.session_id,
                "context_tokens": context_tokens,
            }
        except Exception as exc:
            self._log("error", f"native Codex compact failed: {exc}")
            return {
                "ok": False,
                "mode": "native",
                "error": str(exc),
                "before_pct": before_pct,
                "thread_id": self.session_id,
            }
        finally:
            self._compacting = False
            if self._pending_messages:
                self._spawn_bg(self._flush_pending())
            elif self.status == AgentStatus.IDLE:
                self._hibernate.schedule()

    async def compact(self) -> dict:
        if self.backend_type == "codex":
            return await self._compact_codex_context()

        # #106 Q6: hot_state_ledger bundle. Bounded promotion replaces the old
        # unconditional CLAUDE.md/TODO.md/BUGS.md presave, which drove 218
        # unrelated writes across 63 measured outputs (candidate: 0).
        COMPACT_PROMPT = (
            "[SYSTEM: Context compaction requested — structured handoff]\n\n"
            "Before writing the handoff, promote a durable fact only when the conversation explicitly "
            "names an existing canonical Markdown path and the exact fact to store. Update only that "
            "path, preserve unrelated content, and make the write idempotent. Otherwise do not write "
            "files. Never create CLAUDE.md, TODO.md, BUGS.md, or a new note solely for compaction. "
            "Never write credentials.\n\n"
            "Write a compact task-state handoff from supported evidence only.\n\n"
            "TASK STATE\n"
            "- Current objective, phase, and evidence-backed status.\n\n"
            "DECISIONS\n"
            "- Only active decisions and reversals needed to continue; retain provisional/final state "
            "and rationale.\n\n"
            "BLOCKER / NEXT\n"
            "- Current blocker and owner if known; then the single next executable action. If "
            "continuity is uncertain, write `UNKNOWN — source gap` instead of guessing.\n\n"
            "CONSTRAINTS\n"
            "- Still-active user preferences, safety constraints, and unresolved conflicts. Distinguish "
            "durable preferences from one-off instructions.\n\n"
            "Preserve the last three user messages verbatim, including exact commands, paths, numbers, "
            "and error strings.\n\n"
            "Do not claim a file was read, changed, committed, deployed, or tested unless the "
            "conversation or tool evidence says so. Do not assert the negative either: absence of a "
            "tool event means the outcome is unknown, not that the action did not happen. Write "
            "`no evidence of X` rather than `X did not happen`. A measured empty diff supports only "
            "`not modified`; it never supports `not read`. Omit redundant tool output and all "
            "credentials. Output only these four short sections."
        )
        PREAMBLE = "[PREVIOUS CONTEXT SUMMARY — context was compacted]\n\n{summary}\n\n[END OF SUMMARY — continue naturally]\n\n"
        COMPACT_MAX_RETRIES = 3
        COMPACT_RETRY_DELAY = 30
        COMPACT_MIN_SUMMARY_LEN = 200
        _GARBAGE_PATTERNS = ["rate limit", "rate_limit", "api error", "overloaded", "temporarily limiting", "server error", "session limit", "hit your session"]

        if self._compacting:
            return {"ok": False, "error": "compact already in progress"}
        if self.status == AgentStatus.RUNNING:
            return {"ok": False, "error": "cannot compact while agent is running"}
        if _claude_subscription_limit_active():
            error = "Claude subscription limit active; compact postponed until quota reset"
            self._log("error", error)
            return {"ok": False, "error": error}
        self._session_limit_hit = False
        self._compacting = True
        before_pct = self._last_context.get("percentage", 0)
        pre_compact_session_id = self.session_id
        self._log("status", f"compact started (context {before_pct}%, pre_session={pre_compact_session_id})")

        def abort_compact(error: str) -> dict:
            self.session_id = pre_compact_session_id
            self._compacting = False
            if self._pending_messages:
                self._spawn_bg(self._flush_pending())
            return {"ok": False, "error": error, "before_pct": before_pct}

        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"[{self.name}] listen task failed during compact: {e}")

        summary = ""
        last_error = ""
        for attempt in range(1, COMPACT_MAX_RETRIES + 1):
            summary_parts = []
            backend = self._backend or self._make_backend()
            need_connect = self._backend is None
            try:
                async with self._lifecycle_lock:
                    if need_connect:
                        await backend.connect()
                    await backend.send(COMPACT_PROMPT)
                    async for event in backend.events():
                        if event.type == "text":
                            summary_parts.append(event.content)
                        elif event.type == "tool":
                            self._log("tool", event.content)
                            summary_parts.append(f"\n[tool] {event.content[:200]}\n")
                        elif event.type == "tool_result":
                            self._log("tool_result", event.content[:500])
                            summary_parts.append(f"\n[tool_result] {event.content[:200]}\n")
                        elif event.type == "turn_end":
                            if event.metadata.get("session_id"):
                                self.session_id = event.metadata["session_id"]
                            break
            except Exception as e:
                last_error = str(e)
                self._log("error", f"compact attempt {attempt}/{COMPACT_MAX_RETRIES} failed: {e}")
                try:
                    await backend.disconnect()
                except Exception:
                    pass
                self._backend = None
                if attempt < COMPACT_MAX_RETRIES:
                    self._log("status", f"compact retry in {COMPACT_RETRY_DELAY * attempt}s...")
                    await asyncio.sleep(COMPACT_RETRY_DELAY * attempt)
                    continue
                return abort_compact(last_error)
            finally:
                try:
                    await backend.disconnect()
                except Exception:
                    pass
                self._backend = None

            summary = "".join(summary_parts).strip()

            summary_lower = summary.lower()
            terminal_limit = (
                len(summary) < COMPACT_MIN_SUMMARY_LEN
                and summary.count("\n") <= 2
                and _is_terminal_subscription_limit(summary)
            )
            provider_error = (
                len(summary) < COMPACT_MIN_SUMMARY_LEN
                and summary.count("\n") <= 2
                and any(pattern in summary_lower for pattern in _GARBAGE_PATTERNS)
            )
            if not summary:
                last_error = "empty summary"
            elif terminal_limit:
                last_error = "Claude subscription limit active; compact aborted"
            elif provider_error:
                last_error = "provider error returned instead of compact summary"
            else:
                last_error = ""

            if last_error:
                self._log("error", f"compact attempt {attempt}/{COMPACT_MAX_RETRIES}: {last_error}")
                self.session_id = pre_compact_session_id
                if not terminal_limit and attempt < COMPACT_MAX_RETRIES:
                    self._log("status", f"compact retry in {COMPACT_RETRY_DELAY * attempt}s...")
                    await asyncio.sleep(COMPACT_RETRY_DELAY * attempt)
                    continue
                return abort_compact(last_error)

            if attempt > 1:
                self._log("status", f"compact succeeded on attempt {attempt}")
            break

        preamble = PREAMBLE.format(summary=summary)
        self._compact_ack_event = asyncio.Event()
        ack_event = self._compact_ack_event
        try:
            async with self._lifecycle_lock:
                self._manually_interrupted = False
                self._did_report = False
                self._turns.bump_turn_gen()
                self._compact_ack_gen = self._turn_gen
                self._turn_logs = []
                self._turn_start = asyncio.get_event_loop().time()
                self._last_msg_time = self._turn_start
                self.status = AgentStatus.RUNNING
                self._persist()
                backend = await self._ensure_backend(force_fresh=True)
                self._log("user_message", preamble + "Acknowledge briefly.")
                await backend.send(preamble + "Acknowledge briefly.")

            try:
                await asyncio.wait_for(ack_event.wait(), timeout=60)
            except asyncio.TimeoutError:
                self._log("error", "compact ack turn did not complete (60s)")
                # stop the still-running ack turn so it can't interleave with the next send
                await self._disconnect_backend()
                self.session_id = pre_compact_session_id
                self.status = AgentStatus.IDLE
                self._persist()
                self._turns.publish_turn_finished()
                return {"ok": False, "error": "ack turn did not complete", "before_pct": before_pct}
            if self._session_limit_hit:
                error = "Claude subscription limit hit during compact acknowledgement"
                self._log("error", error)
                await self._disconnect_backend()
                self.session_id = pre_compact_session_id
                self.status = AgentStatus.IDLE
                self._persist()
                self._turns.publish_turn_finished()
                return {"ok": False, "error": error, "before_pct": before_pct}
        finally:
            self._compact_ack_event = None
            self._compact_ack_gen = -1
            self._compacting = False
            if self._pending_messages:
                self._spawn_bg(self._flush_pending())

        self.last_summary = _bounded_summary(summary)
        # compact() hands the session a NEW native session_id, and every later
        # reconnect resumes it — a resumed CLI is never given system_prompt, so the
        # role would only survive in whatever the summary happened to mention.
        # Re-arm the injector so the next turn re-delivers it. Success path only:
        # on the abort branches the pre-compact session is restored and its prompt
        # is still live, so resetting there would buy a needless full re-inject.
        self._prompt_injected = False
        if pre_compact_session_id:
            self.session_id_history.append({
                "session_id": pre_compact_session_id,
                "runtime": self.backend_type,
                "model": self.model,
                "compacted_at": datetime.now(timezone.utc).isoformat(),
                "context_pct": before_pct,
            })
            self.session_id_history = self.session_id_history[-10:]
        self._persist()
        await self._drain_persist()
        if LOG_COMPACT_SUMMARY:
            self._log("text", f"📋 **Compact summary:**\n\n{summary}")
        after_pct = self._last_context.get("percentage", 0)
        self._log("status", f"compact done: {before_pct}% → {after_pct}% (summary {len(summary)} chars)")
        return {"ok": True, "before_pct": before_pct, "after_pct": after_pct, "summary_chars": len(summary), "summary": summary}

    async def _notify_scope_idle(self) -> None:
        # wired callback (set by tg_bridge.start_bridge) — session does not import tg_bridge
        if on_scope_idle is None:
            return
        try:
            await on_scope_idle(self)
        except Exception as e:
            logger.warning(f"[{self.name}] TG scope-idle notify failed: {e}")

    async def _notify_scope_running(self) -> None:
        if on_scope_running is None:
            return
        try:
            await on_scope_running(self)
        except Exception as e:
            logger.warning(f"[{self.name}] TG scope-running notify failed: {e}")

    async def _rate_limit_retry(self, delay: int) -> None:
        await asyncio.sleep(delay)
        try:
            await self.send("[system] Retrying after rate limit. Continue where you left off.")
            logger.info(f"[{self.name}] rate-limit retry after {delay}s")
        except Exception as e:
            logger.warning(f"[{self.name}] rate-limit retry failed: {e}")
            self.status = AgentStatus.IDLE
            self._persist()
            self._turns.publish_turn_finished()

    async def _retry_after_server_error(self, delay: int, expected_turn_gen: int) -> None:
        """Resume through a fresh SDK transport after an upstream stream failure."""
        await asyncio.sleep(delay)
        try:
            async with self._lifecycle_lock:
                # A real user message already started a newer turn; it supersedes this
                # automatic retry and must not be duplicated.
                if self._turn_gen != expected_turn_gen or self.status != AgentStatus.IDLE:
                    return
                await self._disconnect_backend()
            await self.send(
                "[system] Retrying after transient server error. Continue where you "
                "left off. Do not repeat completed research; execute the pending "
                "deliverable now."
            )
            logger.info(f"[{self.name}] server-error retry after {delay}s")
        except Exception as e:
            logger.warning(f"[{self.name}] server-error retry failed: {e}")
            self.status = AgentStatus.IDLE
            self._persist()
            self._turns.publish_turn_finished()

    async def _auto_continue(self) -> None:
        await asyncio.sleep(1)
        try:
            await self.send("[system] Turn limit reached. Continue where you left off.")
            logger.info(f"[{self.name}] auto-continue after max_turns")
        except Exception as e:
            logger.warning(f"[{self.name}] auto-continue failed: {e}")
            self.status = AgentStatus.IDLE
            self._persist()
            self._turns.publish_turn_finished()

    async def _refresh_context_from_api(
        self, *, schedule_compaction_on_success: bool = False,
    ) -> None:
        if not self._backend or not hasattr(self._backend, 'context_usage'):
            return
        try:
            usage = await asyncio.wait_for(self._backend.context_usage(), timeout=5)
            if usage and usage.get("percentage") is not None:
                raw_max = usage.get("raw_max_tokens") or usage.get("max_tokens")
                context = current_context(
                    usage.get("total_tokens"),
                    raw_max,
                    percentage=usage.get("percentage"),
                    unknown_reason="context API omitted a current-context value",
                )
                if not isinstance(context, KnownContext):
                    self._last_context["percentage"] = 0
                    self._last_context["total_tokens"] = 0
                    self._last_context["known"] = False
                    self._log(
                        "status",
                        f"context unknown ({context.reason}); "
                        "automatic compaction skipped",
                    )
                    self._cancel_precompact_timer("context_unknown")
                    self._persist()
                    return
                old_pct = self._last_context.get("percentage", 0)
                self._last_context["percentage"] = context.percentage
                self._last_context["total_tokens"] = context.tokens
                self._last_context["max_tokens"] = context.max_tokens
                self._last_context["known"] = True
                if abs(old_pct - context.percentage) > 30:
                    logger.info(
                        f"[{self.name}] context corrected: "
                        f"{old_pct}% → {context.percentage}%"
                    )
                self._persist()
                if schedule_compaction_on_success:
                    self._turns.schedule_context_compaction(context.percentage)
        except asyncio.TimeoutError:
            logger.debug(f"[{self.name}] context refresh timeout (5s)")
        except Exception as e:
            logger.debug(f"[{self.name}] context refresh failed: {e}")

    async def _auto_compact(self) -> None:
        await asyncio.sleep(2)
        try:
            await self.compact()
        except Exception as e:
            logger.warning(f"[{self.name}] auto-compact failed: {e}")

    async def _build_runtime_handoff(self, exclude_latest_user: str = "") -> str:
        """Build a bounded provider-neutral transcript for a new native runtime."""
        if self._log_futures:
            await asyncio.gather(*tuple(self._log_futures), return_exceptions=True)
        logs = await asyncio.get_running_loop().run_in_executor(
            _db_executor(),
            lambda: get_logs(self.id, limit=120),
        )
        labels = {"user_message": "User", "text": "Assistant"}
        blocks: list[str] = []
        total = 0
        max_chars = 32_000
        skipped_latest_user = False
        for entry in reversed(logs):
            label = labels.get(entry.get("type"))
            content = str(entry.get("content") or "").strip()
            if not label or not content:
                continue
            if (
                exclude_latest_user
                and not skipped_latest_user
                and label == "User"
                and content == exclude_latest_user.strip()
            ):
                skipped_latest_user = True
                continue
            if content.startswith("[Orchestra platform note:"):
                continue
            content = content[:6_000]
            block = f"{label}:\n{content}"
            if total + len(block) > max_chars:
                remaining = max_chars - total
                if remaining > 200:
                    blocks.append(block[-remaining:])
                break
            blocks.append(block)
            total += len(block)
        return "\n\n".join(reversed(blocks))

    async def change_model(self, new_model: str) -> dict:
        old_model = self.model
        if old_model == new_model:
            return {"ok": True, "model": new_model, "changed": False}
        if self.status == AgentStatus.RUNNING:
            return {"ok": False, "error": "cannot change model while running"}

        old_runtime = self.backend_type or backend_for_model(old_model)
        new_runtime = get_model_spec(new_model).runtime
        runtime_changed = old_runtime != new_runtime
        native_session_reset = (
            runtime_changed
            or not get_runtime(new_runtime).capabilities.resume_across_models
        )
        if native_session_reset:
            if runtime_changed and self.last_summary:
                self.runtime_handoff = _bounded_summary(self.last_summary)
            else:
                self.runtime_handoff = await self._build_runtime_handoff()
            # Legacy history predates runtime/model metadata. Cross-runtime switching
            # used to be forbidden, so those native IDs belong to the current runtime.
            for entry in self.session_id_history:
                entry.setdefault("runtime", old_runtime)
                entry.setdefault("model", old_model)
            if self.session_id:
                self.session_id_history.append({
                    "session_id": self.session_id,
                    "runtime": old_runtime,
                    "model": old_model,
                    "switched_at": datetime.now(timezone.utc).isoformat(),
                })
                self.session_id_history = self.session_id_history[-10:]

        self._log(
            "status",
            f"model change: {old_model} ({old_runtime}) → {new_model} ({new_runtime})",
        )
        await self._disconnect_backend()
        if native_session_reset:
            self.session_id = None
            self._last_context = {"percentage": 0, "total_tokens": 0, "max_tokens": 0}
        self.model = new_model
        self.backend_type = new_runtime
        self._prompt_injected = False
        self._hibernated = False
        self._persist()
        snapshot = self._to_db_dict()
        await asyncio.get_running_loop().run_in_executor(_db_executor(), save_session, snapshot)
        return {
            "ok": True,
            "model": new_model,
            "old_model": old_model,
            "runtime": new_runtime,
            "old_runtime": old_runtime,
            "runtime_changed": runtime_changed,
            "native_session_reset": native_session_reset,
            "changed": True,
        }

    async def _disconnect_backend(self) -> None:
        if self._hibernate_task and not self._hibernate_task.done() and self._hibernate_task is not asyncio.current_task():
            self._hibernate_task.cancel()
            self._hibernate_task = None
        backend = self._backend
        if backend:
            await backend.disconnect()
            if self._backend is backend:
                self._backend = None
        if (self._heartbeat_task and not self._heartbeat_task.done()
                and self._heartbeat_task is not asyncio.current_task()):
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"[{self.name}] heartbeat task failed on disconnect: {e}")
            self._heartbeat_task = None
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"[{self.name}] listen task failed on disconnect: {e}")

    async def stop(self) -> None:
        # Единственный вызывающий — shutdown_all(), то есть выключение сервера
        # (пользовательский стоп идёт через interrupt()). Поэтому агент, застигнутый
        # в RUNNING, не «закончил ход», а оборван: помечаем это в БД, иначе старт
        # прочитает 'idle' и не узнает, кого будить (#160).
        interrupted = self.status == AgentStatus.RUNNING
        self._log("status", "⏹️ stopped (server shutdown)" if interrupted
                  else "⏹️ stopped (manual interrupt)")
        self._turns.cancel_auto_report()
        self._cancel_precompact_timer("stop")
        await self._disconnect_backend()
        self._hibernated = False
        self.status = AgentStatus.INTERRUPTED if interrupted else AgentStatus.IDLE
        self._persist()
        self._turns.publish_turn_finished()

    def _persist(self) -> None:
        # Coalesce rapid successive calls: mark dirty, let one active task drain them all —
        # prevents N DB writes when status/cost/context all change in the same event loop tick
        self._persist_dirty = True
        if self._persist_task and not self._persist_task.done():
            return
        self._persist_task = asyncio.get_running_loop().create_task(self._persist_loop())
        self._persist_task.add_done_callback(self._on_persist_done)

    def _on_persist_done(self, task: asyncio.Task) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[{self.name}] persist task crashed: {e}")

    async def _persist_loop(self) -> None:
        while self._persist_dirty:
            self._persist_dirty = False
            snapshot = self._to_db_dict()
            try:
                await asyncio.get_running_loop().run_in_executor(_db_executor(), save_session, snapshot)
            except Exception as e:
                logger.error(f"[{self.name}] persist failed: {e}")

    async def _drain_persist(self) -> None:
        if self._persist_task and not self._persist_task.done():
            await asyncio.gather(self._persist_task, return_exceptions=True)

    def _submit_db_write(self, operation, *args, **kwargs) -> None:
        """Run non-critical telemetry outside the event loop and surface failures."""
        future = asyncio.get_running_loop().run_in_executor(
            _db_executor(),
            partial(operation, *args, **kwargs),
        )
        self._log_futures.add(future)

        def completed(done) -> None:
            self._log_futures.discard(done)
            try:
                done.result()
            except Exception as error:
                logger.error(f"[{self.name}] telemetry write failed: {error}")

        future.add_done_callback(completed)

    def _log(self, type: str, content: str, *, event_id: str = "") -> None:
        # Fire-and-forget on dedicated DB pool — keeps event loop non-blocking for log-heavy turns
        future = asyncio.get_event_loop().run_in_executor(
            _db_executor(),
            add_log,
            self.id,
            datetime.now(timezone.utc),
            type,
            content,
            event_id,
        )
        self._log_futures.add(future)

        def completed(done) -> None:
            # Тот же способ, что у _submit_db_write выше: result() ОБЯЗАН быть забран.
            # Без него asyncio печатает своё «Future exception was never retrieved» —
            # без имени агента, без типа записи и без её содержимого (#167).
            self._log_futures.discard(done)
            try:
                done.result()
            except Exception as error:
                # logs висят на sessions(id) ON DELETE CASCADE: у записи для мёртвой
                # сессии нет дома by design, восстанавливать нечего. Но потеря обязана
                # быть ВИДНОЙ — иначе следующий FK-сбой по другой причине (битая
                # миграция, гонка при архивации) снова уйдёт в никуда.
                logger.error(
                    "[%s] log write lost (%s): %s | %.200s",
                    self.name, type, err_text(error), content,
                )

        future.add_done_callback(completed)

    def _persist_subagent(self, meta: dict, ended: bool = False) -> None:
        """Upsert sub-agent telemetry from a Task* event. Fire-and-forget.

        Only the fields the event carries are passed — subagent_upsert's
        NULLIF-COALESCE keeps prior values, so progress never wipes start's data.
        Lifecycle timestamps are captured before the executor can reorder jobs.
        """
        task_id = meta.get("subagent_id")
        if not task_id:
            return
        event_at = datetime.now(timezone.utc).isoformat()
        fields = {k: meta[k] for k in (
            "sdk_session_id", "tool_use_id", "description", "task_type", "status",
            "last_tool_name", "output_file", "summary", "raw_json",
            "total_tokens", "tool_uses", "duration_ms",
        ) if k in meta}
        if meta.get("phase") == "start":
            fields["started_at"] = event_at
        if ended or meta.get("phase") == "end":
            fields["ended_at"] = event_at
        from app.db import subagent_upsert
        asyncio.get_event_loop().run_in_executor(
            _db_executor(), lambda: subagent_upsert(self.id, task_id, **fields))

    def _to_db_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "scope": self.scope, "cwd": self.cwd,
            "model": self.model, "system_prompt": self.system_prompt,
            "status": self.status.value, "session_id": self.session_id,
            "cost_usd": self.cost_usd, "cost_usd_cached": self.cost_usd_cached,
            "context_cost": self._context_cost,
            "worktree_path": self.worktree_path,
            "branch": self.branch, "base_branch": self.base_branch,
            "needs_switch": int(self.needs_switch),
            "is_orchestrator": self.is_orchestrator,
            "role": self.role, "parent_id": self.parent_id, "parent_name": self.parent_name,
            "pipeline": self.pipeline,
            "profile": self.profile,
            "color": self.color, "created_at": self.created_at.isoformat(),
            "finished_at": None,
            "context_pct": self._last_context.get("percentage", 0),
            "context_tokens": self._last_context.get("total_tokens", 0),
            "progress_pct": self.progress_pct,
            "progress_status": self.progress_status,
            "backend_type": self.backend_type,
            "effort": self.effort or "",
            "runtime_handoff": self.runtime_handoff,
            "last_summary": self.last_summary,
            "task_id": self.task_id,
            "description": self.description,
            "total_turns": self.total_turns,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cache_read_tokens": self.total_cache_read_tokens,
            "total_cache_create_tokens": self.total_cache_create_tokens,
            "total_tool_calls": self.total_tool_calls,
            "template_hash": self._template_hash,
            "mcp_servers_custom": json.dumps(self.mcp_servers_custom) if self.mcp_servers_custom else "",
            "owned_dirs": json.dumps(self.owned_dirs) if self.owned_dirs else "",
            "tg_topic": int(self.tg_topic),
            "session_id_history": json.dumps(self.session_id_history) if self.session_id_history else "[]",
        }

    async def get_context(self) -> dict:
        return self._last_context

    def _display_status(self) -> str:
        """`broken` when the recorded worktree is gone — a missing working copy is not idleness.

        Until #62 such a worker looked perfectly `idle` and failed only at the moment a task
        was sent into a directory that no longer existed; seven of them stayed invisible that
        way for two days.
        """
        if self.worktree_path and not os.path.isdir(self.worktree_path):
            return "broken"
        return self.status.value

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "scope": self.scope,
            "cwd": self.cwd, "worktree_path": self.worktree_path,
            "status": self._display_status(), "model": self.model,
            "cost_usd": round(self.cost_usd, 4),
            "cost_usd_cached": round(self.cost_usd_cached, 4),
            "branch": self.branch,
            "base_branch": self.base_branch,
            "needs_switch": self.needs_switch,
            "is_orchestrator": self.is_orchestrator,
            "role": self.role, "parent_id": self.parent_id, "parent_name": self.parent_name,
            "color": self.color,
            "created_at": self.created_at.isoformat(),
            "context_pct": self._last_context.get("percentage", 0),
            "progress_pct": self.progress_pct,
            "progress_status": self.progress_status,
            "backend_type": self.backend_type,
            "runtime": self.backend_type,
            "provider": get_model_spec(self.model).provider,
            "hibernated": self._hibernated,
            "task_id": self.task_id,
            "description": self.description,
            "owned_dirs": self.owned_dirs,
            "tg_topic": self.tg_topic,
            "system_prompt": self.system_prompt[:500] if self.system_prompt else "",
            "total_turns": self.total_turns,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cache_read_tokens": self.total_cache_read_tokens,
            "total_cache_create_tokens": self.total_cache_create_tokens,
            "total_tool_calls": self.total_tool_calls,
        }


# ── Wired callbacks: assigned by tg_bridge.start_bridge, reset by stop_bridge.
# Session fires events without importing tg_bridge (cycle cut). Declared after
# the class — module-level annotations evaluate eagerly (PEP 526), a pre-class
# AgentSession reference would NameError on import.
on_scope_idle: "Callable[[AgentSession], Awaitable[None]] | None" = None
on_scope_running: "Callable[[AgentSession], Awaitable[None]] | None" = None
