#!/usr/bin/env python3
"""Scratch A/B/A/B for an app-side GET admission queue; no production edits."""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

from probe_quota_map import browser_state, setup_page


HERE = Path(__file__).resolve().parent
ORDER = ["current", "queue4", "current", "queue4"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


QUEUE_JS = r'''
(() => {
  const original = api;
  let active = 0;
  const waiters = [];
  window.__q234Queue = {maxActive:0, waited:0, admitted:0};
  const enter = () => new Promise(resolve => {
    if (active < 4) { active++; resolve(); return; }
    window.__q234Queue.waited++;
    waiters.push(() => { active++; resolve(); });
  });
  const leave = () => {
    active--;
    const next = waiters.shift();
    if (next) next();
  };
  api = async (...args) => {
    await enter();
    window.__q234Queue.admitted++;
    window.__q234Queue.maxActive = Math.max(window.__q234Queue.maxActive, active);
    try { return await original(...args); }
    finally { leave(); }
  };
})();
'''


def one_run(playwright, arm: str, seq: int) -> dict:
    browser = playwright.chromium.launch(headless=True)
    events = []
    context = page = None
    try:
        context, page, _ = setup_page(browser, "local", {}, events)
        try:
            page.wait_for_function("typeof eventSource !== 'undefined' && eventSource && eventSource.readyState === 1", timeout=10_000)
        except Exception:
            pass
        if arm == "queue4":
            page.evaluate(QUEUE_JS)
        prefix = f"q234-storm-{arm}-{seq}-{uuid.uuid4().hex[:8]}"
        session = context.new_cdp_session(page)
        session.send("Network.enable")
        session.send("Network.emulateNetworkConditions", {
            "offline": False, "latency": 800,
            "downloadThroughput": -1, "uploadThroughput": -1,
        })
        started = time.perf_counter()
        try:
            outcomes = page.evaluate(
                r'''async prefix => {
                  performance.clearResourceTimings();
                  const calls = [];
                  for (let i=0; i<10; i++) calls.push({kind:'models', url:`/api/models?probe=${prefix}-m${i}`});
                  calls.push({kind:'quota', url:`/api/usage/quota-map?probe=${prefix}-quota`});
                  return Promise.all(calls.map(async call => {
                    try {
                      const data = await api(call.url, {pollKey:'q234-storm'});
                      const backendByte = call.kind === 'models'
                        ? !!(data && Array.isArray(data.models))
                        : !!(data && data.generated_at && data.rule);
                      return {...call, ok:true, backendByte};
                    } catch (e) {
                      return {...call, ok:false, name:e?.name || '', message:e?.message || ''};
                    }
                  }));
                }''', prefix,
            )
        finally:
            session.send("Network.emulateNetworkConditions", {
                "offline": False, "latency": 0,
                "downloadThroughput": -1, "uploadThroughput": -1,
            })
            session.detach()
        resources = page.evaluate(
            r'''prefix => performance.getEntriesByType('resource')
              .filter(e => e.name.includes(prefix)).map(e => ({
                name:e.name, startTime:e.startTime, fetchStart:e.fetchStart,
                requestStart:e.requestStart, responseStart:e.responseStart,
                responseEnd:e.responseEnd, duration:e.duration,
                nextHopProtocol:e.nextHopProtocol, transferSize:e.transferSize,
              }))''', prefix,
        )
        marker_events = [event for event in events if prefix in event.get("url", "")]
        return {
            "seq": seq, "arm": arm, "prefix": prefix, "utc": utc_now(),
            "loadavg": [round(x, 3) for x in os.getloadavg()],
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "outcomes": outcomes, "resources": resources, "events": marker_events,
            "queue": page.evaluate("window.__q234Queue || null"),
            "state": browser_state(page),
        }
    finally:
        if context:
            context.close()
        browser.close()


def main() -> None:
    output = {"schema": 1, "started_at": utc_now(), "order": ORDER, "runs": []}
    with sync_playwright() as playwright:
        for seq, arm in enumerate(ORDER, 1):
            record = one_run(playwright, arm, seq)
            output["runs"].append(record)
            print(json.dumps({
                "seq": seq, "arm": arm, "loadavg": record["loadavg"],
                "elapsed_ms": record["elapsed_ms"],
                "ok": sum(item["ok"] for item in record["outcomes"]),
                "failed": sum(not item["ok"] for item in record["outcomes"]),
                "attempt_resources": len(record["resources"]),
                "queue": record["queue"],
            }, ensure_ascii=False), flush=True)
    output["finished_at"] = utc_now()
    (HERE / "queue-candidate.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
