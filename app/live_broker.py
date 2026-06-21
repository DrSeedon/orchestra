"""In-memory pub/sub for live (ephemeral) stream partials — bypasses the DB.

Single process, single event loop. Partials are best-effort: a slow consumer
drops oldest chunks rather than blocking the session event loop. The final
DB-persisted 'text' log is always authoritative on reload/reconnect.

Not compatible with multi-worker uvicorn (in-memory, like the session manager).
"""
import asyncio
from collections import defaultdict

_MAXSIZE = 256  # per-subscriber backlog; drop-oldest beyond this


class LiveBroker:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, session_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=_MAXSIZE)
        self._subs[session_id].add(q)
        return q

    def unsubscribe(self, session_id: str, q: asyncio.Queue) -> None:
        subs = self._subs.get(session_id)
        if subs:
            subs.discard(q)
            if not subs:
                self._subs.pop(session_id, None)

    def publish(self, session_id: str, payload: dict) -> None:
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


broker = LiveBroker()
