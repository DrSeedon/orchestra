"""AgentLoop — the OpenAI tool-loop that drives one turn to completion.

run(user_msg) yields AgentEvents (text / tool_use / tool_result / file_change) for a
whole turn and RETURNS normally when the turn is done (model stops requesting tools, or
a ceiling/abort/error is hit). It does NOT emit turn_end — the backend wraps run() and
emits exactly one terminal turn_end (plan B2), reading the loop's final state:

    loop.stop_reason   — "end_turn" | "tool_calls"(unreachable as terminal) | "max_turns"
                         | "aborted" | "context_limit" | "error"
    loop.ok            — False on error/limit paths
    loop.last_usage    — {prompt_tokens, completion_tokens, cost} from the last LLM call
    loop.error_detail  — human string when ok is False

Invariants:
- A round's assistant message is appended to history BEFORE dispatching its tools, and
  every tool_call gets a matching tool result message (same tool_call_id) — never leave a
  tool_call dangling (breaks the next request).
- content + tool_calls in one message: keep both, but tool_calls win — we keep looping.
- Invalid tool-argument JSON → tool error result, loop continues (never crash, plan B4).
- Context guard before each request: estimate tokens, truncate the middle, and if still
  over → terminal context_limit (plan B6).
"""

import json
import logging
from typing import AsyncIterator, Callable

from app.events import AgentEvent
from app.harness import tools as builtin
from app.harness.llm import OpenRouterClient
from app.harness.mcp import MCPClient

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 50          # ceiling on tool-call rounds in a single turn
REVIEW_MAX_ROUNDS = 15        # tighter ceiling for a reviewer sub-loop (#126)
CONTEXT_GUARD_RATIO = 0.85    # truncate when estimated tokens exceed this × max_context
CHARS_PER_TOKEN = 3.5         # crude estimator (no tiktoken dependency)
KEEP_RECENT_MESSAGES = 8      # messages preserved at the tail during truncation


class _NoopMCP:
    """MCP stand-in for the read-only reviewer sub-loop — no tools reachable (#126). Ensures the
    reviewer physically cannot call mutating MCP tools (spawn_worker, etc.), beyond the read-only
    schema + dispatch guard (defense in depth)."""
    def has_tool(self, name: str) -> bool:
        return False

    async def call(self, name: str, args: dict) -> str:
        return "[review] MCP tools are not available to the reviewer"


class ReviewCtx:
    """Immutable holder of what the reviewer sub-loop needs (NO mcp — it uses _NoopMCP)."""
    __slots__ = ("llm", "cwd", "max_context")

    def __init__(self, llm, cwd: str, max_context: int):
        self.llm = llm
        self.cwd = cwd
        self.max_context = max_context


class AgentLoop:
    def __init__(self, llm: OpenRouterClient, mcp: MCPClient, cwd: str,
                 history: list[dict], tool_schemas: list[dict], max_context: int,
                 abort: Callable[[], bool] | None = None, effort: str | None = None,
                 todo_store=None, allow_review: bool = False, review_ctx=None,
                 readonly_mode: bool = False, max_rounds: int = MAX_TOOL_ROUNDS,
                 drain_injected: Callable[[], list[str]] | None = None):
        self.llm = llm
        self.mcp = mcp
        self.cwd = cwd
        self.history = history            # full OpenAI-format message list (shared, mutated)
        self.tool_schemas = tool_schemas
        self.max_context = max_context
        self._abort = abort or (lambda: False)
        self.effort = effort              # OpenRouter reasoning effort for this turn (or None)
        self.todo_store = todo_store      # per-session TodoStore, or None (todo_write not offered)
        # sub-agent reviewer (#126)
        self.allow_review = allow_review  # parent loop → True; reviewer sub-loop → False (depth-1)
        self.review_ctx = review_ctx      # ReviewCtx(llm, cwd, max_context) for the sub-loop, or None
        self.readonly_mode = readonly_mode  # reviewer sub-loop: dispatch rejects non-READONLY tools
        self.max_rounds = max_rounds      # round ceiling (reviewer gets a tighter one)
        # Mid-turn steering: returns messages that arrived while this turn was running.
        # Drained at the TOP of a round, never between an assistant tool_calls message
        # and its tool results — a gap there makes the next request malformed.
        self._drain_injected = drain_injected or (lambda: [])
        # terminal state read by the backend after run() exhausts
        self.stop_reason = "end_turn"
        self.ok = True
        self.last_usage: dict = {}          # usage of the LAST round (for context_pct)
        # round_usages = the usage dict of EVERY round (a tool turn has many
        # /chat/completions calls). The backend accumulates each round independently so a
        # round with native cost and a round with only tokens are each handled correctly.
        self.round_usages: list[dict] = []
        self.error_detail = ""
        self.new_messages: list[dict] = []  # messages produced this turn (for persistence)

    async def run(self, user_msg: str) -> AsyncIterator[AgentEvent]:
        user_entry = {"role": "user", "content": user_msg}
        self.history.append(user_entry)
        self.new_messages.append(user_entry)

        for _ in range(self.max_rounds):
            if self._abort():
                self._terminal("aborted", ok=False, detail="aborted by interrupt")
                return

            for injected in self._drain_injected():
                entry = {"role": "user", "content": injected}
                self.history.append(entry)
                self.new_messages.append(entry)
                yield AgentEvent("status", "message steered into active turn")

            if not self._fit_context():
                self._terminal("context_limit", ok=False,
                               detail="history exceeds context window even after truncation")
                return

            assistant_msg = {"role": "assistant", "content": None}  # filled by _one_round
            try:
                # _one_round yields text live AND fills assistant_msg in place.
                async for ev in self._one_round(assistant_msg):
                    yield ev
            except Exception as e:
                logger.error(f"harness loop round failed: {e}")
                yield AgentEvent("error", f"llm round failed: {e}")
                self._terminal("error", ok=False, detail=f"llm_error: {e}")
                return

            self.history.append(assistant_msg)
            self.new_messages.append(assistant_msg)

            tool_calls = assistant_msg.get("tool_calls") or []
            if not tool_calls:
                # No tools requested → turn is done. Normalize the OpenAI "stop"/""
                # finish to "end_turn" (parity with other backends); pass through other
                # explicit reasons (e.g. "length", "content_filter").
                fr = self.stop_reason
                stop = "end_turn" if fr in ("stop", "tool_calls", "") else fr
                self._terminal(stop, ok=True)
                return

            # Abort that arrives AFTER tool_calls are known: do NOT execute the tools
            # (could be destructive). Append synthetic aborted tool results so the
            # assistant tool_calls message is never left dangling (else the next request
            # is rejected), then end the turn.
            if self._abort():
                for tc in tool_calls:
                    self._append_tool_result(tc.get("id", ""), "[aborted by interrupt]")
                self._terminal("aborted", ok=False, detail="aborted before tool dispatch")
                return

            # Dispatch tools sequentially, preserving tool_call ids.
            for tc in tool_calls:
                async for ev in self._dispatch_tool(tc):
                    yield ev

        # ran out of rounds
        self._terminal("max_turns", ok=False, detail=f"exceeded {self.max_rounds} tool rounds")

    async def _one_round(self, assistant_msg: dict) -> AsyncIterator[AgentEvent]:
        """Stream one LLM completion. Yields text AgentEvents LIVE (so the session sees
        tokens as they arrive, not buffered to round-end) and fills `assistant_msg`
        in place with content + tool_calls. Accumulates this round's usage into the
        turn totals (every round counts toward the cumulative cost contract)."""
        text_parts: list[str] = []
        tool_calls: list[dict] = []
        reasoning_details: list = []
        finish_reason = "stop"

        # Pass effort only when set — keeps the call signature-compatible with stream() stubs
        # that don't accept the kwarg (real backwards compatibility, not just body-identical).
        if self.effort is None:
            gen = self.llm.stream(self.history, self.tool_schemas, abort=self._abort)
        else:
            gen = self.llm.stream(self.history, self.tool_schemas, abort=self._abort, effort=self.effort)
        async for ev in gen:
            if ev.kind == "text_delta":
                text_parts.append(ev.text)
            elif ev.kind == "tool_call_done":
                tool_calls.append({
                    "id": ev.tool_id,
                    "type": "function",
                    "function": {"name": ev.tool_name, "arguments": ev.arguments or "{}"},
                })
            elif ev.kind == "final":
                finish_reason = ev.finish_reason or "stop"
                reasoning_details = ev.reasoning_details or []
                if ev.usage:
                    self.last_usage = ev.usage
                    self.round_usages.append(ev.usage)

        content = "".join(text_parts)
        if content:
            yield AgentEvent("text", content)
        assistant_msg["content"] = content or None
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
            finish_reason = "tool_calls"   # tool_calls win over any other finish reason
        # Replay reasoning blocks UNMODIFIED on the next request (they go into history via
        # assistant_msg) — required for reasoning models across tool rounds. Only reasoning_details
        # (structured, verbatim), never the plaintext `reasoning` too — sending both corrupts the
        # signature (OpenRouter reasoning-tokens docs).
        if reasoning_details:
            assistant_msg["reasoning_details"] = reasoning_details
        self.stop_reason = finish_reason

    async def _dispatch_tool(self, tc: dict) -> AsyncIterator[AgentEvent]:
        fn = tc.get("function") or {}
        name = fn.get("name", "")
        raw_args = fn.get("arguments", "") or "{}"
        call_id = tc.get("id", "")

        # Parse arguments here (plan B4) — invalid JSON → tool error, never a crash.
        try:
            args = json.loads(raw_args) if raw_args.strip() else {}
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
        except (ValueError, TypeError) as e:
            result = f"[error] invalid tool arguments for {name}: {e}"
            yield AgentEvent("tool_use", f"{name}: {raw_args[:200]}",
                             metadata={"tool_name": name, "short_name": _short(name)})
            yield AgentEvent("tool_result", result)
            self._append_tool_result(call_id, result)
            return

        try:
            arg_summary = json.dumps(args, ensure_ascii=False)
        except (TypeError, ValueError):
            arg_summary = str(args)
        yield AgentEvent("tool_use", f"{name}: {arg_summary}",
                         metadata={"tool_name": name, "short_name": _short(name)})

        # Reviewer sub-loop is READ-ONLY (#126): reject any non-read tool (incl. a hallucinated
        # `review` → enforces depth-1) BEFORE builtin/mcp/review dispatch. Structural guarantee.
        if self.readonly_mode and name not in builtin.READONLY_NAMES:
            result = f"[read-only] reviewer cannot use '{name}' — only read/glob/grep are allowed"
            yield AgentEvent("tool_result", result)
            self._append_tool_result(call_id, result)
            return

        # review spawns a read-only reviewer sub-loop; it streams its own subagent_* events and
        # appends exactly one tool_result (try/finally inside _run_review). Handled here (stateful).
        if (name == builtin.REVIEW_TOOL_NAME and self.allow_review and self.review_ctx is not None
                and not self.mcp.has_tool(name)):
            async for ev in self._run_review(call_id, args.get("focus", "")):
                yield ev
            return

        # todo_write is stateful (per-session store) — handled here, not in the stateless dispatch.
        # Only OUR tool: require a store AND that no MCP server owns the name (never shadow MCP).
        if (name == builtin.TODO_TOOL_NAME and self.todo_store is not None
                and not self.mcp.has_tool(name)):
            result = self.todo_store.write(args.get("todos"))
            is_file_change = False
        elif name in builtin.BUILTIN_NAMES:
            result, is_file_change = await builtin.dispatch(name, args, self.cwd)
            if is_file_change and not result.startswith("["):
                path = args.get("path", "")
                verb = "add" if name == "write" else "update"
                yield AgentEvent("file_change", f"{verb} {path}")
        elif self.mcp.has_tool(name):
            result = await self.mcp.call(name, args)
            is_file_change = False
        else:
            result = f"[error] unknown tool: {name}"

        yield AgentEvent("tool_result", result)
        self._append_tool_result(call_id, result)

    def _append_tool_result(self, call_id: str, content: str) -> None:
        entry = {"role": "tool", "tool_call_id": call_id, "content": content}
        self.history.append(entry)
        self.new_messages.append(entry)

    async def _run_review(self, sub_id: str, focus: str) -> AsyncIterator[AgentEvent]:
        """Run a READ-ONLY reviewer sub-loop (#126) with a clean context; stream its events UP as
        subagent_* (subagent_id lives IN THE CONTENT so it survives the DB/SSE path and the frontend
        groups it). try/finally guarantees exactly one subagent_end, one tool_result for sub_id, and
        the sub-loop's usage billed exactly once — even on abort/error."""
        ctx = self.review_ctx
        focus = (focus or "").strip() or "Review the recent changes for correctness and clarity."
        yield AgentEvent("subagent_start", f"subagent_id={sub_id} | type=reviewer | {focus[:120]}",
                         metadata={"subagent_id": sub_id})
        sub = AgentLoop(
            llm=ctx.llm, mcp=_NoopMCP(), cwd=ctx.cwd,
            history=[{"role": "system", "content": builtin.REVIEWER_PROMPT}],  # clean context
            tool_schemas=builtin.readonly_tool_schemas(), max_context=ctx.max_context,
            abort=self._abort, allow_review=False, readonly_mode=True, max_rounds=REVIEW_MAX_ROUNDS,
        )
        text_parts: list[str] = []
        folded = False
        status = "failed"
        try:
            async for ev in sub.run(focus):
                if ev.type == "text":
                    text_parts.append(ev.content)
                # surface the reviewer's activity live, nested under the accordion by subagent_id
                if ev.type in ("text", "tool_use", "tool_result"):
                    yield AgentEvent("subagent_stream",
                                     f"subagent_id={sub_id} | {ev.content[:300]}",
                                     metadata={"subagent_id": sub_id, "event_type": ev.type})
            status = "aborted" if self._abort() else ("completed" if sub.ok else "failed")
        except Exception as e:
            logger.error(f"[review] sub-loop failed: {e}")
            text_parts.append(f"[review error] {e}")
            status = "failed"
        finally:
            if not folded:
                self.round_usages.extend(sub.round_usages)   # bill sub-loop rounds exactly once
                folded = True
            review_text = "".join(text_parts).strip() or "(reviewer produced no findings)"
            if status == "aborted":
                review_text = f"[review aborted]\n{review_text}"
            yield AgentEvent("subagent_end",
                             f"subagent_id={sub_id} | status={status} | {review_text[:160]}",
                             metadata={"subagent_id": sub_id})
            yield AgentEvent("tool_result", review_text)
            self._append_tool_result(sub_id, review_text)

    # ── context management (plan B6) ──

    def _estimate_tokens(self) -> int:
        total = 0
        for m in self.history:
            total += len(json.dumps(m, ensure_ascii=False))
        return int(total / CHARS_PER_TOKEN)

    def _fit_context(self) -> bool:
        """Truncate history from the MIDDLE to fit the context guard. Preserve the
        system message, the recent tail, and tool_call/tool_result integrity.
        Returns False if it cannot be made to fit (caller → context_limit)."""
        guard = int(self.max_context * CONTEXT_GUARD_RATIO)
        if self._estimate_tokens() <= guard:
            return True
        head = self.history[:1] if self.history and self.history[0].get("role") == "system" else []
        tail = self.history[-KEEP_RECENT_MESSAGES:]
        # Never start the tail with an orphan tool result (no preceding tool_call).
        while tail and tail[0].get("role") == "tool":
            tail = tail[1:]
        self.history[:] = head + tail
        return self._estimate_tokens() <= self.max_context

    def _terminal(self, stop_reason: str, ok: bool, detail: str = "") -> None:
        self.stop_reason = stop_reason
        self.ok = ok
        self.error_detail = detail


def _short(name: str) -> str:
    # strip an mcp__server__ prefix or orchestra_ prefix for compact UI labels
    if name.startswith("mcp__"):
        return name.rsplit("__", 1)[-1]
    if name.startswith("orchestra_"):
        return name.split("_", 1)[-1]
    return name
