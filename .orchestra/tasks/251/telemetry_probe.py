#!/usr/bin/env python3
"""Positive/negative wire oracle for Grok 1.0.3 telemetry configuration.

Runs two identical low-effort subscription calls. The positive arm deliberately points product
analytics and external OTEL at a local collector. The negative arm passes the same hostile
endpoints through the production GrokBackend._build_env(). Bodies and credentials are never
printed or persisted.
"""

from __future__ import annotations

import collections
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from app.backend_grok import GrokBackend  # noqa: E402 - pin this worktree before import


PORT = 18767


def main() -> None:
    hits: list[tuple[str, str]] = []

    class Collector(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
            length = int(self.headers.get("content-length", "0"))
            self.rfile.read(length)
            hits.append((self.command, self.path))
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *_args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Collector)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    command = [
        "grok", "--model", "grok-4.5", "--reasoning-effort", "low",
        "--no-memory", "--no-plan", "--always-approve", "--disable-web-search",
        "--output-format", "json", "--cwd", str(ROOT / "data/bench-251"),
        "-p", "Reply with exactly OK.",
    ]
    common = os.environ.copy()
    for name in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy",
                 "ALL_PROXY", "all_proxy"):
        common.pop(name, None)
    common.update({
        "GROK_HOME": str(ROOT / "data/grok-home"),
        "GROK_TELEMETRY_ENABLED": "1",
        "GROK_TELEMETRY_EVENTS_URL": f"http://127.0.0.1:{PORT}/events",
        "GROK_TELEMETRY_EVENTS_API_KEY": "positive-control",
        "GROK_EXTERNAL_OTEL": "1",
        "OTEL_LOGS_EXPORTER": "otlp",
        "OTEL_METRICS_EXPORTER": "otlp",
        "OTEL_TRACES_EXPORTER": "otlp",
        "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://127.0.0.1:{PORT}",
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
    })
    positive = subprocess.run(
        command, env=common, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=120, check=False,
    )
    time.sleep(6)
    positive_hits = collections.Counter(path for _, path in hits)
    hits.clear()

    backend = GrokBackend(
        model="grok-4.5", cwd=str(ROOT / "data/bench-251"), mcp_servers=[],
        mcp_env={
            **common,
            "GROK_TELEMETRY_EVENTS_API_KEY": "hostile-value",
            "SENTRY_DSN": f"http://127.0.0.1:{PORT}/sentry",
        },
    )
    production = subprocess.run(
        command, env=backend._build_env(), stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, timeout=120, check=False,
    )
    time.sleep(6)
    production_hits = collections.Counter(path for _, path in hits)
    server.shutdown()

    print(json.dumps({
        "positive_rc": positive.returncode,
        "positive_post_paths": dict(sorted(positive_hits.items())),
        "production_rc": production.returncode,
        "production_post_paths": dict(sorted(production_hits.items())),
        "production_switches": {
            key: backend._build_env().get(key)
            for key in (
                "GROK_TELEMETRY_ENABLED", "GROK_EXTERNAL_OTEL",
                "OTEL_LOGS_EXPORTER", "OTEL_METRICS_EXPORTER",
                "OTEL_TRACES_EXPORTER", "SENTRY_DSN",
            )
        },
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
