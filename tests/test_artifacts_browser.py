"""#294 T3 Chromium oracle for the trusted wrapper and sandboxed artifact child."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import ipaddress
import os
import socket
import threading
from contextlib import contextmanager

import pytest
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from playwright.sync_api import sync_playwright

from tests.test_artifacts import (
    NOW,
    SECRET_TEXT,
    _insert_active_artifact,
)


def _write_ephemeral_certificate(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "127.0.0.1")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                x509.DNSName("localhost"),
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    key_path = tmp_path / "artifact-test.key"
    cert_path = tmp_path / "artifact-test.crt"
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    spki = key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    pin = base64.b64encode(hashlib.sha256(spki).digest()).decode()
    return key_path, cert_path, pin


class _ReadyServer(uvicorn.Server):
    def __init__(self, config, ready):
        super().__init__(config)
        self._ready = ready

    def install_signal_handlers(self):
        return None

    async def startup(self, sockets=None):
        await super().startup(sockets=sockets)
        self._ready.set()


@contextmanager
def _https_server(app, tmp_path):
    key_path, cert_path, pin = _write_ephemeral_certificate(tmp_path)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    ready = threading.Event()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        ssl_keyfile=str(key_path),
        ssl_certfile=str(cert_path),
        log_level="error",
        access_log=False,
    )
    server = _ReadyServer(config, ready)
    thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [sock]},
        daemon=True,
    )
    thread.start()
    assert ready.wait(timeout=10), "ephemeral HTTPS artifact server did not start"
    try:
        yield f"https://127.0.0.1:{port}", pin
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive(), "ephemeral HTTPS artifact server did not stop"


@pytest.fixture
def browser_artifact_env(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setenv("STATE_DIRECTORY", str(state))
    monkeypatch.setenv("ARTIFACT_PUBLIC_LINKS_ENABLED", "1")
    monkeypatch.setenv("ARTIFACT_LINK_SECRET", SECRET_TEXT)
    monkeypatch.setenv("ARTIFACT_DEFAULT_TTL_SECONDS", "86400")
    monkeypatch.setenv("ARTIFACT_MAX_TTL_SECONDS", "604800")
    monkeypatch.setenv("ARTIFACT_MAX_BYTES", "10485760")
    monkeypatch.setenv("DASHBOARD_USER", "operator")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "dashboard-secret")
    monkeypatch.setenv("INTERNAL_TOKEN", "internal-test-token")
    from app import db

    db.init_db()
    return state


def test_t3_chromium_keeps_active_html_in_the_sandboxed_child(
    browser_artifact_env, tmp_path, monkeypatch,
):
    assert os.getenv("ARTIFACT_BROWSER", "chromium") == "chromium", (
        "T3 is the Chromium gate; Firefox/WebKit are the out-of-scope T4 matrix"
    )
    from app.main import app
    from tests.test_routes_surface import route_surface

    paths = {path for path, _methods in route_surface()}
    assert "/api/artifacts/open/{locator}/content" in paths, (
        "#294 missing contract: trusted wrapper/sandbox content route is absent"
    )

    locator = "N" * 22
    capability = "P" * 43
    artifact_marker = "MALICIOUS_CHILD_EXECUTED"
    artifact = f"""<!doctype html>
<p id="ran">not-run</p>
<script>
  window.__sandbox = {{cookie: "unread", storage: "unread"}};
  try {{ window.__sandbox.cookie = document.cookie; }} catch (e) {{ window.__sandbox.cookie = "blocked"; }}
  try {{ localStorage.setItem("artifact", "1"); window.__sandbox.storage = "writable"; }}
  catch (e) {{ window.__sandbox.storage = "blocked"; }}
  fetch("/api/sessions").catch(() => {{}});
  fetch("https://example.invalid/artifact-collector").catch(() => {{}});
  try {{ window.open("https://example.invalid/popup"); }} catch (e) {{}}
  try {{ top.location = "https://example.invalid/replaced-parent"; }} catch (e) {{}}
  document.getElementById("ran").textContent = "{artifact_marker}";
</script>""".encode()
    _insert_active_artifact(
        browser_artifact_env,
        locator=locator,
        capability=capability,
        body=artifact,
    )

    server_targets = []

    async def captured_app(scope, receive, send):
        if scope["type"] == "http":
            target = scope.get("raw_path", scope["path"].encode()).decode()
            if scope.get("query_string"):
                target += "?" + scope["query_string"].decode()
            server_targets.append(target)
        await app(scope, receive, send)

    with _https_server(captured_app, tmp_path) as (base_url, spki_pin):
        monkeypatch.setenv("PUBLIC_BASE_URL", base_url)
        browser_requests = []
        popups = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=[f"--ignore-certificate-errors-spki-list={spki_pin}"],
            )
            try:
                context = browser.new_context()
                context.add_cookies([{
                    "name": "session",
                    "value": "dashboard-cookie-must-not-authorize-content",
                    "url": base_url,
                    "secure": True,
                }])
                context.on("request", lambda request: browser_requests.append(request.url))
                page = context.new_page()
                page.on("popup", lambda popup: popups.append(popup.url))
                page.goto(
                    f"{base_url}/api/artifacts/open/{locator}#{capability}",
                    wait_until="networkidle",
                )
                child = page.frame_locator("iframe#artifact")
                child.locator("#ran").wait_for(state="visible")
                assert child.locator("#ran").text_content() == artifact_marker
                sandbox = child.locator("body").evaluate("() => window.__sandbox")

                assert page.url == f"{base_url}/api/artifacts/open/{locator}"
                assert sandbox["cookie"] in {"", "blocked"}
                assert sandbox["storage"] == "blocked"
                assert popups == []
                assert not any("/api/sessions" in url for url in browser_requests)
                assert not any("example.invalid" in url for url in browser_requests)
                assert all(capability not in target for target in server_targets)

                direct = context.new_page()
                response = direct.goto(
                    f"{base_url}/api/artifacts/open/{locator}/content",
                    wait_until="domcontentloaded",
                )
                assert response is not None and response.status == 404
                assert artifact_marker not in direct.content()
                assert page.url == f"{base_url}/api/artifacts/open/{locator}"
            finally:
                browser.close()
