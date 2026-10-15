#!/usr/bin/env python3
"""Скриншоты ключевых экранов дашборда до/после дизайн-системы (V-876).

Поднимает изолированный сервер на временной БД с набором оркестраторов и воркеров
разных моделей, подменяет статусы в ответах /api/sessions и /api/orchestrators
(живых рантаймов в стенде нет, а статусы нужны все) и снимает экраны.

    uv run --frozen python .orchestra/tasks/V-876/shots.py --out .orchestra/tasks/V-876/before
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

USER, PASSWORD = "auditor", "audit-pass"
SCOPE = str(ROOT)
SCOPE2 = str(ROOT / "app")
SCOPE3 = str(ROOT / "docs")

ORCHS = [
    ("orchestra", SCOPE, "claude-opus-5-5[1m]", "running"),
    ("game-master", SCOPE2, "gpt-6-luna", "waiting"),
    ("docs-pm", SCOPE3, "claude-sonnet-5-5[1m]", "idle"),
]
WORKERS = [
    ("design-system", "claude-opus-5-5[1m]", "running", 72),
    ("fix-dashboard", "claude-sonnet-5-5[1m]", "waiting", 41),
    ("haiku-collector", "claude-haiku-5-5", "idle", 12),
    ("feat-voice", "gpt-6-luna", "running", 33),
    ("sol-review", "gpt-6.1-sol", "idle", 85),
    ("astra-plan", "gpt-6-astra", "broken", 0),
    ("spark-leaf", "gpt-5.3-codex-spark", "idle", 0),
    ("grok-probe", "grok-4.6", "idle", 5),
]
STATUS = {name: status for name, _, status, _ in WORKERS}
STATUS.update({name: status for name, _, _, status in ORCHS})


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def seed_db(db_path: Path) -> None:
    from app import db as dbmod
    from app import checklists
    from app.db import init_db, save_session

    previous = dbmod.DB_PATH
    dbmod.DB_PATH = db_path
    try:
        init_db()
        now = datetime.now(timezone.utc).isoformat()
        for name, scope, model, _ in ORCHS:
            save_session({
                "id": name, "name": name, "scope": scope, "cwd": scope, "model": model,
                "system_prompt": "", "status": "idle", "session_id": None, "cost_usd": 3.4,
                "worktree_path": None, "branch": None, "is_orchestrator": True, "color": "",
                "created_at": now, "finished_at": None, "role": "orchestrator",
                "context_pct": 52,
            })
        palette = ["#818cf8", "#34d399", "#f97316", "#38bdf8", "#f472b6", "#a78bfa", "#fbbf24", "#2dd4bf"]
        for i, (name, model, _, pct) in enumerate(WORKERS):
            save_session({
                "id": name, "name": name, "scope": SCOPE, "cwd": SCOPE, "model": model,
                "system_prompt": "", "status": "idle", "session_id": None,
                "cost_usd": round(0.37 * (i + 1), 2), "worktree_path": None,
                "branch": f"task-V-876/{name}", "is_orchestrator": False,
                "color": palette[i], "created_at": now, "finished_at": None, "role": "worker",
                "parent_id": "orchestra", "parent_name": "orchestra", "task_id": f"V-87{i}",
                "description": "lifecycle=persistent | экранный стенд V-876", "context_pct": pct,
            })
            if i < 4:
                checklists.save_checklist(
                    name, f"V-87{i}", "t", items=["Аудит", "Токены", "Применение", "Скриншоты"],
                    completed=list(range(i % 4)), current=i % 4,
                )
    finally:
        dbmod.DB_PATH = previous


def start_server(db_path: Path):
    env = os.environ.copy()
    env.update({"ORCHESTRA_DB_PATH": str(db_path), "DASHBOARD_USER": USER,
                "DASHBOARD_PASSWORD": PASSWORD, "OWNER_MODE": "1", "SSH_TUNNELS": ""})
    port = free_port()
    log = open(db_path.parent / "server.log", "wb")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    origin = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError((db_path.parent / "server.log").read_text()[-3000:])
        try:
            with urllib.request.urlopen(origin, timeout=1) as r:
                if r.status == 200:
                    return proc, origin
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.2)
    proc.kill()
    raise RuntimeError("server did not start")


def patch_sessions(route):
    response = route.fetch()
    try:
        data = response.json()
    except Exception:
        return route.fulfill(response=response)

    def fix(row):
        if isinstance(row, dict) and row.get("name") in STATUS:
            row["status"] = STATUS[row["name"]]
            if row.get("is_orchestrator"):
                row["any_running"] = row["status"] == "running"
                row["any_waiting"] = row["status"] == "waiting"
        return row

    if isinstance(data, list):
        data = [fix(r) for r in data]
    elif isinstance(data, dict):
        fix(data)
        fix(data.get("session"))
        for child in data.get("children") or []:
            fix(child)
    route.fulfill(status=200, content_type="application/json", body=json.dumps(data),
                  headers={k: v for k, v in response.headers.items() if k.lower() not in {"content-length", "etag", "content-encoding"}})


def shoot(origin: str, out: Path) -> None:
    from playwright.sync_api import sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for label, viewport, mobile in (("desktop", {"width": 1440, "height": 900}, False),
                                        ("phone", {"width": 390, "height": 844}, True)):
            ctx = browser.new_context(viewport=viewport, is_mobile=mobile, has_touch=mobile,
                                      device_scale_factor=2 if mobile else 1)
            ctx.add_init_script("window.__ORCH_LANG__ = 'ru';")
            page = ctx.new_page()
            page.route("**/api/sessions*", patch_sessions)
            page.route("**/api/sessions/*/info-panel*", patch_sessions)
            page.route("**/api/orchestrators", patch_sessions)
            page.goto(f"{origin}/login")
            page.fill('input[name="username"]', USER)
            page.fill('input[name="password"]', PASSWORD)
            page.click('button[type="submit"]')
            page.wait_for_selector("#agent-list", timeout=30000)
            page.wait_for_timeout(2500)
            page.evaluate("() => { if (window.Connection) Connection.set('online', {}); }")
            # Выбрать главный оркестратор, затем воркера — чтобы панель «Инфо» была заполнена.
            tab = page.locator("#orch-tabs >> text=orchestra").first
            if tab.count():
                tab.click()
                page.wait_for_timeout(1500)
            page.screenshot(path=str(out / f"{label}-main.png"))
            if not mobile:
                page.evaluate("() => switchLeftTab('info')")
                page.wait_for_timeout(1200)
                page.screenshot(path=str(out / f"{label}-info.png"))
                page.locator("#agent-list .agent-item", has_text="design-system").first.click()
                page.wait_for_timeout(1200)
                page.screenshot(path=str(out / f"{label}-worker.png"))
                page.locator("#agent-list").screenshot(path=str(out / f"{label}-agent-list.png"))
                page.locator("#orch-tabs").screenshot(path=str(out / f"{label}-orch-tabs.png"))
                if page.locator("#usage-bar").is_visible():
                    page.locator("#usage-bar").screenshot(path=str(out / f"{label}-usage.png"))
                page.click("#analytics-btn")
                page.wait_for_timeout(2000)
                page.screenshot(path=str(out / f"{label}-analytics.png"))
            else:
                btn = page.locator("#mobile-info-open")
                if btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(1200)
                    page.screenshot(path=str(out / f"{label}-info.png"))
            ctx.close()
        browser.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(dir=str(ROOT / ".orchestra/tasks/V-876")) as tmp:
        db_path = Path(tmp) / "shots.db"
        seed_db(db_path)
        proc, origin = start_server(db_path)
        try:
            shoot(origin, Path(args.out))
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    main()
