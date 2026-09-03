#!/usr/bin/env python3
"""Bounded native-Playwright probes for #234.

The script never prints credentials or response bodies. It talks only to already-running
services and writes one JSON document to the requested artifact path.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[3]
MAIN_ROOT = Path("/mnt/data/Projects/Python/orchestra")
SSH_BASE = [
    "proxychains4", "-q", "ssh",
    "-i", "/home/maxim/.ssh/id_ed25519",
    "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
    "root@158.220.127.161",
]
ORIGINS = {
    "local": "http://127.0.0.1:8888",
    "tunnel": "http://127.0.0.1:18888",
    "public": "https://orc.seedon.ru",
}
INTERLEAVED = [
    "local", "tunnel", "local", "tunnel",
    "public", "tunnel", "public", "tunnel",
    "local", "public", "local", "public",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def remote_credentials() -> dict[str, str]:
    env_result = subprocess.run(
        SSH_BASE + ["systemctl", "show", "orchestra", "-p", "EnvironmentFiles", "--value"],
        capture_output=True, text=True, timeout=12, check=True,
    )
    paths = [line.strip().split(" ", 1)[0] for line in env_result.stdout.splitlines() if line.strip()]
    if not paths:
        raise RuntimeError("remote EnvironmentFiles is empty")
    remote_code = r'''
import json, sys
from pathlib import Path
values = {}
for raw in Path(sys.argv[1]).read_text().splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    values[key.strip()] = value
print(json.dumps({key: values.get(key, "") for key in ("DASHBOARD_USER", "DASHBOARD_PASSWORD")}))
'''
    result = subprocess.run(
        SSH_BASE + ["python3", "-", paths[0]], input=remote_code,
        capture_output=True, text=True, timeout=12, check=True,
    )
    values = json.loads(result.stdout.splitlines()[-1])
    if not values.get("DASHBOARD_USER") or not values.get("DASHBOARD_PASSWORD"):
        raise RuntimeError("remote dashboard credentials are unavailable")
    return values


def proxy_config() -> dict | None:
    values = dotenv_values(MAIN_ROOT / ".env")
    proxy = values.get("HTTPS_PROXY") or values.get("HTTP_PROXY")
    if not proxy:
        return None
    parsed = urlparse(proxy)
    server = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port:
        server += f":{parsed.port}"
    out = {"server": server, "bypass": "127.0.0.1,localhost"}
    if parsed.username:
        out["username"] = parsed.username
    if parsed.password:
        out["password"] = parsed.password
    return out


def setup_page(browser, label: str, credentials: dict[str, str], events: list[dict]):
    context_args = {"ignore_https_errors": True, "service_workers": "allow"}
    if label == "public":
        proxy = proxy_config()
        if proxy:
            context_args["proxy"] = proxy
    context = browser.new_context(**context_args)
    page = context.new_page()
    page.set_default_timeout(20_000)
    t0 = time.perf_counter()

    def record(kind: str, **fields):
        events.append({
            "origin": label,
            "kind": kind,
            "mono_ms": round((time.perf_counter() - t0) * 1000, 3),
            **fields,
        })

    def tracked(url: str) -> bool:
        return any(key in url for key in (
            "/api/usage", "/api/models", "/api/sessions/", "/api/logs/sync",
        ))

    page.on("request", lambda req: tracked(req.url) and record(
        "request", url=req.url, method=req.method, resource_type=req.resource_type,
    ))
    page.on("response", lambda resp: tracked(resp.url) and record(
        "response", url=resp.url, status=resp.status,
        server=resp.headers.get("server", ""),
        content_encoding=resp.headers.get("content-encoding", ""),
        build=resp.headers.get("x-orchestra-build", ""),
    ))
    page.on("requestfailed", lambda req: tracked(req.url) and record(
        "requestfailed", url=req.url, failure=req.failure or "",
    ))
    page.on("console", lambda msg: (
        ("api /api/usage" in msg.text or "Usage fetch failed" in msg.text
         or "quota-map fetch failed" in msg.text or "[store]" in msg.text)
        and record("console", level=msg.type, text=msg.text[:500])
    ))
    page.on("pageerror", lambda error: record("pageerror", text=str(error)[:500]))
    page.add_init_script(r'''
        window.__q234Dom = [];
        addEventListener('DOMContentLoaded', () => {
          const snap = (why) => {
            const net = document.getElementById('net-fail-banner');
            const usage = document.getElementById('usage-bar');
            const quota = document.getElementById('quota-lines');
            window.__q234Dom.push({
              t: performance.now(), why,
              netClass: net ? net.className : null,
              netText: net ? net.textContent.trim().slice(0, 300) : null,
              usageText: usage ? usage.textContent.trim().slice(0, 300) : null,
              quotaText: quota ? quota.textContent.trim().slice(0, 300) : null,
            });
          };
          const observer = new MutationObserver(() => snap('mutation'));
          observer.observe(document.documentElement, {subtree:true, childList:true, attributes:true, characterData:true});
          snap('domcontentloaded');
        });
    ''')

    base = ORIGINS[label]
    if label != "local":
        login = context.request.post(
            base + "/login",
            form={
                "username": credentials["DASHBOARD_USER"],
                "password": credentials["DASHBOARD_PASSWORD"],
            },
            fail_on_status_code=False,
        )
        record("login", status=login.status, redirected=login.url != base + "/login")
    nav_start = time.perf_counter()
    response = page.goto(base + "/", wait_until="domcontentloaded", timeout=20_000)
    record(
        "navigation", status=response.status if response else None,
        elapsed_ms=round((time.perf_counter() - nav_start) * 1000, 3),
    )
    # `networkidle` is intentionally inapplicable: the dashboard owns a persistent SSE.
    page.wait_for_function("typeof window.api === 'function' && typeof window.fetchQuotaLines === 'function'")
    page.wait_for_timeout(750)
    return context, page, record


def browser_state(page) -> dict:
    return page.evaluate(r'''async () => ({
      serviceWorkers: (await navigator.serviceWorker.getRegistrations()).map(r => r.scope),
      cacheKeys: await caches.keys(),
      indexedDB: indexedDB.databases ? await indexedDB.databases() : [],
      localStorageKeys: Object.keys(localStorage),
      localStorageBytes: Object.entries(localStorage).reduce((n, [k,v]) => n + k.length + v.length, 0),
      storeOpen: typeof _storeDb !== 'undefined' && !!_storeDb,
      eventSourceReadyState: typeof eventSource !== 'undefined' && eventSource ? eventSource.readyState : null,
      currentScope: typeof currentScope !== 'undefined' ? currentScope : null,
      selectedAgent: typeof selectedAgent !== 'undefined' ? selectedAgent : null,
      usageText: document.getElementById('usage-bar')?.textContent.trim().slice(0, 500) || '',
      quotaText: document.getElementById('quota-lines')?.textContent.trim().slice(0, 500) || '',
      netText: document.getElementById('net-fail-banner')?.textContent.trim().slice(0, 500) || '',
    })''')


def quota_action(page, label: str, seq: int) -> dict:
    marker = f"q234-{label}-{seq}-{uuid.uuid4().hex[:8]}"
    before = len(page.context.pages)
    started = time.perf_counter()
    load = tuple(round(x, 3) for x in os.getloadavg())
    try:
        outcome = page.evaluate(
            r'''async (url) => {
              try {
                const data = await api(url, {pollKey: 'q234'});
                return {ok:true, backendByte: !!(data && data.generated_at && data.rule)};
              } catch (e) {
                return {ok:false, name:e?.name || '', message:e?.message || ''};
              }
            }''',
            f"/api/usage/quota-map?probe={marker}",
        )
    except PlaywrightError as error:
        outcome = {"ok": False, "name": type(error).__name__, "message": str(error)[:300]}
    elapsed = round((time.perf_counter() - started) * 1000, 3)
    resource = page.evaluate(
        r'''marker => performance.getEntriesByType('resource')
          .filter(e => e.name.includes(marker)).map(e => ({
            name:e.name, initiatorType:e.initiatorType, nextHopProtocol:e.nextHopProtocol,
            startTime:e.startTime, fetchStart:e.fetchStart,
            domainLookupStart:e.domainLookupStart, connectStart:e.connectStart,
            secureConnectionStart:e.secureConnectionStart, connectEnd:e.connectEnd,
            requestStart:e.requestStart, responseStart:e.responseStart,
            responseEnd:e.responseEnd, duration:e.duration,
            transferSize:e.transferSize, encodedBodySize:e.encodedBodySize,
          }))''', marker,
    )
    return {
        "origin": label, "marker": marker, "utc": utc_now(), "loadavg": load,
        "elapsed_ms": elapsed, "outcome": outcome, "resource": resource,
        "page_count_before": before,
        "dom_tail": page.evaluate("window.__q234Dom.slice(-12)"),
        "state": browser_state(page),
    }


def populate_idb_control(page) -> dict:
    return page.evaluate(r'''async () => {
      const db = await _storeOpen();
      if (!db) return {ok:false};
      const payload = 'x'.repeat(2400);
      const start = performance.now();
      await new Promise((resolve, reject) => {
        const tx = db.transaction(['logs', 'meta'], 'readwrite');
        const logs = tx.objectStore('logs');
        for (let i = 0; i < 688; i++) {
          logs.put({id: -234000000 - i, session_id:'q234-stale', type:'text', content:payload, ts:0});
        }
        tx.objectStore('meta').put(Number.MAX_SAFE_INTEGER, 'watermark');
        tx.objectStore('meta').put('q234-mismatch', 'sessions');
        tx.oncomplete = resolve; tx.onerror = () => reject(tx.error); tx.onabort = () => reject(tx.error);
      });
      return {ok:true, rows:688, contentBytes:688*2400, elapsedMs:performance.now()-start};
    }''')


def idb_control(page, label: str, seq: int) -> dict:
    before = quota_action(page, label + "-idb-before", seq)
    populate = populate_idb_control(page)
    started = time.perf_counter()
    # This is the old-state mechanism under test: repair/sync and quota refresh overlap.
    marker = f"q234-{label}-idb-{uuid.uuid4().hex[:8]}"
    result = page.evaluate(
        r'''async (url) => {
          const sync = _storeSync();
          let quota;
          try {
            const data = await api(url, {pollKey:'q234-idb'});
            quota = {ok:true, backendByte:!!(data && data.generated_at && data.rule)};
          } catch (e) {
            quota = {ok:false, name:e?.name || '', message:e?.message || ''};
          }
          let syncResult;
          try { syncResult = await sync; } catch (e) { syncResult = `${e?.name}: ${e?.message}`; }
          return {quota, syncResult};
        }''',
        f"/api/usage/quota-map?probe={marker}",
    )
    return {
        "before": before, "populate": populate, "marker": marker,
        "overlap_elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "overlap_result": result, "state_after": browser_state(page),
    }


def sse_saturation_control(page, label: str) -> dict:
    marker = f"q234-{label}-sixslots-{uuid.uuid4().hex[:8]}"
    started = time.perf_counter()
    result = page.evaluate(
        r'''async (url) => {
          if (!eventSource && selectedAgent && currentScope) connectSSE();
          const base = eventSource?.url;
          if (!base) return {ok:false, reason:'no valid SSE URL'};
          const extras = Array.from({length:5}, () => new EventSource(base + (base.includes('?') ? '&' : '?') + 'q234slot=' + Math.random()));
          const opened = await Promise.all(extras.map(es => new Promise(resolve => {
            const timer = setTimeout(() => resolve(false), 4000);
            es.onopen = () => { clearTimeout(timer); resolve(true); };
            es.onerror = () => { clearTimeout(timer); resolve(false); };
          })));
          let quota;
          try {
            const data = await api(url, {pollKey:'q234-sixslots'});
            quota = {ok:true, backendByte:!!(data && data.generated_at && data.rule)};
          } catch (e) {
            quota = {ok:false, name:e?.name || '', message:e?.message || ''};
          } finally {
            extras.forEach(es => es.close());
          }
          return {ok:true, base, opened, quota};
        }''',
        f"/api/usage/quota-map?probe={marker}",
    )
    return {
        "marker": marker, "loadavg": tuple(round(x, 3) for x in os.getloadavg()),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "result": result,
        "resource": page.evaluate(
            "marker => performance.getEntriesByType('resource').filter(e => e.name.includes(marker)).map(e => ({startTime:e.startTime,fetchStart:e.fetchStart,requestStart:e.requestStart,responseStart:e.responseStart,responseEnd:e.responseEnd,duration:e.duration,nextHopProtocol:e.nextHopProtocol,transferSize:e.transferSize}))",
            marker,
        ),
    }


def render_fault_controls(page) -> dict:
    results = {}

    # Quota-map-only failure: usage must remain visible; only lane status may degrade.
    def abort_quota(route):
        if urlparse(route.request.url).path == "/api/usage/quota-map":
            route.abort("connectionfailed")
        else:
            route.continue_()

    page.route("**/api/usage/quota-map*", abort_quota)
    page.evaluate("_usageData=null; _usageError=false; _quotaMapData=null; localStorage.removeItem('orchestra_snapshot:usage')")
    started = time.perf_counter()
    page.evaluate("fetchUsage()")
    results["quota_map_only"] = {
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "state": browser_state(page),
    }
    page.unroute("**/api/usage/quota-map*", abort_quota)

    # Usage-only failure: this is the branch that owns the exact `Usage unavailable` text.
    def abort_usage(route):
        if urlparse(route.request.url).path == "/api/usage":
            route.abort("connectionfailed")
        else:
            route.continue_()

    page.route("**/api/usage*", abort_usage)
    page.evaluate("_usageData=null; _usageError=false; _quotaMapData=null; localStorage.removeItem('orchestra_snapshot:usage')")
    started = time.perf_counter()
    page.evaluate("fetchUsage()")
    results["usage_only"] = {
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "state": browser_state(page),
    }
    page.unroute("**/api/usage*", abort_usage)
    return results


def auth_classification_control(page) -> dict:
    marker = f"q234-auth-{uuid.uuid4().hex[:8]}"
    attempts = []

    def unauthorized(route):
        attempts.append(time.perf_counter())
        route.fulfill(status=401, content_type="application/json", body='{"detail":"Not authenticated"}')

    page.route(f"**/*{marker}*", unauthorized)
    page.evaluate("document.getElementById('net-fail-banner')?.classList.add('hidden')")
    result = page.evaluate(
        r'''async url => { try { await api(url); return {ok:true}; }
        catch(e) { return {ok:false, name:e?.name || '', message:e?.message || ''}; } }''',
        f"/api/usage/quota-map?probe={marker}",
    )
    page.unroute(f"**/*{marker}*", unauthorized)
    return {
        "attempts": len(attempts), "result": result,
        "net_hidden": page.locator("#net-fail-banner").evaluate("e => e.classList.contains('hidden')"),
    }


def latency_timeout_control(page) -> dict:
    session = page.context.new_cdp_session(page)
    session.send("Network.enable")
    try:
        session.send("Network.emulateNetworkConditions", {
            "offline": False,
            "latency": 2500,
            "downloadThroughput": -1,
            "uploadThroughput": -1,
        })
        return quota_action(page, "local-cdp2500", 1)
    finally:
        session.send("Network.emulateNetworkConditions", {
            "offline": False,
            "latency": 0,
            "downloadThroughput": -1,
            "uploadThroughput": -1,
        })
        session.detach()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--mode", choices=("baseline", "controls"), required=True)
    args = parser.parse_args()

    credentials = remote_credentials()
    artifact = {
        "schema": 1, "mode": args.mode, "started_at": utc_now(),
        "interleaved_order": INTERLEAVED if args.mode == "baseline" else None,
        "events": [], "runs": [], "controls": {},
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        pages = {}
        contexts = {}
        try:
            labels = ("local", "tunnel", "public") if args.mode == "baseline" else ("local", "tunnel")
            for label in labels:
                try:
                    context, page, _ = setup_page(browser, label, credentials, artifact["events"])
                    contexts[label] = context
                    pages[label] = page
                    artifact["runs"].append({"setup": label, "state": browser_state(page)})
                except Exception as error:
                    artifact["runs"].append({"setup": label, "error": f"{type(error).__name__}: {error}"})
            if args.mode == "baseline":
                for seq, label in enumerate(INTERLEAVED, 1):
                    if label in pages:
                        artifact["runs"].append(quota_action(pages[label], label, seq))
            else:
                if "local" in pages:
                    artifact["controls"]["idb"] = idb_control(pages["local"], "local", 1)
                    artifact["controls"]["render_faults"] = render_fault_controls(pages["local"])
                    artifact["controls"]["auth_classification"] = auth_classification_control(pages["local"])
                    artifact["controls"]["cdp_2500ms"] = latency_timeout_control(pages["local"])
                    artifact["controls"]["six_slots_local"] = sse_saturation_control(pages["local"], "local")
                if "tunnel" in pages:
                    artifact["controls"]["six_slots_tunnel"] = sse_saturation_control(pages["tunnel"], "tunnel")
        finally:
            for context in contexts.values():
                context.close()
            browser.close()
    artifact["finished_at"] = utc_now()
    Path(args.output).write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "output": args.output, "mode": args.mode,
        "run_records": len(artifact["runs"]), "event_records": len(artifact["events"]),
        "controls": sorted(artifact["controls"]),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
