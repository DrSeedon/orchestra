"""Tests for app.live_broker — in-memory pub/sub for stream partials."""
import asyncio
import pytest

from app.live_broker import LiveBroker, STREAM_CLOSE, _MAXSIZE


@pytest.mark.asyncio
async def test_subscribe_publish_get():
    b = LiveBroker()
    q = b.subscribe("sid")
    b.publish("sid", {"type": "stream", "content": "hi"})
    assert q.get_nowait() == {"type": "stream", "content": "hi"}


@pytest.mark.asyncio
async def test_fanout_to_multiple_subscribers():
    b = LiveBroker()
    q1 = b.subscribe("sid")
    q2 = b.subscribe("sid")
    b.publish("sid", {"content": "x"})
    assert q1.get_nowait() == {"content": "x"}
    assert q2.get_nowait() == {"content": "x"}


@pytest.mark.asyncio
async def test_publish_to_unknown_session_is_noop():
    b = LiveBroker()
    # no subscribers — must not raise
    b.publish("nobody", {"content": "x"})


@pytest.mark.asyncio
async def test_drop_oldest_when_full():
    b = LiveBroker()
    q = b.subscribe("sid")
    for i in range(_MAXSIZE + 5):
        b.publish("sid", {"n": i})
    # queue capped at _MAXSIZE; oldest dropped, newest kept
    assert q.qsize() == _MAXSIZE
    first = q.get_nowait()
    assert first["n"] == 5  # 0..4 dropped
    # drain rest, last must be the newest
    last = first
    while not q.empty():
        last = q.get_nowait()
    assert last["n"] == _MAXSIZE + 4


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery_and_cleans_up():
    b = LiveBroker()
    q = b.subscribe("sid")
    b.unsubscribe("sid", q)
    b.publish("sid", {"content": "x"})
    assert q.empty()
    # session set removed once empty
    assert "sid" not in b._subs


@pytest.mark.asyncio
async def test_unsubscribe_one_of_two_keeps_other():
    b = LiveBroker()
    q1 = b.subscribe("sid")
    q2 = b.subscribe("sid")
    b.unsubscribe("sid", q1)
    b.publish("sid", {"content": "x"})
    assert q1.empty()
    assert q2.get_nowait() == {"content": "x"}
    assert "sid" in b._subs


@pytest.mark.asyncio
async def test_isolated_sessions():
    b = LiveBroker()
    qa = b.subscribe("a")
    qb = b.subscribe("b")
    b.publish("a", {"content": "for-a"})
    assert qa.get_nowait() == {"content": "for-a"}
    assert qb.empty()


def test_close_subscribers_wakes_every_current_stream():
    broker = LiveBroker()
    first = broker.subscribe("session-1")
    second = broker.subscribe("session-1")
    third = broker.subscribe("session-2")

    broker.close_subscribers()

    assert first.get_nowait() is STREAM_CLOSE
    assert second.get_nowait() is STREAM_CLOSE
    assert third.get_nowait() is STREAM_CLOSE


def test_close_subscribers_makes_room_in_full_queue():
    broker = LiveBroker()
    queue = broker.subscribe("session")
    for index in range(queue.maxsize):
        queue.put_nowait({"index": index})

    broker.close_subscribers()

    items = []
    while True:
        try:
            items.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    assert STREAM_CLOSE in items
