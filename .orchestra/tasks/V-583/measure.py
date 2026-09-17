"""V-583: network capture of the Orchestra dashboard via CDP.

modes:
  switch   — load the page, then switch agent chats A→B→C→B, phase-tagged
  idle     — page parked on a quiet agent, record N seconds with zero interaction
  active   — page parked on the named agent (a running one), record N seconds

Numbers come from Chrome DevTools Protocol Network events (encodedDataLength),
not from reading the application code.
"""

import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8888"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    mode = sys.argv[1]
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
    park_agent = sys.argv[3] if len(sys.argv) > 3 else None
    tag = sys.argv[4] if len(sys.argv) > 4 else mode

    user = os.environ["DASHBOARD_USER"]
    password = os.environ["DASHBOARD_PASSWORD"]

    events = []
    state = {"phase": "boot"}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        page = context.new_page()
        cdp = context.new_cdp_session(page)

        req = {}

        def on_send(params):
            req[params["requestId"]] = {
                "method": params["request"]["method"],
                "url": params["request"]["url"],
                "start": params["timestamp"],
                "phase": state["phase"],
                "type": params.get("type", ""),
            }

        def on_response(params):
            r = req.setdefault(params["requestId"], {})
            resp = params["response"]
            r["status"] = resp.get("status")
            r["mime"] = resp.get("mimeType")
            r["from_disk_cache"] = resp.get("fromDiskCache", False)
            r["response_at"] = params["timestamp"]
            r["headers_bytes"] = resp.get("encodedDataLength", 0)
            if not r.get("url"):
                r["url"] = resp.get("url")
                r["phase"] = state["phase"]

        def on_data(params):
            r = req.setdefault(params["requestId"], {})
            r.setdefault("chunks", []).append(
                (params["timestamp"], params["encodedDataLength"], params["dataLength"])
            )

        def on_finished(params):
            r = req.setdefault(params["requestId"], {})
            r["finish"] = params["timestamp"]
            r["encoded_total"] = params.get("encodedDataLength", 0)

        def on_failed(params):
            r = req.setdefault(params["requestId"], {})
            r["failed"] = params.get("errorText", "")
            r["canceled"] = params.get("canceled", False)
            r["finish"] = params["timestamp"]

        def on_from_cache(params):
            r = req.setdefault(params["requestId"], {})
            r["served_from_memory_cache"] = True

        cdp.send("Network.enable", {"maxTotalBufferSize": 100_000_000})
        cdp.on("Network.requestWillBeSent", on_send)
        cdp.on("Network.responseReceived", on_response)
        cdp.on("Network.dataReceived", on_data)
        cdp.on("Network.loadingFinished", on_finished)
        cdp.on("Network.loadingFailed", on_failed)
        cdp.on("Network.requestServedFromCache", on_from_cache)

        def mark(phase):
            state["phase"] = phase
            events.append({"phase": phase, "wall": time.time(), "note": "phase-start"})

        # ── login ──
        mark("login")
        page.goto(f"{BASE}/login", wait_until="load")
        page.fill('input[name="username"]', user)
        page.fill('input[name="password"]', password)
        page.click('button[type="submit"]')
        page.wait_for_load_state("load")
        page.wait_for_timeout(6000)

        if mode == "switch":
            # baseline: full first paint of the app is already inside "login" phase
            names = page.eval_on_selector_all(
                ".agent-item",
                "els => els.map(e => e.querySelector('.text-xs.font-medium')?.textContent || '')",
            )
            events.append({"note": "agent-list", "names": names, "wall": time.time()})
            picker = page.eval_on_selector_all(
                "#orch-picker option", "els => els.map(e => e.value + '|' + e.textContent)"
            )
            events.append({"note": "orch-picker", "options": picker, "wall": time.time()})

            order = [n for n in names if n]
            if len(order) < 3:
                print("NOT ENOUGH AGENTS", order)
            plan = [order[1], order[2], order[1], order[0]] if len(order) >= 3 else order
            for i, name in enumerate(plan):
                mark(f"switch{i+1}:{name}")
                page.click(f'.agent-item:has(.text-xs.font-medium:text-is("{name}"))')
                page.wait_for_timeout(8000)
            mark("post-switch-quiet")
            page.wait_for_timeout(5000)
        elif mode == "orchswitch":
            tabs = page.eval_on_selector_all(
                "#orch-tabs .orch-tab", "els => els.map(e => e.dataset.orchName)"
            )
            events.append({"note": "orch-tabs", "tabs": tabs, "wall": time.time()})
            # A(current) → B → C → B(return) → A(return)
            plan = [tabs[1], tabs[2], tabs[1], tabs[0]]
            for i, name in enumerate(plan):
                mark(f"orch{i+1}:{name}")
                page.click(f'#orch-tabs .orch-tab[data-orch-name="{name}"]')
                page.wait_for_timeout(9000)
            mark("post-orch-quiet")
            page.wait_for_timeout(5000)
        elif mode == "record2":
            quiet, active = park_agent.split(",")
            page.click(f'.agent-item:has(.text-xs.font-medium:text-is("{quiet}"))')
            page.wait_for_timeout(4000)
            mark(f"idle:{quiet}")
            page.wait_for_timeout(int(seconds * 1000))
            mark("switch-to-active")
            page.click(f'.agent-item:has(.text-xs.font-medium:text-is("{active}"))')
            page.wait_for_timeout(4000)
            mark(f"active:{active}")
            page.wait_for_timeout(int(seconds * 1000))
            mark("record-end")
            page.wait_for_timeout(500)
        else:
            if park_agent:
                page.click(
                    f'.agent-item:has(.text-xs.font-medium:text-is("{park_agent}"))'
                )
                page.wait_for_timeout(5000)
            mark(f"record:{mode}")
            t0 = time.time()
            while time.time() - t0 < seconds:
                page.wait_for_timeout(1000)
            mark("record-end")
            page.wait_for_timeout(500)

        browser.close()

    out = {
        "mode": mode,
        "tag": tag,
        "seconds": seconds,
        "park_agent": park_agent,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "events": events,
        "requests": [dict(v, request_id=k) for k, v in req.items()],
    }
    path = os.path.join(OUT_DIR, f"raw-{tag}.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=1)
    print("WROTE", path, "requests:", len(req))


if __name__ == "__main__":
    main()
