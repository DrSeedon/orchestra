"""Proxy manager (read-only, .env source of truth) + ssh_tunnel health-gate."""

import asyncio

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
async def test_health_gate_blocks_dead_vps():
    # unroutable host → health-gate must NOT spawn ssh
    t = st.Tunnel(name="dead", local_port=19997, host="10.255.255.1",
                  remote_port=3128, key_path="")
    task = asyncio.create_task(st._tunnel_loop(t))
    await asyncio.sleep(st.HEALTH_TIMEOUT + 1)  # one failed probe → backoff
    # match only real ssh processes (comm==ssh) — pgrep -f self-matches this
    # test's own cmdline otherwise
    proc = await asyncio.create_subprocess_exec(
        "pgrep", "-x", "ssh", "-f", "ssh -N -L 19997:127.0.0.1:",
        stdout=asyncio.subprocess.PIPE)
    out, _ = await proc.communicate()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert not out.decode().strip(), "dead VPS must not spawn ssh"
    assert t.running is False
