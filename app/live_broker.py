"""In-memory pub/sub for live (ephemeral) stream partials — bypasses the DB.

Single process, single event loop. Partials are best-effort: a slow consumer
drops oldest chunks rather than blocking the session event loop. The final
DB-persisted 'text' log is always authoritative on reload/reconnect.

Not compatible with multi-worker uvicorn (in-memory, like the session manager).
"""
import asyncio
from collections import defaultdict

_MAXSIZE = 256  # per-subscriber backlog; drop-oldest beyond this
STREAM_CLOSE = object()


class LiveBroker:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._accum: dict[str, str] = {}
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
