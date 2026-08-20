"""Question (a), decisive form: on the REAL app.main with the REAL SSE route
(/api/sessions/{name}/stream), with GZipMiddleware active:

  1. the SSE response is NOT compressed and arrives INCREMENTALLY over a raw socket;
  2. Census classifies it as a STREAM (not mutating), so drain_mutating_requests()
     returns True while the stream is still open -> a restart can complete;
  3. a concurrent slow MUTATING request DOES hold the drain (control arm: the same
     call must return False), proving the probe can tell the two apart.

Arms: gzip / nogzip must agree on 1-3; the wire size must differ (discriminating).
"""
import asyncio, json, socket, sys, tempfile, time
from pathlib import Path

ARM = sys.argv[1]
ROOT = "/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/rev197-opus"
sys.path.insert(0, ROOT)

import os
_db = Path(tempfile.mkdtemp()) / "o.db"
os.environ["ORCHESTRA_DB_PATH"] = str(_db)
os.environ["DASHBOARD_USER"] = ""
os.environ["DASHBOARD_PASSWORD"] = ""

from app import db as dbmod
dbmod.DB_PATH = _db
from app.db import init_db, save_session, add_log
init_db()
from datetime import datetime, timezone
NOW = datetime.now(timezone.utc).isoformat()
save_session({"id": "sse-id", "name": "sse-probe", "scope": "/tmp/s", "cwd": "/tmp/s",
              "model": "claude-opus-5[1m]", "system_prompt": "", "status": "idle",
              "session_id": None, "cost_usd": 0.0, "worktree_path": None, "branch": None,
              "is_orchestrator": False, "color": "", "created_at": NOW,
              "finished_at": None, "role": "worker"})
for i in range(6):
    add_log("sse-id", datetime.now(timezone.utc), "text", f"line-{i}-" + "z" * 2000)

import app.main as M
from fastapi.responses import JSONResponse

_hold = asyncio.Event()


@M.app.post("/api/probe_hold_mutating")
async def hold_mut():
    await _hold.wait()
    return JSONResponse({"ok": True, "pad": "q" * 5000})


@M.app.post("/api/probe_drain_now")
async def drain_now():
    ok = await M.drain_mutating_requests(budget_s=2.0)
    return JSONResponse({"drained": ok,
                         "mutating": M.inflight_mutating_count(),
                         "streams": M.inflight_stream_count()})


@M.app.post("/api/probe_release_hold")
async def rel():
    _hold.set()
    return JSONResponse({"ok": True})


if ARM == "nogzip":
    M.app.user_middleware = [m for m in M.app.user_middleware if m.cls.__name__ != "GZipMiddleware"]
    M.app.middleware_stack = None


def raw(port, method, path, hdr=b"", body=b"", keep=False, timeout=25):
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    req = f"{method} {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n".encode() + hdr
    if body:
        req += f"Content-Length: {len(body)}\r\nContent-Type: application/json\r\n".encode()
    req += b"\r\n" + body
    s.sendall(req)
    if keep:
        return s
    out = b""
    while True:
        try:
            c = s.recv(65536)
        except socket.timeout:
            break
        if not c:
            break
        out += c
    s.close()
    return out


def body_of(rawb):
    i = rawb.find(b"\r\n\r\n")
    return rawb[:i].decode("latin1"), rawb[i + 4:]


def dechunk(b):
    o = b""
    while True:
        i = b.find(b"\r\n")
        if i < 0:
            return o + b
        try:
            n = int(b[:i].split(b";")[0], 16)
        except ValueError:
            return o + b
        if n == 0:
            return o
        o += b[i + 2:i + 2 + n]
        b = b[i + 2 + n + 2:]


async def main():
    import uvicorn
    sk = socket.socket(); sk.bind(("127.0.0.1", 0)); port = sk.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(M.app, log_level="error", lifespan="off"))
    t = asyncio.create_task(srv.serve(sockets=[sk]))
    for _ in range(200):
        if srv.started:
            break
        await asyncio.sleep(0.05)
    loop = asyncio.get_running_loop()
    R = {"arm": ARM}

    # --- open the REAL SSE stream and read the first bytes early
    url = "/api/sessions/sse-probe/stream?scope=/tmp/s&after_id=0"
    s = await loop.run_in_executor(None, lambda: raw(port, "GET", url, hdr=b"Accept-Encoding: gzip\r\n", keep=True))

    def early():
        s.settimeout(3.0)
        got = b""
        t0 = time.monotonic()
        try:
            while time.monotonic() - t0 < 3.0 and b"line-5" not in got:
                c = s.recv(65536)
                if not c:
                    break
                got += c
        except socket.timeout:
            pass
        return got

    got = await loop.run_in_executor(None, early)
    head, b1 = body_of(got)
    R["sse_head"] = head
    R["sse_gzipped"] = "content-encoding: gzip" in head.lower()
    R["sse_first_bytes"] = len(got)
    R["sse_incremental_plain_visible"] = b"line-0" in got
    await asyncio.sleep(0.3)
    R["census_while_sse"] = {"mutating": M.inflight_mutating_count(),
                             "streams": M.inflight_stream_count()}

    # drain MUST succeed while SSE is open
    d = await loop.run_in_executor(None, lambda: raw(port, "POST", "/api/probe_drain_now", body=b"{}"))
    _, db = body_of(d)
    R["drain_with_sse_open"] = json.loads(dechunk(db))

    # --- control arm: a slow MUTATING request must BLOCK the drain
    hold = await loop.run_in_executor(None, lambda: raw(port, "POST", "/api/probe_hold_mutating", body=b"{}", keep=True))
    await asyncio.sleep(0.4)
    d2 = await loop.run_in_executor(None, lambda: raw(port, "POST", "/api/probe_drain_now", body=b"{}"))
    _, db2 = body_of(d2)
    R["drain_with_mutating_inflight"] = json.loads(dechunk(db2))
    await loop.run_in_executor(None, lambda: raw(port, "POST", "/api/probe_release_hold", body=b"{}"))

    def fin(sock):
        sock.settimeout(15)
        o = b""
        while True:
            try:
                c = sock.recv(65536)
            except socket.timeout:
                break
            if not c:
                break
            o += c
        sock.close()
        return o

    await loop.run_in_executor(None, lambda: fin(hold))
    await asyncio.sleep(0.4)
    d3 = await loop.run_in_executor(None, lambda: raw(port, "POST", "/api/probe_drain_now", body=b"{}"))
    _, db3 = body_of(d3)
    R["drain_after_mutating_done"] = json.loads(dechunk(db3))

    try:
        s.close()
    except Exception:
        pass
    await asyncio.sleep(0.5)
    R["census_after_sse_closed"] = {"mutating": M.inflight_mutating_count(),
                                    "streams": M.inflight_stream_count()}
    print("JSONRESULT" + json.dumps(R, ensure_ascii=False))
    srv.should_exit = True
    await t


asyncio.run(main())
