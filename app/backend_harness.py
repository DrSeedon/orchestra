"""HarnessBackend — Orchestra's own agent backend (BackendLike), no daemon.

A persistent in-process object: it owns an OpenRouter HTTP client, an MCP stdio client,
a JSONL session store, and the cumulative cost/token counters that must survive across
turns. Each send()/events() pair runs ONE turn through AgentLoop and emits EXACTLY ONE
turn_end (plan B2) carrying the full 15-key metadata parity of the other backends.

Cost contract (plan B5): _cumulative_cost is authoritative. A turn with no usage.cost
does NOT reset it to 0 — that would corrupt session_cost's `max(0, new - last)` delta and
overcount the next turn. We keep the previous cumulative, or grow it with a price-table
estimate when token counts are available.
"""

import asyncio
import contextlib
import copy
import logging
import os
import re
from pathlib import Path
from typing import AsyncIterator, Optional

from app.events import AgentEvent
from app.usage_contract import AggregateUsage, TurnUsage, current_context
from app.harness import bestofn, prompts, tools as builtin
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
                 is_orchestrator: bool = False,
                 provider_id: str = "openrouter"):
        self.model = model
        self.provider_id = provider_id
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

        # Best-of-N (#124) — OFF by default; only activates when the flag is set AND the turn
        # runs in a clean git worktree with a resolvable test suite (see _should_use_bestofn).
        self._bestofn = os.environ.get("HARNESS_BESTOFN", "").lower() in ("1", "true", "yes")
        self._bestofn_n = bestofn.clamp_n(os.environ.get("HARNESS_BESTOFN_N"))

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
        if self._llm is not None:
            self._llm.model = model
        self.model = model

    # ── lifecycle ──

    async def connect(self) -> None:
        api_key = (os.environ.get("OPENROUTER_API_KEY")
                   or os.environ.get("OPENROUTER_KEY")
                   or os.environ.get("ANTHROPIC_API_KEY", ""))
        if not api_key:
            raise RuntimeError("No API key found (checked OPENROUTER_API_KEY, OPENROUTER_KEY, ANTHROPIC_API_KEY)")
        base_url = os.environ.get("OPENROUTER_BASE_URL") or os.environ.get("ANTHROPIC_BASE_URL", "https://openrouter.ai/api/v1")
        if base_url and not base_url.endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"
        self._llm = OpenRouterClient(api_key=api_key, model=self.model, base_url=base_url)

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

        # Best-of-N branch (#124) — guarded, off by default. When it doesn't apply, the ORIGINAL
        # single-attempt path below runs byte-for-byte unchanged.
        test_cmd = self._resolve_bestofn()
        if test_cmd is not None:
            async for ev in self._events_bestofn(self._pending_msg, test_cmd):
                yield ev
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
                await self._persist(_consistent_prefix(loop.new_messages))
            self._turn_active = False
            raise
        except Exception as e:
            logger.error(f"HarnessBackend events() error: {e}")
            error_out = f"loop_error: {e}"
        finally:
            self._turn_active = False

        # Persist the turn's messages (best-effort) before emitting the terminal event.
        with contextlib.suppress(Exception):
            await self._persist(loop.new_messages)

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

    # ── Best-of-N (#124) ──

    def _resolve_bestofn(self) -> Optional[str]:
        """Return the verifier command if Best-of-N should run this turn, else None (→ default
        single-attempt path). Gate: flag on AND git worktree AND clean tree AND resolvable HEAD
        AND detectable test suite AND resolvable test command. Any miss → None (fail-safe)."""
        if not self._bestofn:
            return None
        if not (bestofn.is_git_repo(self.cwd) and bestofn.clean_tree(self.cwd)):
            return None
        if bestofn.base_sha(self.cwd) is None:
            return None
        return bestofn.resolve_test_cmd(self.cwd)

    async def _events_bestofn(self, user_msg: str, test_cmd: str) -> AsyncIterator[AgentEvent]:
        """Run up to N sequential attempts, verifying each with test_cmd; yield the first passing
        attempt's events + one turn_end. Early-exit on pass. All-failed → roll back to base and
        report failure. Defensive rollback: reset only when the dirt is attempt-generated."""
        self._pending_msg = None
        assert self._llm is not None and self._mcp is not None    # events() checked before calling
        base = bestofn.base_sha(self.cwd)
        assert base is not None                      # guaranteed by _resolve_bestofn
        base_history = copy.deepcopy(self._history)
        base_todos = copy.deepcopy(self._todos.todos)   # planning state resets per attempt (#125)
        effort = classify_effort(user_msg, self._is_orchestrator)
        turn_schemas = self._turn_tool_schemas(effort, allow_review=False)  # attempts don't review (#126)
        n = self._bestofn_n
        winner: Optional[AgentLoop] = None
        winner_events: list[AgentEvent] = []
        touched: set = set()                          # paths the LAST attempt wrote (for rollback)
        last_tail = ""
        abort_reason: Optional[str] = None            # set → stop without a winner, distinct turn_end

        try:
            for i in range(1, n + 1):
                if self._abort_flag:
                    abort_reason = "aborted"
                    break
                if i > 1 and not self._rollback_attempt(base, touched):
                    # unexpected worktree/HEAD state → do NOT destructively reset (no data loss).
                    abort_reason = "bestofn_abort_dirty"
                    yield AgentEvent("status", "[bestofn] unexpected worktree changes — stopping, tree left as-is")
                    break
                self._history = copy.deepcopy(base_history)
                self._todos.todos = copy.deepcopy(base_todos)   # clean planning state per attempt
                loop = AgentLoop(
                    llm=self._llm, mcp=self._mcp, cwd=self.cwd, history=self._history,
                    tool_schemas=turn_schemas, max_context=self._max_context(),
                    abort=lambda: self._abort_flag, effort=effort, todo_store=self._todos,
                )
                buffered: list[AgentEvent] = []
                loop_failed = False
                try:
                    async for ev in loop.run(user_msg):
                        buffered.append(ev)
                except Exception as e:
                    logger.error(f"[bestofn] attempt {i} loop failed: {e}")
                    loop_failed = True
                for u in loop.round_usages:            # every attempt is billed (cost is cumulative)
                    self._accumulate(u)
                touched = self._attempt_touched(buffered)
                if loop_failed:
                    continue                           # retry (rollback at top of next iter)
                yield AgentEvent("status", f"[bestofn] attempt {i}/{n} — running tests…")
                verdict, tail = await bestofn.run_verifier(self.cwd, test_cmd)
                last_tail = tail
                logger.info(f"[bestofn] attempt {i}/{n}: {verdict} "
                            f"(cost=${self._cumulative_cost:.4f} in={self._cumulative_input} out={self._cumulative_output})")
                if verdict == "pass":
                    winner, winner_events = loop, buffered
                    break                             # early-exit — keep this attempt's tree
                if verdict == "no_verifier":
                    # broken runner (not a real fail): can't verify → keep NOTHing, roll back + report.
                    abort_reason = "bestofn_no_verifier"
                    break
                # fail → next iteration rolls back and retries
        except asyncio.CancelledError:
            self._turn_active = False
            raise

        self._turn_active = False
        if winner is not None:
            # commit the winner: its history is already self._history (loop mutated it in place).
            self._history = winner.history
            with contextlib.suppress(Exception):
                await self._persist(winner.new_messages)
            for ev in winner_events:
                yield ev
            yield self._turn_end(winner, ok=winner.ok, stop_reason=winner.stop_reason,
                                 detail=winner.error_detail if not winner.ok else "")
            return

        # No winner. Roll back to base UNLESS the tree is already in an unexpected state
        # (abort_dirty). If the final rollback REFUSES or FAILS to verify, the tree is NOT clean —
        # report bestofn_abort_dirty (honest) instead of claiming a clean all_failed rollback.
        if abort_reason != "bestofn_abort_dirty":
            rolled_back = False
            with contextlib.suppress(Exception):
                rolled_back = self._rollback_attempt(base, touched)
            if not rolled_back:
                abort_reason = "bestofn_abort_dirty"
        self._history = base_history
        self._todos.todos = base_todos                # no winner → restore pre-turn planning state
        reason = abort_reason or "bestofn_all_failed"
        msg = {
            "aborted": "Best-of-N: interrupted before a passing attempt.",
            "bestofn_no_verifier": "Best-of-N: the test command could not run (no verifier) — rolled back.",
            "bestofn_abort_dirty": "Best-of-N: unexpected worktree changes — stopped, tree left as-is.",
        }.get(reason, f"Best-of-N: all {n} attempts failed the test suite.")
        yield AgentEvent("text", f"{msg}\n{last_tail}".rstrip())
        yield self._error_turn_end(reason)

    def _attempt_touched(self, events: list[AgentEvent]) -> set:
        """Repo-relative paths the attempt's file tools wrote (from file_change events:
        'add /abs/path' / 'update /abs/path')."""
        touched: set = set()
        base = os.path.abspath(self.cwd)
        for ev in events or []:
            if ev.type != "file_change":
                continue
            parts = ev.content.split(" ", 1)
            if len(parts) != 2:
                continue
            raw = parts[1]
            p = raw if os.path.isabs(raw) else os.path.abspath(os.path.join(self.cwd, raw))
            try:
                if os.path.commonpath([base, p]) == base:    # p is strictly inside the worktree
                    touched.add(os.path.relpath(p, base))
            except ValueError:
                continue                                     # different drive / not comparable → skip
        return touched

    def _rollback_attempt(self, base: str, touched: set) -> bool:
        """Defensive rollback (Option 1). Reset the worktree to `base` ONLY if it's safe (HEAD still
        at base AND every dirty path is attempt-generated) AND the reset verifiably lands clean-at-
        base. Returns False if we refused to reset OR the reset didn't verify — caller must stop."""
        if not bestofn.dirt_is_attempt_only(self.cwd, base, touched):
            return False
        return bestofn.rollback_to_base(self.cwd, base)

    async def _persist(self, messages: list[dict]) -> None:
        if self._store and messages:
            await self._store.append_messages(messages)

    # ── cost / tokens (plan B5) ──

    def _accumulate(self, usage: dict) -> None:
        """Grow cumulative counters from ONE round's usage. Native cost is used when the
        round reports it; otherwise the round's cost is estimated from tokens × price
        table (so a mix of native and missing-cost rounds is each handled correctly).
        NEVER reset to 0 on missing data — keep the previous cumulative monotonic."""
        if not usage:
            return  # no usage → keep previous cumulative (do not corrupt the delta)
        in_tok = int(usage.get("prompt_tokens", 0) or 0)
        out_tok = int(usage.get("completion_tokens", 0) or 0)
        self._cumulative_input += in_tok
        self._cumulative_output += out_tok
        cost = usage.get("cost")
        if cost is not None:
            self._cumulative_cost += float(cost)
        else:
            est = self._estimate_cost(in_tok, out_tok)
            if est > 0:
                self._cumulative_cost += est

    def _estimate_cost(self, in_tok: int, out_tok: int) -> float:
        """Fallback only — OpenRouter reports usage.cost for paid models, and every model
        routed here today is `:free` (priced 0 in models.py). TOKEN_PRICES stays the single
        owner of prices; no local copy."""
        from app.models import TOKEN_PRICES

        price = TOKEN_PRICES.get(self.model)
        if not price:
            return 0.0
        return (in_tok / 1_000_000) * price["input"] + (out_tok / 1_000_000) * price["output"]

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
