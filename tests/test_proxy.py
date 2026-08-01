"""Proxy manager (read-only, .env source of truth) + ssh_tunnel health-gate."""

import asyncio
import subprocess
import sys
from unittest.mock import AsyncMock

import pytest

from app import proxy_manager as pm
from app import ssh_tunnel as st
from app.routes import proxy as proxy_routes


@pytest.fixture(autouse=True)
def _clean_proxy_env(monkeypatch):
    for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("PROXY_LIST", raising=False)


def test_direct_id_stable(monkeypatch):
    monkeypatch.setenv("PROXY_LIST", "Direct (VPN/Соту)|direct,Contabo DE|http://127.0.0.1:12343")
    entries = pm._parse_proxy_list()
    assert entries[0].id == "direct"  # not mangled 'direct-(vpn/соту)'
    assert entries[1].id == "contabo-de"


@pytest.mark.asyncio
async def test_active_follows_env(monkeypatch):
    monkeypatch.setenv("PROXY_LIST", "Direct|direct,Contabo|http://127.0.0.1:12343,Fornex|http://127.0.0.1:12342")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:12343")
    mgr = pm.ProxyManager()
    r = await mgr.list_proxies()
    assert r["active"] == "contabo"
    # list carries NO cached liveness — that's on-demand via check
    assert all("ok" not in p for p in r["proxies"])


@pytest.mark.asyncio
async def test_active_direct_when_no_env(monkeypatch):
    monkeypatch.setenv("PROXY_LIST", "Direct|direct,Contabo|http://127.0.0.1:12343")
    r = await pm.ProxyManager().list_proxies()
    assert r["active"] == "direct"


def test_no_mutation_methods_gone():
    # hot-switch / DB persistence removed — .env is the only source
    mgr = pm.ProxyManager()
    assert not hasattr(mgr, "select_proxy")
    assert not hasattr(mgr, "load_saved_proxy")
    assert not hasattr(mgr, "refresh_loop")


@pytest.mark.asyncio
async def test_check_geo_failure_keeps_alive(monkeypatch):
    # liveness (Anthropic) OK but geo (ipinfo) throwing must NOT flip ok→false
    mgr = pm.ProxyManager()

    class _Resp:
        status_code = 404  # any response = tunnel works

    class _Client:
        def __init__(self, **kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def get(self, url): return _Resp()

    monkeypatch.setattr(pm.httpx, "AsyncClient", _Client)

    async def boom(proxy):
        raise RuntimeError("ipinfo timeout")

    monkeypatch.setattr(mgr, "_geo", boom)
    r = await mgr._do_check(pm.ProxyEntry(id="c", name="C", url="http://127.0.0.1:12343"))
    assert r["ok"] is True  # geo blew up, liveness held


@pytest.mark.asyncio
async def test_check_dead_proxy_real_error():
    # unreachable proxy → ok:false with a NON-empty error (not "")
    entry = pm.ProxyEntry(id="d", name="D", url="http://127.0.0.1:19998")
    r = await pm.ProxyManager()._do_check(entry)
    assert r["ok"] is False
    assert r["error"], "error must be non-empty for a dead proxy"


def test_set_env_preserves_tokens(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "HTTPS_PROXY=http://127.0.0.1:12343\n"
        "HTTP_PROXY=http://127.0.0.1:12343\n"
        "TG_BOT_TOKEN=123:ABC_secret\n"
        "YOUGILE_KEY=xyz|special@chars\n"
        "PROXY_LIST=Direct|direct,Contabo|http://127.0.0.1:12343\n",
        encoding="utf-8")
    monkeypatch.setattr(proxy_routes, "ENV_FILE", env)

    proxy_routes._set_env_proxy("http://127.0.0.1:12342")
    out = env.read_text()
    assert "HTTPS_PROXY=http://127.0.0.1:12342" in out
    assert "HTTP_PROXY=http://127.0.0.1:12342" in out
    assert "TG_BOT_TOKEN=123:ABC_secret" in out  # tokens untouched
    assert "YOUGILE_KEY=xyz|special@chars" in out
    assert "PROXY_LIST=Direct|direct" in out  # ^-anchor: PROXY_LIST not matched
    assert out.count("HTTPS_PROXY=") == 1  # no dup lines


def test_set_env_direct_empties(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("HTTPS_PROXY=http://127.0.0.1:12343\nHTTP_PROXY=http://127.0.0.1:12343\n",
                   encoding="utf-8")
    monkeypatch.setattr(proxy_routes, "ENV_FILE", env)
    proxy_routes._set_env_proxy("direct")
    out = env.read_text()
    assert "HTTPS_PROXY=\n" in out
    assert "HTTP_PROXY=\n" in out


def test_set_env_appends_when_missing(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("SOME_OTHER=1\n", encoding="utf-8")
    monkeypatch.setattr(proxy_routes, "ENV_FILE", env)
    proxy_routes._set_env_proxy("http://127.0.0.1:12343")
    out = env.read_text()
    assert "SOME_OTHER=1" in out
    assert "HTTPS_PROXY=http://127.0.0.1:12343" in out
    assert "HTTP_PROXY=http://127.0.0.1:12343" in out


@pytest.mark.asyncio
async def test_port_open_probe():
    # closed port → False, fast
    assert await st._port_open("127.0.0.1", 1, timeout=1) is False
    # open port → True
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        assert await st._port_open("127.0.0.1", port, timeout=2) is True
    finally:
        server.close()


@pytest.mark.asyncio
async def test_health_gate_blocks_dead_vps(monkeypatch):
    # unroutable host → health-gate must NOT spawn ssh
    t = st.Tunnel(name="dead", local_port=19997, host="10.255.255.1",
                  remote_port=3128, key_path="")
    spawn = AsyncMock()
    monkeypatch.setattr(st, "_port_open", AsyncMock(return_value=False))
    monkeypatch.setattr(st.asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(st._tunnel_loop(t))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    await task
    spawn.assert_not_awaited()
    assert t.running is False


@pytest.mark.asyncio
async def test_start_tunnel_adopts_already_bound_external_forward(monkeypatch):
    tunnel = st.Tunnel(
        name="systemd-owned",
        local_port=12341,
        host="example.invalid",
        remote_port=3128,
        key_path="",
    )
    monkeypatch.setattr(st, "_parse_tunnels", lambda: [tunnel])
    monkeypatch.setattr(st, "_port_open", AsyncMock(return_value=True))

    await st.start_tunnel()

    assert tunnel.externally_managed is True
    assert tunnel.running is True
    assert tunnel.task is None


@pytest.mark.asyncio
async def test_start_stop_never_signals_similar_foreign_process(monkeypatch):
    tunnel = st.Tunnel(
        name="owned",
        local_port=23456,
        host="198.51.100.42",
        remote_port=34567,
        key_path="",
    )
    old_match = (
        "ssh -N -L 23456:127.0.0.1:34567 "
        "-o ExitOnForwardFailure=yes root@198.51.100.42"
    )
    foreign = subprocess.Popen(
        [old_match, "-c", "import time; time.sleep(30)"],
        executable=sys.executable,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    monkeypatch.setattr(st, "_parse_tunnels", lambda: [tunnel])
    monkeypatch.setattr(st, "_port_open", AsyncMock(return_value=False))

    try:
        await st.start_tunnel()
        assert foreign.poll() is None
        await st.stop_tunnel()
        assert foreign.poll() is None
    finally:
        foreign.terminate()
        foreign.wait(timeout=5)
