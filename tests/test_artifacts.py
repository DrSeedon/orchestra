"""#294 RED oracles for the private artifact publication boundary.

These tests intentionally describe the security contract before the runtime exists.  Executors
may change production code, but this file is the immutable T1/T2 acceptance boundary.
"""

from __future__ import annotations

import base64
import asyncio
import hashlib
import hmac
import importlib
import os
import re
from collections.abc import Mapping
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


NOW = 2_000_000_000
SECRET_BYTES = b"#294-artifact-link-secret" + b"x" * 16
SECRET_TEXT = base64.urlsafe_b64encode(SECRET_BYTES).rstrip(b"=").decode()


def _artifacts():
    try:
        return importlib.import_module("app.artifacts")
    except ModuleNotFoundError as exc:
        if exc.name != "app.artifacts":
            raise
        pytest.fail(
            "#294 missing contract: app.artifacts does not provide the private "
            "snapshot/registry boundary",
            pytrace=False,
        )


def _value(result, key):
    if isinstance(result, Mapping):
        return result[key]
    return getattr(result, key)


def _capability_verifier(capability: str, secret: bytes = SECRET_BYTES) -> bytes:
    return hmac.new(
        secret,
        b"artifact-cap-v1\0" + capability.encode("ascii"),
        hashlib.sha256,
    ).digest()


@pytest.fixture
def artifact_env(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setenv("STATE_DIRECTORY", str(state))
    monkeypatch.setenv("ARTIFACT_PUBLIC_LINKS_ENABLED", "1")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://testserver")
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


def _artifact_columns():
    from app.db import _conn

    with _conn() as conn:
        return [row[1] for row in conn.execute("PRAGMA table_info(artifacts)").fetchall()]


def _insert_active_artifact(
    state: Path,
    *,
    locator: str,
    capability: str,
    body: bytes,
    display_name: str = "report.html",
) -> Path:
    from app.db import _conn

    store = state / "artifacts"
    store.mkdir(parents=True, exist_ok=True, mode=0o700)
    stored_name = f"{locator}.html"
    stored = store / stored_name
    stored.write_bytes(body)
    stored.chmod(0o600)
    with _conn() as conn:
        conn.execute(
            """INSERT INTO artifacts (
                   id, capability_verifier, stored_name, content_sha256, display_name,
                   publisher_session_id, publisher_name, scope, size_bytes, created_at,
                   expires_at, state, activated_at, revoked_at, last_opened_at, open_count
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, NULL, NULL, 0)""",
            (
                locator,
                _capability_verifier(capability),
                stored_name,
                hashlib.sha256(body).digest(),
                display_name,
                "publisher-session",
                "publisher",
                "/scope",
                len(body),
                NOW,
                NOW + 3600,
                NOW,
            ),
        )
    return stored


def _swap_path_after_open(monkeypatch, module, target: Path, replacement: bytes):
    real_open = os.open
    swapped = {"done": False}

    def racing_open(path, flags, mode=0o777, *, dir_fd=None):
        fd = real_open(path, flags, mode, dir_fd=dir_fd)
        if (
            not swapped["done"]
            and not flags & os.O_DIRECTORY
            and Path(os.fsdecode(path)).name == target.name
        ):
            moved = target.with_name(f"{target.name}.opened")
            target.rename(moved)
            target.write_bytes(replacement)
            swapped["done"] = True
        return fd

    monkeypatch.setattr(module.os, "open", racing_open)
    return swapped


def test_t1_private_registry_is_present_before_snapshot(artifact_env):
    assert "id" in _artifact_columns(), (
        "#294 missing contract: init_db() did not create the private artifacts registry"
    )


def test_t1_snapshot_copies_the_authorized_inode_and_stores_no_bearer(
    artifact_env, tmp_path, monkeypatch,
):
    artifacts = _artifacts()
    root = tmp_path / "allowed"
    root.mkdir()
    source = root / "report.html"
    original = b"<!doctype html><p>authorized bytes</p>"
    attacker = b"<!doctype html><p>retargeted attacker bytes</p>"
    source.write_bytes(original)
    swapped = _swap_path_after_open(monkeypatch, artifacts, source, attacker)

    published = artifacts.publish_snapshot(
        source_path=str(source),
        allowed_roots=(str(root),),
        publisher_session_id="publisher-session",
        publisher_name="publisher",
        scope="/scope",
        ttl_seconds=600,
        now=NOW,
    )

    assert swapped["done"], "race probe never reached the opened source descriptor"
    locator = _value(published, "id")
    capability = _value(published, "capability")
    assert _value(published, "content_sha256") == hashlib.sha256(original).digest()
    assert _value(published, "size_bytes") == len(original)
    decoded_capability = base64.urlsafe_b64decode(
        capability + "=" * (-len(capability) % 4)
    )
    assert len(decoded_capability) >= 32

    from app.db import _conn

    with _conn() as conn:
        row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (locator,)).fetchone()
    assert row is not None
    assert row["state"] == "pending"
    assert row["content_sha256"] == hashlib.sha256(original).digest()
    assert row["capability_verifier"] == _capability_verifier(capability)
    assert "source_path" not in row.keys()
    assert str(source) not in "\n".join(str(value) for value in row)
    assert capability not in "\n".join(str(value) for value in row)

    stored = artifact_env / "artifacts" / row["stored_name"]
    assert row["stored_name"] == f"{locator}.html"
    assert stored.read_bytes() == original
    assert stored.stat().st_mode & 0o777 == 0o600
    assert stored.parent.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("source_kind", ["outside", "symlink"])
def test_t1_snapshot_rejects_paths_outside_registered_roots(
    artifact_env, tmp_path, source_kind,
):
    artifacts = _artifacts()
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "outside.html"
    outside.write_text("<p>outside</p>")
    source = outside
    if source_kind == "symlink":
        source = root / "linked.html"
        source.symlink_to(outside)

    from app.db import _conn

    with pytest.raises(Exception):
        artifacts.publish_snapshot(
            source_path=str(source),
            allowed_roots=(str(root),),
            publisher_session_id="publisher-session",
            publisher_name="publisher",
            scope="/scope",
            ttl_seconds=600,
            now=NOW,
        )
    with _conn() as conn:
        assert conn.execute("SELECT count(*) FROM artifacts").fetchone()[0] == 0
    store = artifact_env / "artifacts"
    assert not store.exists() or list(store.iterdir()) == []


def test_t2_open_returns_the_verified_immutable_buffer_after_path_retarget(
    artifact_env, monkeypatch,
):
    artifacts = _artifacts()
    locator = "A" * 22
    capability = "B" * 43
    original = (b"<!doctype html><p>registered buffer</p>" * 4096)
    attacker = b"<script>top.location='https://attacker.invalid'</script>"
    stored = _insert_active_artifact(
        artifact_env, locator=locator, capability=capability, body=original,
    )
    swapped = _swap_path_after_open(monkeypatch, artifacts, stored, attacker)

    opened = artifacts.open_artifact_buffer(locator, now=NOW + 1)

    assert swapped["done"], "race probe never reached the stored-file descriptor"
    assert type(opened) is bytes
    assert opened == original


def test_t2_open_rejects_an_inode_changed_after_descriptor_open(
    artifact_env, monkeypatch,
):
    artifacts = _artifacts()
    locator = "C" * 22
    capability = "D" * 43
    original = b"<!doctype html><p>registered</p>"
    attacker = b"<!doctype html><p>substitute</p>"
    assert len(original) == len(attacker)
    stored = _insert_active_artifact(
        artifact_env, locator=locator, capability=capability, body=original,
    )
    real_open = os.open
    mutated = {"done": False}

    def racing_open(path, flags, mode=0o777, *, dir_fd=None):
        fd = real_open(path, flags, mode, dir_fd=dir_fd)
        if (
            not mutated["done"]
            and not flags & os.O_DIRECTORY
            and Path(os.fsdecode(path)).name == stored.name
        ):
            os.pwrite(fd, attacker, 0)
            mutated["done"] = True
        return fd

    monkeypatch.setattr(artifacts.os, "open", racing_open)
    with pytest.raises(Exception):
        artifacts.open_artifact_buffer(locator, now=NOW + 1)
    assert mutated["done"], "integrity probe never mutated the opened stored inode"


def _artifact_client():
    from app.main import app
    from tests.test_routes_surface import route_surface

    surface = set(route_surface())
    assert any(path == "/api/artifacts/open/{locator}/redeem" for path, _ in surface), (
        "#294 missing contract: artifact redeem/content routes are not registered"
    )
    return TestClient(
        app,
        base_url="https://testserver",
        raise_server_exceptions=False,
    )


def test_t2_grant_is_bound_to_locator_secret_and_exact_iframe_destination(artifact_env):
    first_locator = "E" * 22
    second_locator = "F" * 22
    capability = "G" * 43
    body = b"<!doctype html><p id='artifact-body'>private</p>"
    _insert_active_artifact(
        artifact_env, locator=first_locator, capability=capability, body=body,
    )
    _insert_active_artifact(
        artifact_env,
        locator=second_locator,
        capability="H" * 43,
        body=b"<!doctype html><p>other</p>",
    )
    content_path = f"/api/artifacts/open/{first_locator}/content"

    with _artifact_client() as dashboard:
        from app.auth import create_session

        dashboard.cookies.set("session", create_session("operator"), path="/")
        denied = dashboard.get(content_path, headers={"Sec-Fetch-Dest": "iframe"})
        assert denied.status_code == 404
        assert body not in denied.content

    with _artifact_client() as granted:
        redeemed = granted.post(
            f"/api/artifacts/open/{first_locator}/redeem",
            json={"capability": capability},
        )
        assert redeemed.status_code in {200, 204}
        set_cookie = redeemed.headers["set-cookie"]
        assert "orchestra_artifact_grant=" in set_cookie
        for flag in (
            "Secure",
            "HttpOnly",
            "SameSite=Strict",
            f"Path=/api/artifacts/open/{first_locator}",
        ):
            assert flag.lower() in set_cookie.lower()

        wrong_dest = granted.get(
            content_path, headers={"Sec-Fetch-Dest": "document"},
        )
        assert wrong_dest.status_code == 404
        assert body not in wrong_dest.content

        served = granted.get(content_path, headers={"Sec-Fetch-Dest": "iframe"})
        assert served.status_code == 200
        assert served.content == body
        content_csp = served.headers["content-security-policy"]
        assert content_csp.startswith("sandbox allow-scripts;")
        for directive in (
            "connect-src 'none'",
            "object-src 'none'",
            "base-uri 'none'",
            "form-action 'none'",
            "frame-src 'none'",
            "frame-ancestors 'self'",
        ):
            assert directive in content_csp
        assert "allow-same-origin" not in content_csp
        assert "'unsafe-eval'" not in content_csp
        assert served.headers["content-type"] == "text/html; charset=utf-8"
        assert served.headers["cache-control"] == "no-store, private, max-age=0"
        assert served.headers["referrer-policy"] == "no-referrer"
        assert served.headers["x-content-type-options"] == "nosniff"
        assert not ({"etag", "last-modified"} & set(served.headers))

        ranged = granted.get(
            content_path,
            headers={"Sec-Fetch-Dest": "iframe", "Range": "bytes=0-3"},
        )
        assert ranged.status_code in {400, 404, 416}
        assert body not in ranged.content

        grant = granted.cookies.get("orchestra_artifact_grant")
        assert grant and capability not in grant and first_locator in grant
        wrong_path = granted.get(
            f"/api/artifacts/open/{second_locator}/content",
            headers={
                "Sec-Fetch-Dest": "iframe",
                "Cookie": f"orchestra_artifact_grant={grant}",
            },
        )
        assert wrong_path.status_code == 404
        assert body not in wrong_path.content

        os.environ["ARTIFACT_LINK_SECRET"] = base64.urlsafe_b64encode(
            b"rotated-secret" + b"z" * 32
        ).rstrip(b"=").decode()
        old_fragment = granted.post(
            f"/api/artifacts/open/{first_locator}/redeem",
            json={"capability": capability},
        )
        old_grant = granted.get(
            content_path,
            headers={
                "Sec-Fetch-Dest": "iframe",
                "Cookie": f"orchestra_artifact_grant={grant}",
            },
        )
        assert old_fragment.status_code == 404
        assert old_grant.status_code == 404
        assert body not in old_grant.content


def test_t2_wrapper_is_fixed_trusted_top_level_and_artifact_is_only_the_child(
    artifact_env,
):
    locator = "J" * 22
    capability = "K" * 43
    marker = b"TOP_LEVEL_ARTIFACT_MARKER"
    body = b"<!doctype html><script>window.childRan=true</script>" + marker
    _insert_active_artifact(
        artifact_env, locator=locator, capability=capability, body=body,
    )

    with _artifact_client() as client:
        assert client.post(
            f"/api/artifacts/open/{locator}/redeem",
            json={"capability": capability},
        ).status_code in {200, 204}
        wrapper = client.get(f"/api/artifacts/open/{locator}")

    assert wrapper.status_code == 200
    assert marker not in wrapper.content
    assert locator not in wrapper.text
    assert capability not in wrapper.text
    assert (
        '<iframe id="artifact" sandbox="allow-scripts" '
        'referrerpolicy="no-referrer"></iframe>'
    ) in wrapper.text
    assert "allow-same-origin" not in wrapper.text
    assert "allow-forms" not in wrapper.text
    assert "allow-popups" not in wrapper.text
    script_match = re.search(r"<script>(.*?)</script>", wrapper.text, re.DOTALL)
    assert script_match, "trusted wrapper must contain one fixed inline loader"
    digest = base64.b64encode(
        hashlib.sha256(script_match.group(1).encode()).digest()
    ).decode()
    assert f"script-src 'sha256-{digest}'" in wrapper.headers["content-security-policy"]
    assert "frame-src 'self'" in wrapper.headers["content-security-policy"]
    assert wrapper.headers["cache-control"] == "no-store, private, max-age=0"
    assert wrapper.headers["referrer-policy"] == "no-referrer"
    assert wrapper.headers["x-content-type-options"] == "nosniff"


def test_t2_revocation_blocks_both_an_existing_grant_and_fragment(
    artifact_env,
):
    from app.auth import create_session

    locator = "Q" * 22
    capability = "R" * 43
    body = b"<!doctype html><p>revocable</p>"
    _insert_active_artifact(
        artifact_env, locator=locator, capability=capability, body=body,
    )
    with _artifact_client() as client:
        assert client.post(
            f"/api/artifacts/open/{locator}/redeem",
            json={"capability": capability},
        ).status_code in {200, 204}
        grant = client.cookies.get("orchestra_artifact_grant")
        client.cookies.set("session", create_session("operator"), path="/")
        revoked = client.post(f"/api/artifacts/{locator}/revoke")
        assert revoked.status_code == 200

        old_grant = client.get(
            f"/api/artifacts/open/{locator}/content",
            headers={
                "Sec-Fetch-Dest": "iframe",
                "Cookie": f"orchestra_artifact_grant={grant}",
            },
        )
        old_fragment = client.post(
            f"/api/artifacts/open/{locator}/redeem",
            json={"capability": capability},
        )
    assert old_grant.status_code == 404
    assert old_fragment.status_code == 404
    assert body not in old_grant.content


def test_t2_content_head_and_raw_file_route_remain_authenticated(artifact_env):
    locator = "L" * 22
    capability = "M" * 43
    _insert_active_artifact(
        artifact_env,
        locator=locator,
        capability=capability,
        body=b"<!doctype html><p>private</p>",
    )
    with _artifact_client() as client:
        raw = client.get("/api/files/raw", params={"path": "/tmp/report.html"})
        content_head = client.head(f"/api/artifacts/open/{locator}/content")
    assert raw.status_code == 401
    assert content_head.status_code == 401


def test_t2_publish_binds_mcp_proof_and_keeps_capability_only_in_telegram(
    artifact_env, tmp_path, monkeypatch, caplog,
):
    import app.tg_bridge as tg_bridge
    from app import db
    from app.mcp_proof import issue_mcp_proof
    from tests.test_acceptance import _session_row

    victim_root = tmp_path / "victim"
    attacker_root = tmp_path / "attacker"
    victim_root.mkdir()
    attacker_root.mkdir()
    source = victim_root / "report.html"
    source.write_text("<!doctype html><p>private publication</p>")

    victim = _session_row(str(victim_root))
    victim.update({
        "id": "victim-session",
        "name": "victim",
        "scope": "/scope",
        "cwd": str(victim_root),
        "worktree_path": str(victim_root),
    })
    attacker = _session_row(str(attacker_root))
    attacker.update({
        "id": "attacker-session",
        "name": "attacker",
        "scope": "/scope",
        "cwd": str(attacker_root),
        "worktree_path": str(attacker_root),
    })
    db.save_session(victim)
    db.save_session(attacker)

    delivered = []

    async def send_text(text, **kwargs):
        delivered.append((text, kwargs))
        return {"ok": True, "message_id": 77, "chat_id": -100}

    monkeypatch.setattr(tg_bridge, "send_text_to_tg", send_text)
    routes = importlib.import_module("app.routes.artifacts")
    monkeypatch.setattr(routes, "send_text_to_tg", send_text, raising=False)
    forged_headers = {
        "Authorization": "Bearer internal-test-token",
        "X-Orchestra-Session-Id": "victim-session",
        "X-Orchestra-Mcp-Proof": issue_mcp_proof("attacker-session"),
    }
    valid_headers = dict(forged_headers)
    valid_headers["X-Orchestra-Mcp-Proof"] = issue_mcp_proof("victim-session")
    payload = {"path": str(source), "caption": "report", "ttl_seconds": 600}

    with _artifact_client() as client:
        forged = client.post(
            "/api/artifacts/publish", headers=forged_headers, json=payload,
        )
        assert forged.status_code == 403
        assert delivered == []
        response = client.post(
            "/api/artifacts/publish", headers=valid_headers, json=payload,
        )

    assert response.status_code == 200
    assert delivered and delivered[0][1] == {
        "scope": "/scope",
        "sender": "victim",
        "disable_link_preview": True,
    }
    match = re.search(
        r"https://testserver/api/artifacts/open/([A-Za-z0-9_-]{22})"
        r"#([A-Za-z0-9_-]{43})(?:\s|$)",
        delivered[0][0],
    )
    assert match, delivered[0][0]
    locator, capability = match.groups()
    response_text = response.text
    assert capability not in response_text
    assert str(source) not in response_text
    assert capability not in caplog.text

    with db._conn() as conn:
        rows = conn.execute("SELECT * FROM artifacts").fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == locator
    assert row["state"] == "active"
    assert row["publisher_session_id"] == "victim-session"
    assert row["capability_verifier"] == _capability_verifier(capability)
    assert capability not in row["stored_name"]


@pytest.mark.parametrize(
    "delivery_error",
    [
        RuntimeError("telegram transport failed after dispatch"),
        asyncio.CancelledError(),
    ],
    ids=["exception", "cancelled-after-dispatch"],
)
def test_t2_failed_telegram_delivery_never_activates_or_auto_sends_file(
    artifact_env, tmp_path, monkeypatch, delivery_error,
):
    import app.tg_bridge as tg_bridge
    from app import db
    from app.mcp_proof import issue_mcp_proof
    from tests.test_acceptance import _session_row

    root = tmp_path / "publisher"
    root.mkdir()
    source = root / "report.html"
    source.write_text("<!doctype html><p>private</p>")
    row = _session_row(str(root))
    row.update({
        "id": "publisher-session",
        "name": "publisher",
        "scope": "/scope",
        "cwd": str(root),
        "worktree_path": str(root),
    })
    db.save_session(row)

    dispatched = []

    async def fail_after_dispatch(text, **kwargs):
        dispatched.append(text)
        raise delivery_error

    file_calls = []

    async def forbidden_file(*args, **kwargs):
        file_calls.append((args, kwargs))
        return {"ok": True, "message_id": 99, "chat_id": -100}

    monkeypatch.setattr(tg_bridge, "send_text_to_tg", fail_after_dispatch)
    monkeypatch.setattr(tg_bridge, "send_file_to_tg", forbidden_file)
    routes = importlib.import_module("app.routes.artifacts")
    monkeypatch.setattr(routes, "send_text_to_tg", fail_after_dispatch, raising=False)
    monkeypatch.setattr(routes, "send_file_to_tg", forbidden_file, raising=False)
    proof = issue_mcp_proof("publisher-session")
    headers = {
        "Authorization": "Bearer internal-test-token",
        "X-Orchestra-Session-Id": "publisher-session",
        "X-Orchestra-Mcp-Proof": proof,
    }

    response = None
    try:
        with _artifact_client() as client:
            response = client.post(
                "/api/artifacts/publish",
                headers=headers,
                json={"path": str(source), "caption": "report", "ttl_seconds": 600},
            )
    except asyncio.CancelledError:
        assert isinstance(delivery_error, asyncio.CancelledError)

    assert dispatched, "delivery failure probe never reached Telegram dispatch"
    assert file_calls == []
    if response is not None:
        assert response.status_code >= 400
        assert str(source) not in response.text
        for sent_text in dispatched:
            capability = sent_text.rsplit("#", 1)[-1].split()[0]
            assert capability not in response.text
        if not isinstance(delivery_error, asyncio.CancelledError):
            assert "send_file" in response.text and "as_document=True" in response.text
    with db._conn() as conn:
        rows = conn.execute("SELECT id, state FROM artifacts").fetchall()
    assert rows
    assert all(row["state"] != "active" for row in rows)
    capability = dispatched[0].rsplit("#", 1)[-1].split()[0]
    locator = rows[0]["id"]
    with _artifact_client() as denied_client:
        redeem = denied_client.post(
            f"/api/artifacts/open/{locator}/redeem",
            json={"capability": capability},
        )
        content = denied_client.get(
            f"/api/artifacts/open/{locator}/content",
            headers={"Sec-Fetch-Dest": "iframe"},
        )
    assert redeem.status_code == 404
    assert content.status_code == 404
    assert source.read_bytes() not in content.content


def test_t2_activation_failure_after_telegram_success_leaves_a_dead_link(
    artifact_env, tmp_path, monkeypatch,
):
    import app.tg_bridge as tg_bridge
    from app import db
    from app.mcp_proof import issue_mcp_proof
    from tests.test_acceptance import _session_row

    root = tmp_path / "publisher"
    root.mkdir()
    source = root / "report.html"
    source.write_text("<!doctype html><p>private</p>")
    row = _session_row(str(root))
    row.update({
        "id": "publisher-session",
        "name": "publisher",
        "scope": "/scope",
        "cwd": str(root),
        "worktree_path": str(root),
    })
    db.save_session(row)
    with db._conn() as conn:
        conn.execute(
            """CREATE TRIGGER fail_artifact_activation
               BEFORE UPDATE OF state ON artifacts
               WHEN NEW.state = 'active'
               BEGIN
                   SELECT RAISE(ABORT, 'forced activation failure');
               END"""
        )

    delivered = []

    async def successful_delivery(text, **kwargs):
        delivered.append(text)
        return {"ok": True, "message_id": 77, "chat_id": -100}

    monkeypatch.setattr(tg_bridge, "send_text_to_tg", successful_delivery)
    routes = importlib.import_module("app.routes.artifacts")
    monkeypatch.setattr(
        routes, "send_text_to_tg", successful_delivery, raising=False,
    )
    headers = {
        "Authorization": "Bearer internal-test-token",
        "X-Orchestra-Session-Id": "publisher-session",
        "X-Orchestra-Mcp-Proof": issue_mcp_proof("publisher-session"),
    }

    with _artifact_client() as client:
        response = client.post(
            "/api/artifacts/publish",
            headers=headers,
            json={"path": str(source), "caption": "report", "ttl_seconds": 600},
        )

    assert delivered, "activation failure probe never reached successful TG delivery"
    assert response.status_code >= 400
    assert str(source) not in response.text
    assert "send_file" in response.text and "as_document=True" in response.text
    capability = delivered[0].rsplit("#", 1)[-1].split()[0]
    assert capability not in response.text
    with db._conn() as conn:
        stored = conn.execute("SELECT id, state FROM artifacts").fetchone()
    assert stored is not None and stored["state"] != "active"

    with _artifact_client() as denied_client:
        redeem = denied_client.post(
            f"/api/artifacts/open/{stored['id']}/redeem",
            json={"capability": capability},
        )
        content = denied_client.get(
            f"/api/artifacts/open/{stored['id']}/content",
            headers={"Sec-Fetch-Dest": "iframe"},
        )
    assert redeem.status_code == 404
    assert content.status_code == 404
