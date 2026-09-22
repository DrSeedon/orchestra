"""V-585 live acceptance: one Harness turn on GigaChat with a socket-level connection log."""
import asyncio
import os
import socket
import sys
import tempfile

sys.path.insert(0, os.getcwd())

for line in open("/home/kesha/projects/seedon/secrets/gigachat.env"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ[k] = v
os.environ["GIGACHAT_CA_BUNDLE"] = "/home/kesha/.config/seedon/certs/russian_trusted_root_ca_pem.crt"

LOG: list[str] = []
_orig_connect = socket.socket.connect
_orig_gai = socket.getaddrinfo


def _connect(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6):
        LOG.append(f"connect {address[0]}:{address[1]}")
    return _orig_connect(self, address)


def _gai(host, port, *a, **kw):
    LOG.append(f"dns {host}:{port}")
    return _orig_gai(host, port, *a, **kw)


socket.socket.connect = _connect
socket.getaddrinfo = _gai


async def main():
    from app.backend_harness import HarnessBackend

    cwd = tempfile.mkdtemp(prefix="v585-")
    with open(os.path.join(cwd, "secret.txt"), "w") as f:
        f.write("Кодовое слово: ПЕЛИКАН-47\n")
    backend = HarnessBackend(os.environ.get("MODEL", "GigaChat-2"), cwd)
    await backend.connect()
    print("llm:", type(backend._llm).__name__, backend._llm.chat_url)
    await backend.send("Прочитай файл secret.txt инструментом read и назови кодовое слово из него.")
    async for ev in backend.events():
        print("event:", ev.type, repr(ev.content[:160]), {k: ev.metadata.get(k) for k in ("ok", "stop_reason") if k in ev.metadata})
    await backend.disconnect()
    print("--- network log ---")
    for entry in dict.fromkeys(LOG):
        print(entry)


asyncio.run(main())
