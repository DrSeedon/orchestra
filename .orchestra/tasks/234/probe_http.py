#!/usr/bin/env python3
"""Interleaved direct HTTP + event-loop controls for #234."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from probe_quota_map import INTERLEAVED, ORIGINS, proxy_config, remote_credentials


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def client_for(label: str) -> httpx.Client:
    kwargs = {"verify": False, "timeout": 12.0, "follow_redirects": False, "trust_env": False}
    if label == "public":
        proxy = proxy_config()
        if proxy:
            kwargs["proxy"] = proxy["server"]
            if proxy.get("username"):
                user = proxy["username"]
                password = proxy.get("password", "")
                parsed = httpx.URL(proxy["server"])
                kwargs["proxy"] = str(parsed.copy_with(username=user, password=password))
    return httpx.Client(**kwargs)


def login(client: httpx.Client, label: str, credentials: dict[str, str]) -> dict:
    if label == "local":
        return {"status": None, "cookie": False}
    response = client.post(ORIGINS[label] + "/login", data={
        "username": credentials["DASHBOARD_USER"],
        "password": credentials["DASHBOARD_PASSWORD"],
    })
    return {"status": response.status_code, "cookie": "session" in client.cookies}


def get_quota(client: httpx.Client, label: str, marker: str) -> dict:
    started = time.perf_counter()
    try:
        response = client.get(ORIGINS[label] + f"/api/usage/quota-map?probe={marker}")
        elapsed = (time.perf_counter() - started) * 1000
        try:
            data = response.json()
        except Exception:
            data = {}
        return {
            "status": response.status_code, "http_version": response.http_version,
            "elapsed_ms": round(elapsed, 3), "bytes": len(response.content),
            "backend_byte": bool(data.get("generated_at") and data.get("rule")),
            "server": response.headers.get("server", ""),
            "content_encoding": response.headers.get("content-encoding", ""),
            "cache_control": response.headers.get("cache-control", ""),
        }
    except Exception as error:
        return {"error": f"{type(error).__name__}: {error}", "elapsed_ms": round((time.perf_counter() - started) * 1000, 3)}


def head_control(client: httpx.Client, label: str) -> dict:
    started = time.perf_counter()
    try:
        response = client.head(ORIGINS[label] + "/api/models")
        return {
            "status": response.status_code,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "backend_byte": bool(response.headers.get("x-orchestra-build")),
            "build": response.headers.get("x-orchestra-build", ""),
        }
    except Exception as error:
        return {"error": f"{type(error).__name__}: {error}", "elapsed_ms": round((time.perf_counter() - started) * 1000, 3)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    credentials = remote_credentials()
    clients = {label: client_for(label) for label in ORIGINS}
    artifact = {"schema": 1, "started_at": utc_now(), "order": INTERLEAVED, "login": {}, "runs": []}
    try:
        for label, client in clients.items():
            artifact["login"][label] = login(client, label, credentials)
        for seq, label in enumerate(INTERLEAVED, 1):
            marker = f"q234-http-{label}-{seq}-{uuid.uuid4().hex[:8]}"
            load = tuple(round(x, 3) for x in os.getloadavg())
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                quota_future = pool.submit(get_quota, clients[label], label, marker)
                time.sleep(0.05)
                # A separate connection is required: a shared HTTP/1.1 connection would
                # serialize in the client and confound browser/server scheduling.
                control_client = client_for(label)
                if label != "local":
                    login(control_client, label, credentials)
                control_future = pool.submit(head_control, control_client, label)
                quota = quota_future.result()
                control = control_future.result()
                control_client.close()
            record = {
                "seq": seq, "origin": label, "marker": marker, "utc": utc_now(),
                "loadavg": load, "quota": quota, "head_control": control,
            }
            artifact["runs"].append(record)
            print(json.dumps(record, ensure_ascii=False), flush=True)
    finally:
        for client in clients.values():
            client.close()
    artifact["finished_at"] = utc_now()
    Path(args.output).write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
