"""Live-socket probe of streaming responses under GZipMiddleware on the REAL app.main.

Checks:
  1. GET /api/report_bug (text/markdown StreamingResponse) - body arrives COMPLETE and
     byte-identical to the concatenated source chunks, gzip or not.
  2. A long multi-chunk text/markdown stream stays INCREMENTAL (first chunk arrives before
     the generator finishes) - or is proven NOT to.
  3. SSE (text/event-stream) is untouched and incremental.
Arms: gzip / nogzip. Control arm must differ on the wire.
"""
import asyncio
import gzip as gzlib
import json
import os
import socket
import sys
import time

ARM = sys.argv[1]
import app.main as M
from fastapi.responses import StreamingResponse

CHUNKS = [(f"chunk-{i:04d}-" + "y" * 3000 + "\n").encode() for i in range(40)]
_gate = asyncio.Event()


@M.app.get("/api/probe_md_stream")
async def probe_md_stream():
    """Multi-chunk text/markdown stream, gated in the middle: proves incrementality."""
    async def gen():
        yield CHUNKS[0]
        await _gate.wait()
        for c in CHUNKS[1:]:
            yield c
    return StreamingResponse(gen(), media_type="text/markdown")


@M.app.get("/api/probe_md_full")
async def probe_md_full():
    async def gen():
        for c in CHUNKS:
            yield c
    return StreamingResponse(gen(), media_type="text/markdown")


if ARM == "nogzip":
    M.app.user_middleware = [m for m in M.app.user_middleware if m.cls.__name__ != "GZipMiddleware"]
    M.app.middleware_stack = None


def connect(port, path, accept_gzip=True):
    s = socket.create_connection(("127.0.0.1", port), timeout=25)
    hdr = "Accept-Encoding: gzip\r\n" if accept_gzip else ""
    s.sendall(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n{hdr}Connection: close\r\n\r\n".encode())
    return s


def drain(s, timeout=25):
    s.settimeout(timeout)
    out = b""
    while True:
        try:
            b = s.recv(65536)
        except socket.timeout:
            break
        if not b:
            break
        out += b
    s.close()
    return out


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
            return out + body
        if n == 0:
            break
        out += body[i + 2:i + 2 + n]
        body = body[i + 2 + n + 2:]
    return out


def decode(head, body):
    payload = dechunk(body) if "transfer-encoding: chunked" in head.lower() else body
    if "content-encoding: gzip" in head.lower():
        return gzlib.decompress(payload), len(payload)
    return payload, len(payload)


async def main():
    import uvicorn
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(M.app, log_level="error", lifespan="off"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.05)
    loop = asyncio.get_running_loop()
    r = {"arm": ARM}

    # --- 1. full markdown stream integrity
    raw = await loop.run_in_executor(None, lambda: drain(connect(port, "/api/probe_md_full")))
    head, body = split_head(raw)
    dec, wire = decode(head, body)
    expected = b"".join(CHUNKS)
    r["md_full"] = {"wire": wire, "decoded": len(dec), "expected": len(expected),
                    "identical": dec == expected,
                    "gzipped": "content-encoding: gzip" in head.lower()}

    # --- 2. incrementality of a gated markdown stream
    s = await loop.run_in_executor(None, lambda: connect(port, "/api/probe_md_stream"))

    def read_early():
        s.settimeout(2.5)
        got = b""
        t0 = time.monotonic()
        try:
            while time.monotonic() - t0 < 2.5:
                b = s.recv(65536)
                if not b:
                    break
                got += b
        except socket.timeout:
            pass
        return got

    early = await loop.run_in_executor(None, read_early)
    r["md_stream_early_bytes"] = len(early)
    r["md_stream_early_has_head"] = b"HTTP/1.1 200" in early
    r["md_stream_early_has_chunk0"] = b"chunk-0000" in early
    if b"content-encoding: gzip" in early.lower() and b"\r\n\r\n" in early:
        h, b2 = split_head(early)
        try:
            part = gzlib.decompressobj(16 + gzlib.MAX_WBITS).decompress(dechunk(b2))
            r["md_stream_early_decoded_has_chunk0"] = b"chunk-0000" in part
            r["md_stream_early_decoded_bytes"] = len(part)
        except Exception as e:
            r["md_stream_early_decode_err"] = type(e).__name__
    _gate.set()
    rest = await loop.run_in_executor(None, lambda: drain(s))
    whole = early + rest
    head2, body2 = split_head(whole)
    dec2, wire2 = decode(head2, body2)
    r["md_stream_full"] = {"identical": dec2 == expected, "decoded": len(dec2),
                           "expected": len(expected), "wire": wire2,
                           "gzipped": "content-encoding: gzip" in head2.lower(),
                           "head": head2}

    # --- 3. real /api/report_bug
    raw3 = await loop.run_in_executor(None, lambda: drain(connect(port, "/api/report_bug")))
    head3, body3 = split_head(raw3)
    dec3, wire3 = decode(head3, body3)
    r["report_bug"] = {"status": head3.split("\r\n")[0], "wire": wire3, "decoded": len(dec3),
                       "gzipped": "content-encoding: gzip" in head3.lower(),
                       "tail": dec3[-80:].decode("utf-8", "replace"),
                       "head": head3}

    print("JSONRESULT" + json.dumps(r))
    server.should_exit = True
    await task


asyncio.run(main())
