"""HarnessBackend — Orchestra's own agent backend (BackendLike), no daemon.

A persistent in-process object: it owns an OpenRouter HTTP client, an MCP stdio client,
a JSONL session store, and the cumulative cost/token counters that must survive across
turns. Each send()/events() pair runs ONE turn through AgentLoop and emits EXACTLY ONE
turn_end (plan B2) carrying the full 15-key metadata parity of the other backends.

Cost contract (plan B5): _cumulative_cost is authoritative. A turn with no usage.cost
does NOT reset it to 0 — that would corrupt session_cost's `max(0, new - last)` delta and
overcount the next turn. Exact `:free` routes must report zero when cost is present;
the HTTP client rejects a non-zero charge before tool dispatch.
"""

import asyncio
import contextlib
import logging
import os
import re
from pathlib import Path
from typing import AsyncIterator, Optional
from uuid import uuid4

from app.events import AgentEvent
from app.usage_contract import AggregateUsage, TurnUsage, current_context
from app.harness import prompts, tools as builtin
from app.harness.llm import OpenRouterClient
from app.harness.loop import AgentLoop, ReviewCtx
from app.harness.mcp import MCPClient
from app.harness.sessions import SessionStore

logger = logging.getLogger(__name__)

# ── adaptive extended thinking (#123) ──
# The reasoning-vs-quality curve is concave — overthinking HURTS easy tasks and burns tokens
# (HARNESS-RESEARCH.md §2). So pick OpenRouter reasoning effort per turn from the message + role:
# trivial/routing → "minimal", complex (debug/refactor/architecture) → "high", else "medium".
# Pure heuristic, no ML, no extra API call. "minimal" (not "none") for the floor — some models
# reject "none" when reasoning is mandatory.

# Word-boundary match so "fix:" / "why?" / "debugging" hit, "planet" doesn't. Bilingual: the user
# often writes Russian. Cyrillic stems use \w (Unicode) boundaries.
_HIGH_EFFORT_RE = re.compile(
    r"\b(debug\w*|refactor\w*|architect\w*|root cause|race condition|design\w*|investigat\w*|"
    r"trace|why|diagnos\w*|fix\w*|bug\w*|почини|исправь|отлад\w*|рефактор\w*|архитектур\w*|"
    r"почему|разберись|гонк\w*)\b",
    re.IGNORECASE | re.UNICODE)

_TRIVIAL_MESSAGES = frozenset({
    "ok", "okay", "yes", "no", "continue", "go", "merge", "merge it", "proceed", "thanks",
    "done", "approved", "lgtm", "ship it", "да", "нет", "ок", "мерж", "продолжай",
})


def classify_effort(message: str, is_orchestrator: bool) -> str:
    """Pick OpenRouter reasoning effort from the turn. Pure + testable, no ML, no extra call.
    Order matters: trivial acks first, then complexity keywords, then the short-message floor."""
    m = (message or "").strip()
    low = m.lower()
    if not m or low in _TRIVIAL_MESSAGES:
        return "minimal"
    if _HIGH_EFFORT_RE.search(m):        # complexity keyword wins over the length floor
        return "high"
    if len(m) <= 12:                     # very short, non-keyword instruction → cheap
        return "minimal"
    if is_orchestrator:                  # planning/decomposition is the complex path
        return "high"
    if len(m) >= 400:                    # long multi-part request → complex
        return "high"
    return "medium"                      # safe default; medium rarely hurts

DEFAULT_CONTEXT = 200000


class HarnessBackend:
    def __init__(self, model: str, cwd: str, system_prompt: str = "",
                 resume_session_id: str | None = None,
                 mcp_servers: dict | None = None,
                 is_orchestrator: bool = False):
        self.model = model
        self.cwd = cwd
        self.system_prompt = system_prompt
        self._mcp_servers = mcp_servers or {}
        self._is_orchestrator = is_orchestrator
        self._resume_session_id = resume_session_id

        self._llm: Optional[OpenRouterClient] = None
        self._mcp: Optional[MCPClient] = None
        self._store: Optional[SessionStore] = None
        self._history: list[dict] = []
        self._tool_schemas: list[dict] = []
        self._full_system_prompt: str = ""

        self._pending_msg: Optional[str] = None
        self._turn_active = False
        self._abort_flag = False
        self._injected: list[str] = []   # steering messages awaiting the next round

        self._cumulative_cost: float = 0.0
        self._cumulative_input: int = 0
        self._cumulative_output: int = 0

        # Gated planning (#125) — a per-session todo list; the todo_write tool is hard-gated onto
        # complex (effort=="high") turns only (_turn_tool_schemas). Simple turns never see it.
        self._todos = builtin.TodoStore()

    def _turn_tool_schemas(self, effort: str, allow_review: bool = True) -> list[dict]:
        """Tool schemas for THIS turn. `review` (read-only reviewer, #126) is added on parent turns;
        complex turns additionally get todo_write (#125). We never shadow a same-named MCP tool.
        When nothing is added (simple turn, review disabled), returns the base set UNCHANGED (same
        object → default behavior preserved)."""
        names = {s.get("function", {}).get("name") for s in self._tool_schemas}
        extra: list[dict] = []
        if allow_review and builtin.REVIEW_TOOL_NAME not in names:
            extra.append(builtin.review_schema())
        if effort == "high":
            if builtin.TODO_TOOL_NAME in names:
                logger.warning("todo_write already provided by another tool source — not adding the gated one")
            else:
                extra.append(builtin.todo_write_schema())
        return self._tool_schemas + extra if extra else self._tool_schemas

    def _drain_injected(self) -> list[str]:
        """Hand the running loop everything that arrived mid-turn, and forget it here.
        One owner of the queue at a time — the loop appends them to history itself."""
        if not self._injected:
            return []
        taken, self._injected = self._injected, []
        return taken

    def build_handoff_manifest(self, prepared, *, validation_profile: bool):
        """What the model will actually see after a runtime switch.

        Required by session.py's model-change preflight for EVERY runtime — a backend
        without it blocks the switch with a bare AttributeError, which is what happened
        the first time a harness agent was moved to another model.
        """
        from app.runtime_history import build_model_visible_manifest

        return build_model_visible_manifest(
            runtime="harness",
            model=self.model,
            effective_window=self._max_context(),
            system_prompt=self.system_prompt,
            prepared=prepared,
            validation_profile=validation_profile,
            project_docs=getattr(prepared, "project_docs", ()),
            mcp_servers=self._mcp_servers,
        )

    def _review_ctx(self) -> ReviewCtx:
        return ReviewCtx(llm=self._llm, cwd=self.cwd, max_context=self._max_context())

    @property
    def session_id(self) -> Optional[str]:
        return self._store.session_id if self._store else self._resume_session_id

    def retarget_model(self, model: str) -> None:
        """Retarget later OpenRouter requests while keeping local history intact."""
        if self._turn_active:
            raise RuntimeError("cannot retarget harness model while a turn is active")
        from app.models import get_model_spec, validate_harness_model_spec

        spec = get_model_spec(model)
        validate_harness_model_spec(spec)
        if self._llm is not None:
            self._llm.retarget(model, spec.supported_parameters)
        self.model = model

    # ── lifecycle ──

    async def connect(self) -> None:
        api_key = (os.environ.get("OPENROUTER_API_KEY")
                   or os.environ.get("OPENROUTER_KEY", ""))
        if not api_key:
            raise RuntimeError("No API key found (checked OPENROUTER_API_KEY, OPENROUTER_KEY)")
        from app.models import get_model_spec, validate_harness_model_spec

        spec = get_model_spec(self.model)
        validate_harness_model_spec(spec)
        base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        if base_url and not base_url.endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"
        self._llm = OpenRouterClient(
            api_key=api_key,
            model=self.model,
            base_url=base_url,
            supported_parameters=spec.supported_parameters,
        )

        # MCP must NEVER break backend startup. connect() is atomic (clears its own state on
        # a hard error), and merge_tool_schemas can itself raise on a builtin↔MCP name
        # collision — so connect + merge live in ONE guard. On any failure we tear down any
        # children that did start and fall back to built-in tools only.
        self._mcp = MCPClient()
        try:
            await self._mcp.connect(self._mcp_servers)
            self._tool_schemas = prompts.merge_tool_schemas(
                builtin.tool_schemas(), self._mcp.tool_schemas())
        except Exception as e:
            logger.warning(f"MCP unavailable, built-in tools only: {e}")
            with contextlib.suppress(Exception):
                await self._mcp.disconnect()
            self._tool_schemas = prompts.merge_tool_schemas(builtin.tool_schemas(), [])
        self._full_system_prompt = prompts.build_system_prompt(self.system_prompt)

        # Alongside the DB, not /tmp: a reboot must not erase agent history.
        session_dir = str(Path(__file__).parent.parent / "data" / "harness-sessions")
        self._store = SessionStore(session_dir, session_id=self._resume_session_id)
        if self._resume_session_id:
            self._history = self._store.load()
        self._reset_system_message()
        logger.info(f"HarnessBackend connected: model={self.model}, session={self.session_id}, "
                    f"tools={len(self._tool_schemas)}, history={len(self._history)}")

    def _reset_system_message(self) -> None:
        sys_msg = {"role": "system", "content": self._full_system_prompt}
        if self._history and self._history[0].get("role") == "system":
            self._history[0] = sys_msg
        else:
            self._history.insert(0, sys_msg)

    # ── messaging ──

    async def send(self, message: str) -> None:
        if self._llm is None:
            raise RuntimeError("HarnessBackend not connected")
        if self._turn_active:
            # Steering, not an error: the running loop picks this up at the top of its
            # next round. Without it a correction waits for the whole turn to finish —
            # up to MAX_TOOL_ROUNDS rounds of work done against stale instructions.
            self._injected.append(message)
            return
        self._pending_msg = message
        self._abort_flag = False
        self._turn_active = True

    async def events(self) -> AsyncIterator[AgentEvent]:
        if self._llm is None or self._mcp is None or self._store is None:
            return
        if not self._turn_active or self._pending_msg is None:
            return

        user_msg = self._pending_msg
        self._pending_msg = None
        self._injected.clear()   # nothing steered yet; leftovers would replay stale text
        effort = classify_effort(user_msg, self._is_orchestrator)  # once per turn
        loop = AgentLoop(
            llm=self._llm, mcp=self._mcp, cwd=self.cwd, history=self._history,
            tool_schemas=self._turn_tool_schemas(effort), max_context=self._max_context(),
            abort=lambda: self._abort_flag, effort=effort, todo_store=self._todos,
            allow_review=True, review_ctx=self._review_ctx(),
            drain_injected=self._drain_injected,
        )

        error_out: str | None = None
        try:
            async for ev in loop.run(user_msg):
                yield ev
        except asyncio.CancelledError:
            # Hard cancel — session.py's finally sets IDLE. Do not yield after this
            # (the generator is closing). No turn_end is emitted on this path.
            # Persist only a CONSISTENT prefix: an assistant message with tool_calls whose
            # tool results never arrived would make the next request invalid, so drop it.
            with contextlib.suppress(Exception):
                await self._persist_loop(loop, cancelled=True)
            self._turn_active = False
            raise
        except Exception as e:
            logger.error(f"HarnessBackend events() error: {e}")
            error_out = f"loop_error: {e}"
        finally:
            self._turn_active = False

        # Persist the turn's messages (best-effort) before emitting the terminal event.
        with contextlib.suppress(Exception):
            await self._persist_loop(loop)

        # ── terminal turn_end (exactly one, on every non-cancel path) ──
        # Accumulate EACH round independently: a round with native cost uses it; a round
        # with only tokens is estimated. (Counting whatever was spent, error path too.)
        for usage in loop.round_usages:
            self._accumulate(usage)
        if error_out is not None:
            yield self._error_turn_end(error_out)
            return
        yield self._turn_end(loop, ok=loop.ok, stop_reason=loop.stop_reason,
                             detail=loop.error_detail if not loop.ok else "")

    async def _persist(self, messages: list[dict]) -> None:
        if self._store and messages:
            await self._store.append_messages(messages)

    async def _persist_loop(self, loop: AgentLoop, *, cancelled: bool = False) -> None:
        """Persist one loop without resurrecting history discarded by context compaction."""
        if self._store is None:
            return
        if loop.truncated_dropped:
            await self._store.replace_messages(_consistent_prefix(self._history))
            return
        messages = _consistent_prefix(loop.new_messages) if cancelled else loop.new_messages
        await self._persist(messages)

    # ── cost / tokens (plan B5) ──

    def _accumulate(self, usage: dict) -> None:
        """Grow cumulative counters from one round without resetting missing usage.

        The HTTP client rejects any non-zero provider cost before tool dispatch; keeping
        the reported zero here preserves the shared cumulative-cost contract.
        """
        if not usage:
            return  # no usage → keep previous cumulative (do not corrupt the delta)
        in_tok = int(usage.get("prompt_tokens", 0) or 0)
        out_tok = int(usage.get("completion_tokens", 0) or 0)
        self._cumulative_input += in_tok
        self._cumulative_output += out_tok
        cost = usage.get("cost")
        if cost is not None:
            self._cumulative_cost += float(cost)

    def _max_context(self) -> int:
        from app.models import CONTEXT_LIMITS

        return CONTEXT_LIMITS.get(self.model, DEFAULT_CONTEXT)

    def _turn_end(self, loop: AgentLoop, ok: bool, stop_reason: str,
                  detail: str = "") -> AgentEvent:
        usage = loop.last_usage or {}
        turn_input = int(usage.get("prompt_tokens", 0) or 0)
        max_tokens = self._max_context()
        # The last round's prompt_tokens IS the live context: OpenRouter re-sends the whole
        # history each round, so the final prompt carries everything the model still holds.
        turn_usage = TurnUsage(
            AggregateUsage.normalized(
                input_tokens=self._cumulative_input,
                output_tokens=self._cumulative_output,
            ),
            current_context(
                turn_input or None,
                max_tokens,
                unknown_reason="OpenRouter returned no usage for the final round",
            ),
        )
        content = f"stop_reason={stop_reason}" + (f" ({detail})" if detail else "")
        return AgentEvent("turn_end", content, metadata={
            "event_id": str(uuid4()),
            "session_id": self.session_id,
            "ok": ok,
            "stop_reason": stop_reason,
            "num_turns": 1,
            "cost_usd": self._cumulative_cost,
            "cost_usd_cached": self._cumulative_cost,   # no prompt-cache on MVP
            "cache_hit": 0,
            **turn_usage.metadata(),
        }, usage=turn_usage)

    def _error_turn_end(self, reason: str) -> AgentEvent:
        # Even on error, cost/tokens are the AUTHORITATIVE cumulative — NOT 0 (plan B5),
        # so session_cost's delta does not overcount the next turn.
        turn_usage = TurnUsage(
            AggregateUsage.normalized(
                input_tokens=self._cumulative_input,
                output_tokens=self._cumulative_output,
            ),
            current_context(
                None, self._max_context(),
                unknown_reason=f"turn ended on {reason} before a usage report",
            ),
        )
        return AgentEvent("turn_end", f"stop_reason={reason}", metadata={
            "event_id": str(uuid4()),
            "session_id": self.session_id,
            "ok": False,
            "stop_reason": reason,
            "num_turns": 1,
            "cost_usd": self._cumulative_cost,
            "cost_usd_cached": self._cumulative_cost,
            "cache_hit": 0,
            **turn_usage.metadata(),
        }, usage=turn_usage)

    # ── teardown ──

    async def interrupt(self) -> None:
        self._abort_flag = True

    async def reconnect(self) -> None:
        # one-shot backend — never reconnected by session.py (excluded in hibernate),
        # but keep it safe: full re-init.
        await self.disconnect()
        await asyncio.sleep(0.5)
        await self.connect()

    async def disconnect(self) -> None:
        self._abort_flag = True
        self._turn_active = False
        if self._mcp is not None:
            with contextlib.suppress(Exception):
                await self._mcp.disconnect()
            self._mcp = None
        if self._llm is not None:
            with contextlib.suppress(Exception):
                await self._llm.aclose()
            self._llm = None
        if self._store is not None:
            with contextlib.suppress(Exception):
                await self._store.close()


def _consistent_prefix(messages: list[dict]) -> list[dict]:
    """Return the longest prefix in which every assistant tool_calls message has a tool
    result for EACH of its tool_call ids. A turn interrupted mid-dispatch can leave the
    last assistant tool_calls message with only SOME results (e.g. asst(c1,c2) + tool c1);
    persisting that would make the resumed conversation an invalid OpenAI request, so we
    drop the whole incomplete round (the assistant message + its partial results)."""
    if not messages:
        return messages
    # Walk back to the last assistant-with-tool_calls; check its ids are all answered.
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            wanted = {tc.get("id") for tc in m["tool_calls"]}
            answered = {messages[j].get("tool_call_id")
                        for j in range(i + 1, len(messages))
                        if messages[j].get("role") == "tool"}
            if wanted.issubset(answered):
                return messages          # round complete → keep everything
            return messages[:i]          # incomplete → drop this round entirely
        if m.get("role") in ("user", "assistant"):
            return messages              # a clean assistant/user tail with no open tools
    return messages
