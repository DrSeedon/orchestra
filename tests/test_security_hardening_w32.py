"""Wave 32 security hardening regressions (#1 XSS, #2 MCP file scope, #3 /login rate limit, #4 revocable sessions, #5 installer/nginx, #6 CI)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_utils_js_sanitizes_before_dom_parse_and_blocks_external_img_src():
    script = r"""
const fs = require("fs");
const vm = require("vm");
const utilsCode = fs.readFileSync("app/static/js/utils.js", "utf8");
const sliceStart = utilsCode.indexOf("marked.setOptions(");
const sliceEnd = utilsCode.indexOf("// Global click handler:");
if (sliceStart < 0 || sliceEnd < 0) throw new Error("utils.js slice not found");

const sanitizeCalls = [];
const innerHtmlWrites = [];
const hooks = {};
const safeUrlRe = /^\/(?:uploads|charts|api|static)\//;

function fakeNode(tag, attrs = {}, children = []) {
  return {
    nodeType: 1,
    tagName: tag.toUpperCase(),
    attributes: { ...attrs },
    childNodes: children,
    hasAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attributes, k); },
    getAttribute(k) { return this.attributes[k]; },
    removeAttribute(k) { delete this.attributes[k]; },
    remove() { this._removed = true; },
  };
}

class FakeDOMParser {
  parseFromString(html) {
    // Minimal inert parser verifying html has no xss payloads when parsed.
    if (html.includes("onerror=") || html.includes("onload=")) {
      throw new Error("Unsanitized event handler reached DOMParser: " + html);
    }
    const textNode = {
      nodeType: 3,
      textContent: "Visit https://example.com/a and /charts/c.png",
      parentNode: null,
    };
    const body = {
      nodeType: 1,
      tagName: "BODY",
      childNodes: [textNode],
      ownerDocument: {
        createDocumentFragment() {
          const items = [];
          return {
            _items: items,
            appendChild(n) { items.push(n); },
          };
        },
        createTextNode(t) { return { nodeType: 3, textContent: t }; },
        createElement(tag) { return { nodeType: 1, tagName: tag.toUpperCase(), textContent: "" }; },
      },
    };
    body.replaceChild = (newNode, oldNode) => {
      const idx = body.childNodes.indexOf(oldNode);
      if (idx >= 0) {
        const items = newNode._items ? newNode._items : [newNode];
        body.childNodes.splice(idx, 1, ...items);
      }
    };
    body.childNodes.forEach((n) => { n.parentNode = body; });
    body.ownerDocument.body = body;
    Object.defineProperty(body, "innerHTML", {
      get() {
        return body.childNodes.flatMap((n) => n._items ? n._items : [n]).map((n) => {
          if (n.nodeType === 3) return n.textContent;
          if (n.tagName === "A") return `<a href="${n.href}" target="${n.target}" rel="${n.rel}">${n.textContent}</a>`;
          return "";
        }).join("");
      },
      set(val) {
        innerHtmlWrites.push(val);
      },
    });
    return { body };
  }
}

const sandbox = {
  DOMParser: FakeDOMParser,
  document: {
    createElement() {
      return {
        set innerHTML(val) { innerHtmlWrites.push(val); },
        get innerHTML() { return ""; },
        appendChild() {},
      };
    },
  },
  DOMPurify: {
    addHook(name, fn) { (hooks[name] ||= []).push(fn); },
    sanitize(raw, opts) {
      sanitizeCalls.push({ raw, opts });
      let cleaned = String(raw)
        .replace(/\s+on\w+\s*=\s*[^\s>]+/gi, "")
        .replace(/<svg[\s\S]*?<\/svg>/gi, "");
      for (const match of cleaned.matchAll(/<img\b([^>]*)>/gi)) {
        const srcM = match[1].match(/src=["']?([^"'\s>]+)["']?/i);
        if (srcM) {
          const img = fakeNode("IMG", { src: srcM[1] });
          for (const h of (hooks.afterSanitizeAttributes || [])) h(img);
          if (!img.hasAttribute("src")) {
            cleaned = cleaned.replace(match[0], "<img alt=\"blocked\">");
          }
        }
      }
      return cleaned;
    },
  },
  marked: {
    setOptions() {},
    parse(src) {
      return src;
    },
  },
};

vm.runInNewContext(utilsCode.slice(sliceStart, sliceEnd), sandbox);

const outXss = sandbox.marked.parse('<img src=x onerror=alert(1)><svg onload=alert(1)> <img src="https://evil.com/leak.png"> <img src="/charts/c.png">');
if (innerHtmlWrites.length !== 0) {
  throw new Error("innerHTML setter must not be used during marked.parse/autolinkText: " + JSON.stringify(innerHtmlWrites));
}
if (sanitizeCalls.length < 1) throw new Error("DOMPurify.sanitize must run inside marked.parse");
if (outXss.includes("onerror=") || outXss.includes("<svg")) throw new Error("XSS survived: " + outXss);
if (!outXss.includes("https://example.com/a") || !outXss.includes("<a href=\"https://example.com/a\"")) {
  throw new Error("Autolink failed: " + outXss);
}

// Also verify hook rejects external URLs while keeping /uploads/, /charts/, /api/, and safe data:image/png
const extImg = fakeNode("IMG", { src: "https://evil.com/pixel.png" });
const localChart = fakeNode("IMG", { src: "/charts/q.png" });
const localUpload = fakeNode("IMG", { src: "/uploads/u.png" });
const dataImg = fakeNode("IMG", { src: "data:image/png;base64,AAAA" });
const svgData = fakeNode("IMG", { src: "data:image/svg+xml;base64,AAAA" });
for (const n of [extImg, localChart, localUpload, dataImg, svgData]) {
  for (const h of (hooks.afterSanitizeAttributes || [])) h(n);
}
if (extImg.hasAttribute("src")) throw new Error("External img src must be removed");
if (svgData.hasAttribute("src")) throw new Error("SVG data URI img src must be removed");
if (!localChart.hasAttribute("src") || !localUpload.hasAttribute("src") || !dataImg.hasAttribute("src")) {
  throw new Error("Safe local/data image src was unexpectedly stripped");
}
console.log("UTILS_XSS_HARDENING_OK");
"""
    proc = subprocess.run(["node", "-e", script], cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    assert "UTILS_XSS_HARDENING_OK" in proc.stdout


@pytest.mark.asyncio
async def test_tg_send_file_enforces_authenticated_mcp_session_scope_and_symlinks(tmp_path, monkeypatch):
    from app import db, tg_bridge, tg_file_deliveries
    from app.charts import CHART_DIR
    from app.mcp_proof import issue_mcp_proof
    from app.routes import tg
    import app.routes.system as sys_routes

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "w32-tg.db")
    db.init_db()
    monkeypatch.setenv("INTERNAL_TOKEN", "test-mcp-token-w32")
    monkeypatch.setenv("ALLOWED_ROOTS", str(tmp_path))
    monkeypatch.setattr(sys_routes, "_ALLOWED_ROOTS", [])
    monkeypatch.setattr(tg_bridge, "config", {"group_id": -1001, "topics": {"proj-a": 11}, "mirrors": {}})
    monkeypatch.setattr(tg_bridge, "_resolve_topic", lambda _s, _n: ("proj-a", 11))

    proj_a = tmp_path / "proj_a"
    proj_b = tmp_path / "proj_b"
    wt_a = tmp_path / "worktree_a"
    proj_a.mkdir()
    proj_b.mkdir()
    wt_a.mkdir()
    in_a = proj_a / "report.txt"
    in_a.write_text("ok a", encoding="utf-8")
    in_wt = wt_a / "patch.txt"
    in_wt.write_text("ok wt", encoding="utf-8")
    in_b = proj_b / "secret_b.txt"
    in_b.write_text("secret b", encoding="utf-8")
    symlink_to_b = proj_a / "escape_link.txt"
    symlink_to_b.symlink_to(in_b)

    CHART_DIR.mkdir(parents=True, exist_ok=True)
    chart_file = CHART_DIR / "w32-test-chart.png"
    chart_file.write_bytes(b"png")

    sid = "sess-proj-a"
    with db._conn() as conn:
        conn.execute(
            """INSERT INTO sessions (id, name, scope, cwd, model, status, worktree_path, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, '2026-11-25T00:00:00Z')""",
            (sid, "worker-a", str(proj_a), str(wt_a), "hub-gpt-6.2-sol", "running", str(wt_a)),
        )
    proof = issue_mcp_proof(sid)
    headers = {"x-orchestra-session-id": sid, "x-orchestra-mcp-proof": proof}

    accepted = []

    async def fake_single(**kw):
        accepted.append(kw["source_path"])
        return ({"ok": True, "acceptance": "ACCEPTED", "event_id": kw["event_id"], "delivery_state": "QUEUED"}, 202, {})

    async def fake_batch(**kw):
        accepted.extend(kw["source_paths"])
        return ({"ok": True, "acceptance": "ACCEPTED", "event_id": kw["event_id"], "delivery_state": "QUEUED"}, 202, {})

    monkeypatch.setattr(tg_file_deliveries, "accept_file_delivery", fake_single)
    monkeypatch.setattr(tg_file_deliveries, "accept_file_batch", fake_batch)

    app = FastAPI()
    app.include_router(tg.router)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            # Cross-project direct path and symlink escape are rejected (single & batch).
            r_b = await client.post("/api/tg/send_file", headers=headers, json={
                "path": str(in_b), "event_id": "00000000-0000-4000-8000-000000000001",
            })
            assert r_b.status_code == 403

            r_sym = await client.post("/api/tg/send_file", headers=headers, json={
                "path": str(symlink_to_b), "event_id": "00000000-0000-4000-8000-000000000002",
            })
            assert r_sym.status_code == 403

            r_batch_bad = await client.post("/api/tg/send_file", headers=headers, json={
                "paths": [str(in_a), str(symlink_to_b)], "event_id": "00000000-0000-4000-8000-000000000003",
            })
            assert r_batch_bad.status_code == 403

            # Own project, own worktree, and CHART_DIR are admitted.
            r_ok_a = await client.post("/api/tg/send_file", headers=headers, json={
                "path": str(in_a), "event_id": "00000000-0000-4000-8000-000000000004",
            })
            assert r_ok_a.status_code == 202

            r_ok_batch = await client.post("/api/tg/send_file", headers=headers, json={
                "paths": [str(in_wt), str(chart_file)], "event_id": "00000000-0000-4000-8000-000000000005",
            })
            assert r_ok_batch.status_code == 202
    finally:
        chart_file.unlink(missing_ok=True)
        monkeypatch.setattr(sys_routes, "_ALLOWED_ROOTS", [])
    assert accepted == [str(in_a), str(in_wt), str(chart_file)]


def test_dashboard_sessions_revocable_ttl_and_credential_invalidation(tmp_path, monkeypatch):
    from app import auth, db
    from app.main import app
    from app.routes import system as sys_routes

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "w32-auth.db")
    db.init_db()
    sys_routes._reset_login_rate_limits()
    monkeypatch.setenv("DASHBOARD_USER", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pass-one")

    with TestClient(app) as client:
        r_login = client.post("/login", data={"username": "admin", "password": "pass-one"}, follow_redirects=False)
        assert r_login.status_code == 302
        cookie_val = client.cookies.get("session")
        assert cookie_val and cookie_val != auth.create_csrf_token("admin")
        assert auth.validate_session(cookie_val) is True
        assert client.get("/api/sessions", follow_redirects=False).status_code == 200

        # Logout revokes DB record -> old cookie is rejected immediately.
        r_logout = client.post("/logout", follow_redirects=False)
        assert r_logout.status_code == 302
        assert auth.validate_session(cookie_val) is False
        client.cookies.set("session", cookie_val)
        assert client.get("/api/sessions", follow_redirects=False).status_code == 401
        assert client.get("/", follow_redirects=False).status_code == 302

    # Fresh session expires when expires_at is in the past or password changes.
    tok2 = auth.create_session("admin")
    assert auth.validate_session(tok2) is True
    with db._conn() as conn:
        conn.execute("UPDATE dashboard_sessions SET expires_at = 1.0 WHERE token_hash = ?", (auth._token_hash(tok2),))
    assert auth.validate_session(tok2) is False

    tok3 = auth.create_session("admin")
    assert auth.validate_session(tok3) is True
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pass-two")
    assert auth.validate_session(tok3) is False


def test_login_rate_limit_blocks_after_ten_failures_and_resets_on_success(tmp_path, monkeypatch):
    from app import db
    from app.main import app
    from app.routes import system as sys_routes

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "w32-rate.db")
    db.init_db()
    sys_routes._reset_login_rate_limits()
    monkeypatch.setenv("DASHBOARD_USER", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "right-pass")

    with TestClient(app) as client:
        for _ in range(10):
            r = client.post(
                "/login",
                headers={"X-Real-IP": "198.51.100.42"},
                data={"username": "admin", "password": "wrong"},
                follow_redirects=False,
            )
            assert r.status_code == 401
        r_11 = client.post(
            "/login",
            headers={"X-Real-IP": "198.51.100.42"},
            data={"username": "admin", "password": "wrong"},
            follow_redirects=False,
        )
        assert r_11.status_code == 429
        assert r_11.headers.get("retry-after") == "900"

        # Different IP still works and resets its bucket on successful login.
        for _ in range(3):
            assert client.post(
                "/login",
                headers={"X-Real-IP": "198.51.100.99"},
                data={"username": "admin", "password": "wrong"},
                follow_redirects=False,
            ).status_code == 401
        assert client.post(
            "/login",
            headers={"X-Real-IP": "198.51.100.99"},
            data={"username": "admin", "password": "right-pass"},
            follow_redirects=False,
        ).status_code == 302
        assert ("198.51.100.99", "admin") not in sys_routes._login_failures


def test_installer_nginx_template_and_ci_hardening():
    import re

    install_sh = (REPO_ROOT / "deploy/install.sh").read_text(encoding="utf-8")
    subprocess.run(["bash", "-n", str(REPO_ROOT / "deploy/install.sh")], check=True)
    assert "Dashboard: admin / $DASH_PASS" not in install_sh
    assert "sed -i" not in install_sh
    assert 'cp "$INSTALL_DIR/deploy/' not in install_sh

    nginx_tpl = (REPO_ROOT / "deploy/nginx.conf.template").read_text(encoding="utf-8")
    assert "listen 127.0.0.1:80;" in nginx_tpl
    assert "COOKIE_SECURE=1" in nginx_tpl

    ci_yml = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in ci_yml
    pins = re.findall(r"uses:\s*astral-sh/setup-uv@([0-9a-f]{40})", ci_yml)
    assert len(pins) == 2
    assert "@v7" not in ci_yml
