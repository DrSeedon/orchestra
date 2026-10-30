#!/usr/bin/env python3
"""Redeem one existing Codex reset bonus under Orchestra's approved policy.

Standalone stdlib script; importing it never starts Codex. No retry is made after
an uncertain consume response. A later cron run reuses orchestra-<creditid>.
"""

from __future__ import annotations

import json
import math
import os
import selectors
import subprocess
import time
from typing import Any, Callable

WEEK_MINUTES = 7 * 24 * 60
EXPIRY_SECONDS = 9 * 60
CONSUME_METHOD = "account/rateLimitResetCredit/consume"


class ResetError(Exception):
    """An operational failure whose message contains no account payload."""


def number(value: Any, field: str) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value)):
        raise ResetError(f"invalid {field}")
    return value


def week(result: dict) -> tuple[float, float]:
    """Find the actual weekly window; a five-hour slot is never a fallback."""
    limits = result.get("rateLimits")
    if not isinstance(limits, dict):
        raise ResetError("missing weekly rate limits")
    windows = [limits.get(slot) for slot in ("primary", "secondary")]
    weekly = [w for w in windows if isinstance(w, dict)
              and w.get("windowDurationMins") == WEEK_MINUTES]
    if len(weekly) != 1:
        raise ResetError("missing or ambiguous weekly window (10080 minutes)")
    used = number(weekly[0].get("usedPercent"), "weekly usedPercent")
    resets = number(weekly[0].get("resetsAt"), "weekly resetsAt")
    if used < 0 or resets < 0:
        raise ResetError("invalid weekly window values")
    return used, resets


def available_credits(result: dict) -> list[dict]:
    reset_credits = result.get("rateLimitResetCredits")
    if not isinstance(reset_credits, dict):
        raise ResetError("missing reset credits")
    credits = reset_credits.get("credits")
    if not isinstance(credits, list):
        raise ResetError("missing reset credit list")
    available = []
    for credit in credits:
        if not isinstance(credit, dict):
            raise ResetError("invalid reset credit")
        if credit.get("status") != "available":
            continue
        if not isinstance(credit.get("id"), str) or not credit["id"]:
            raise ResetError("invalid available credit id")
        number(credit.get("expiresAt"), "available credit expiresAt")
        available.append(credit)
    return sorted(available, key=lambda c: c["expiresAt"])


def reset(rpc: Any, *, now: Callable = time.time, emit: Callable = print) -> None:
    rpc.request("initialize", {"clientInfo": {"name": "orchestra", "title": "Orchestra", "version": "1"}})
    rpc.notify("initialized", {})
    before = rpc.request("account/rateLimits/read", {})
    available = available_credits(before)
    emit(f"available {[(c['id'][-8:], c['expiresAt']) for c in available]}")
    # Accounts without an available bonus do not need a weekly window at all.
    if not available:
        emit("no action: no available reset credits")
        return
    used, resets = week(before)
    emit(f"week_before {used} {resets}")
    credit = available[0]
    if not (used >= 95 or credit["expiresAt"] - now() < EXPIRY_SECONDS):
        emit("no action")
        return
    redeemed = rpc.request(CONSUME_METHOD, {
        "creditId": credit["id"],
        "idempotencyKey": f"orchestra-{credit['id']}",
    })
    if redeemed.get("outcome") != "reset":
        raise ResetError("consume outcome was not reset")
    emit("REDEEMED")
    after = rpc.request("account/rateLimits/read", {})
    used_after, resets_after = week(after)
    emit(f"week_after {used_after} {resets_after}")


class AppServer:
    """Small line-delimited JSON-RPC client with a bounded response wait."""

    def __init__(self, process: Any, *, timeout: float = 30):
        self.process = process
        self.timeout = timeout
        self.next_id = 0
        self.buffer = b""
        self.selector = selectors.DefaultSelector()
        try:
            self.selector.register(process.stdout, selectors.EVENT_READ)
        except BaseException:
            self.selector.close()
            raise

    def send(self, message: dict) -> None:
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def notify(self, method: str, params: dict) -> None:
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: dict) -> dict:
        self.next_id += 1
        request_id = self.next_id
        self.send({"jsonrpc": "2.0", "id": request_id,
                   "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ResetError(f"{method}: response timed out")
            if b"\n" not in self.buffer:
                if not self.selector.select(remaining):
                    raise ResetError(f"{method}: response timed out")
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise ResetError(f"{method}: unexpected app-server EOF")
                self.buffer += chunk
                continue
            raw, self.buffer = self.buffer.split(b"\n", 1)
            try:
                message = json.loads(raw)
            except (ValueError, UnicodeError):
                raise ResetError(f"{method}: invalid JSON response") from None
            if not isinstance(message, dict):
                raise ResetError(f"{method}: invalid RPC response")
            if message.get("id") != request_id:
                continue
            if "error" in message:
                # Provider errors may contain account details: do not echo them.
                raise ResetError(f"{method}: RPC error")
            result = message.get("result")
            if not isinstance(result, dict):
                raise ResetError(f"{method}: invalid RPC result")
            return result

    def close(self) -> None:
        self.selector.close()


def cleanup(process: Any) -> None:
    """Kill and reap the exact child, then close both pipes even on errors."""
    try:
        if process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        process.wait(timeout=5)
    finally:
        try:
            if process.stdin is not None:
                process.stdin.close()
        finally:
            if process.stdout is not None:
                process.stdout.close()


def main() -> int:
    process = None
    rpc = None
    failed = False
    try:
        process = subprocess.Popen(
            ["codex", "app-server"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, cwd="/tmp",
        )
        rpc = AppServer(process)
        reset(rpc)
    except Exception as exc:
        detail = str(exc) if isinstance(exc, ResetError) else type(exc).__name__
        print(f"REDEEM_FAILED {detail}")
        failed = True
    finally:
        if rpc is not None:
            try:
                rpc.close()
            except Exception as exc:
                print(f"REDEEM_FAILED RPC cleanup: {type(exc).__name__}")
                failed = True
        if process is not None:
            try:
                cleanup(process)
            except Exception as exc:
                print(f"REDEEM_FAILED cleanup: {type(exc).__name__}")
                failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
