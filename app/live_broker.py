"""In-memory pub/sub for live (ephemeral) stream partials — bypasses the DB.

Single process, single event loop. Partials are best-effort: a slow consumer
drops oldest chunks rather than blocking the session event loop. The final
DB-persisted 'text' log is always authoritative on reload/reconnect.

Not compatible with multi-worker uvicorn (in-memory, like the session manager).
"""
import asyncio
import time
from collections import defaultdict

_MAXSIZE = 1024  # per-subscriber backlog; drop-oldest beyond this
STREAM_CLOSE = object()

# Live blocks a client opening the chat mid-generation must still see: the tool call being
# written, current reasoning, running command output. Only the tail is kept for replay.
_LIVE_KEYS = {
    "tool_input_stream": ("tool_use_id", 64 * 1024),
    "thinking_stream": ("item_id", 32 * 1024),
    "tool_stream": ("tool_use_id", 16 * 1024),
}


def live_key(payload: dict) -> tuple[str, str] | None:
    spec = _LIVE_KEYS.get(payload.get("type"))
    if not spec or payload.get("activity") == "waiting":
        return None
    key = payload.get(spec[0])
    return (payload["type"], str(key)) if key else None


_MERGE_FIELDS = {
    "stream": (),
    "subagent_stream": ("subagent_id", "event_type", "item_id"),
    "thinking_stream": ("item_id", "activity"),
    "tool_input_stream": ("tool_use_id",),
    "tool_stream": ("tool_use_id", "stream", "subagent_id"),
}


def coalesce(payloads: list) -> list:
    """Glue adjacent deltas of the same live block into one SSE frame.

    The SSE loop drains the queue every ~100 ms; a long tool call arrives as thousands of
    tiny JSON fragments, and one frame per fragment would make the browser parse and
    repaint per fragment. Only neighbours merge, so the order of blocks is preserved.
    """
    out: list = []
    for payload in payloads:
        fields = _MERGE_FIELDS.get(payload.get("type")) if isinstance(payload, dict) else None
        prev = out[-1] if out else None
        if (fields is not None and isinstance(prev, dict)
                and prev.get("type") == payload.get("type")
                and payload.get("activity") != "waiting"
                and not payload.get("replace")
                and all(prev.get(f) == payload.get(f) for f in fields)):
            merged = {**prev, **payload, "content": prev.get("content", "") + payload.get("content", "")}
            if prev.get("replace"):
                merged["replace"] = True
            out[-1] = merged
        else:
            out.append(payload)
    return out


class LiveBroker:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._accum: dict[str, str] = {}
        self._live: dict[str, dict[tuple[str, str], dict]] = {}
        self._closing = False

    def subscribe(self, session_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=_MAXSIZE)
        if self._closing:
            q.put_nowait(STREAM_CLOSE)
            return q
        # Replay accumulated stream text so reconnecting clients see what they missed
        current = self._accum.get(session_id, "")
        if current:
            try:
                q.put_nowait({"type": "stream", "content": current})
            except asyncio.QueueFull:
                pass
        for item in tuple(self._live.get(session_id, {}).values()):
            replay = {k: v for k, v in item.items() if not k.startswith("_")}
            replay["replace"] = True
            if "_started" in item:
                replay["elapsed_ms"] = int((time.monotonic() - item["_started"]) * 1000)
            try:
                q.put_nowait(replay)
            except asyncio.QueueFull:
                pass
        self._subs[session_id].add(q)
        return q

    def unsubscribe(self, session_id: str, q: asyncio.Queue) -> None:
        subs = self._subs.get(session_id)
        if subs:
            subs.discard(q)
            if not subs:
                self._subs.pop(session_id, None)

    def publish(self, session_id: str, payload: dict) -> None:
        if self._closing:
            return
        # Второй шов маскирования (#224): этот путь в БД не пишется вовсе ("NEVER persist"),
        # поэтому маскирование в db.add_log его не закрывает. Маскируем ДО _accum — иначе
        # реплей отдаст новому подписчику сырое значение.
        if payload.get("type") == "stream":
            self._accum[session_id] = self._accum.get(session_id, "") + payload.get("content", "")
        key = live_key(payload)
        if key is not None:
            payload = self._remember_live(session_id, key, payload)
        for q in tuple(self._subs.get(session_id, ())):  # snapshot — safe if set mutates
            if q.full():
                try:
                    q.get_nowait()  # drop oldest — partials are ephemeral
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    def _remember_live(self, session_id: str, key: tuple[str, str], payload: dict) -> dict:
        blocks = self._live.setdefault(session_id, {})
        item = blocks.get(key)
        content = payload.get("content", "")
        if item is None:
            item = {"content": "", "chars": 0, "_started": time.monotonic()}
            blocks[key] = item
        item.update({k: v for k, v in payload.items() if k != "content"})
        item["content"] = (item["content"] + content)[-_LIVE_KEYS[key[0]][1]:]
        item["chars"] += len(content)
        if key[0] != "tool_input_stream":
            return payload
        # The writer's speed is computed server-side: browser and server clocks differ.
        return {**payload, "chars": item["chars"],
                "elapsed_ms": int((time.monotonic() - item["_started"]) * 1000)}

    def end_live(self, session_id: str, kind: str, key: str = "") -> None:
        """Forget a replayable live block once its persisted record exists (all of a kind
        when key is empty)."""
        blocks = self._live.get(session_id)
        if not blocks:
            return
        for live in [k for k in blocks if k[0] == kind and (not key or k[1] == key)]:
            del blocks[live]
        if not blocks:
            self._live.pop(session_id, None)

    def clear_live(self, session_id: str) -> None:
        self._live.pop(session_id, None)

    def clear_accum(self, session_id: str) -> None:
        """Clear accumulated stream text — call when final 'text' event arrives."""
        self._accum.pop(session_id, None)

    def close_subscribers(self) -> None:
        """Ask all current SSE generators to finish before graceful shutdown."""
        self._closing = True
        for queues in tuple(self._subs.values()):
            for q in tuple(queues):
                if q.full():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                try:
                    q.put_nowait(STREAM_CLOSE)
                except asyncio.QueueFull:
                    pass


broker = LiveBroker()
