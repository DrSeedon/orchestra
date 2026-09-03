"""Live-socket probe: does GZipMiddleware perturb RequestCensusMiddleware's drain counter
on the REAL app.main application (not a bench app)?

Arms:
  gzip   -> app as shipped by the branch (GZipMiddleware outermost)
  nogzip -> same app with GZipMiddleware removed from user_middleware (control arm)

Both arms must report the SAME counter behaviour. The control arm must produce a
PERMISSIVE result (drain succeeds, counter returns to 0) so a broken probe is visible.
"""
import asyncio
import gzip as gzlib
import json
import os
import socket
import sys
import time

os.environ.setdefault("DASHBOARD_USER", "")
os.environ.setdefault("DASHBOARD_PASSWORD", "")

ARM = sys.argv[1]

import app.main as M
from fastapi.responses import JSONResponse, StreamingResponse

_slow_release = asyncio.Event()
_observed = []


@M.app.post("/api/probe_slow_mutating")
async def probe_slow_mutating():
    """A mutating request whose body is big enough to be gzipped."""
    _observed.append(("entered", M.inflight_mutating_count(), M.inflight_stream_count()))
    await _slow_release.wait()
    return JSONResponse({"pad": "x" * 40000, "ok": True})


@M.app.post("/api/probe_slow_stream_mut")
async def probe_slow_stream_mut():
    """Mutating POST that answers with an SSE stream -> Census must reclassify it."""
    async def gen():
        yield b"data: hello\n\n"
        await _slow_release.wait()
        yield b"data: bye\n\n"
    _observed.append(("stream_entered", M.inflight_mutating_count(), M.inflight_stream_count()))
    return StreamingResponse(gen(), media_type="text/event-stream")


@M.app.get("/api/probe_counters")
async def probe_counters():
    return JSONResponse({
        "mutating": M.inflight_mutating_count(),
        "streams": M.inflight_stream_count(),
    })


@M.app.post("/api/probe_drain")
async def probe_drain():
    t0 = time.monotonic()
    ok = await M.drain_mutating_requests(budget_s=3.0)
    return JSONResponse({"drained": ok, "elapsed": round(time.monotonic() - t0, 3),
                         "mutating": M.inflight_mutating_count()})


@M.app.post("/api/probe_release")
async def probe_release():
    _slow_release.set()
    return JSONResponse({"released": True})


if ARM == "nogzip":
    M.app.user_middleware = [m for m in M.app.user_middleware
                             if m.cls.__name__ != "GZipMiddleware"]
    M.app.middleware_stack = None

CHAIN = []
_st = M.app.build_middleware_stack()
_n = _st
while _n is not None and len(CHAIN) < 12:
    CHAIN.append(type(_n).__name__)
    _n = getattr(_n, "app", None)


def raw_request(port, method, path, headers=b"", body=b"", read_all=True, timeout=20):
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    req = f"{method} {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n".encode()
    req += headers
    if body:
        req += f"Content-Length: {len(body)}\r\nContent-Type: application/json\r\n".encode()
    req += b"\r\n" + body
    s.sendall(req)
    if not read_all:
        return s
    chunks = []
    while True:
        try:
            b = s.recv(65536)
        except socket.timeout:
            break
        if not b:
            break
        chunks.append(b)
    s.close()
    return b"".join(chunks)


def split_head(raw):
    i = raw.find(b"\r\n\r\n")
    return raw[:i].decode("latin1"), raw[i + 4:]


def dechunk(body):
    out = b""
    while True:
        i = body.find(b"\r\n")
        if i < 0:
            break
        try:
            n = int(body[:i].split(b";")[0], 16)
        except ValueError:
            return body
        if n == 0:
            break
        out += body[i + 2:i + 2 + n]
        body = body[i + 2 + n + 2:]
    return out


async def main():
    import uvicorn
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(M.app, log_level="error", lifespan="off")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve(sockets=[sock]))
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.05)

    result = {"arm": ARM, "chain": CHAIN, "port": port}
    loop = asyncio.get_running_loop()

    # ---- 1. slow mutating request held open, gzip-capable client
    conn = await loop.run_in_executor(
        None, lambda: raw_request(port, "POST", "/api/probe_slow_mutating",
                                  headers=b"Accept-Encoding: gzip\r\n", body=b"{}",
                                  read_all=False))
    await asyncio.sleep(0.6)
    result["counter_while_inflight"] = M.inflight_mutating_count()

    # drain must NOT succeed while the request is in flight
    d = await loop.run_in_executor(None, lambda: raw_request(
        port, "POST", "/api/probe_drain", body=b"{}"))
    _, db = split_head(d)
    result["drain_while_inflight"] = json.loads(dechunk(db) or db)

    # release + read the held response fully off the raw socket
    await loop.run_in_executor(None, lambda: raw_request(port, "POST", "/api/probe_release", body=b"{}"))

    def finish(s):
        chunks = []
        s.settimeout(20)
        while True:
            try:
                b = s.recv(65536)
            except socket.timeout:
                break
            if not b:
                break
            chunks.append(b)
        s.close()
        return b"".join(chunks)

    raw = await loop.run_in_executor(None, lambda: finish(conn))
    head, body = split_head(raw)
    result["slow_head"] = head
    wire_len = len(body)
    if "content-encoding: gzip" in head.lower():
        payload = dechunk(body) if "transfer-encoding: chunked" in head.lower() else body
        decoded = gzlib.decompress(payload)
    else:
        decoded = dechunk(body) if "transfer-encoding: chunked" in head.lower() else body
    result["wire_bytes"] = wire_len
    result["decoded_bytes"] = len(decoded)
    result["decoded_ok"] = json.loads(decoded).get("ok") is True

    await asyncio.sleep(0.4)
    result["counter_after"] = M.inflight_mutating_count()

    # drain must now succeed
    d2 = await loop.run_in_executor(None, lambda: raw_request(port, "POST", "/api/probe_drain", body=b"{}"))
    _, db2 = split_head(d2)
    result["drain_after"] = json.loads(dechunk(db2) or db2)

    # ---- 2. mutating POST answering with SSE: must move mutating->stream
    _slow_release.clear()
    conn2 = await loop.run_in_executor(
        None, lambda: raw_request(port, "POST", "/api/probe_slow_stream_mut",
                                  headers=b"Accept-Encoding: gzip\r\n", body=b"{}",
                                  read_all=False))
    await asyncio.sleep(0.6)
    result["sse_counter_mutating"] = M.inflight_mutating_count()
    result["sse_counter_streams"] = M.inflight_stream_count()
    d3 = await loop.run_in_executor(None, lambda: raw_request(port, "POST", "/api/probe_drain", body=b"{}"))
    _, db3 = split_head(d3)
    result["sse_drain_while_open"] = json.loads(dechunk(db3) or db3)
    # first SSE chunk must arrive BEFORE the generator finishes (incrementality)
    conn2.settimeout(5)
    early = b""
    try:
        for _ in range(6):
            b = conn2.recv(65536)
            early += b
            if b"data: hello" in early:
                break
    except socket.timeout:
        pass
    result["sse_first_chunk_early"] = b"data: hello" in early
    result["sse_head_snippet"] = early.split(b"\r\n\r\n")[0].decode("latin1")
    await loop.run_in_executor(None, lambda: raw_request(port, "POST", "/api/probe_release", body=b"{}"))
    await loop.run_in_executor(None, lambda: finish(conn2))
    await asyncio.sleep(0.4)
    result["sse_counter_after"] = (M.inflight_mutating_count(), M.inflight_stream_count())

    result["observed"] = _observed
    print("JSONRESULT" + json.dumps(result))
    server.should_exit = True
    await task


asyncio.run(main())
