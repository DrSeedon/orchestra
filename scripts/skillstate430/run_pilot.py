#!/usr/bin/env python3
"""Paired append-history vs mutable-state pilot for #430.

This is a task-local measurement runner, not a production AgentLoop implementation.
It never opens Orchestra's database. Provider-call outcomes and model outcomes are
separate fields; a failed provider call is never graded as model output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


API = "https://openrouter.ai/api/v1/chat/completions"
ROOT = Path(__file__).resolve().parents[2]
SYSTEM = """You are executing a frozen workflow-memory benchmark derived from real Orchestra tasks.
On every step output one JSON object with exactly two top-level keys: state_patch and action.
state_patch must be an object interpreted as recursive JSON Merge Patch: null deletes a key;
objects merge recursively; arrays and scalars replace. Keep current facts, accepted decisions with
reasons, rejected options with reasons, unresolved questions, and source event ids. Never resurrect
a withdrawn value. action must be an object. On non-final steps use {\"kind\":\"continue\"}.
On the FINAL step action must contain exactly the requested final_action_keys. Do not emit Markdown,
commentary, or any text outside the JSON object. Your private reasoning is not part of the answer."""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_key() -> str:
    value = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if value:
        return value
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            value = line.split("=", 1)[1].strip().strip("\"'")
            if value:
                return value
    raise RuntimeError("OPENROUTER_API_KEY is missing")


def merge_patch(target: Any, patch: Any) -> Any:
    if not isinstance(patch, dict):
        return patch
    base = dict(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            base.pop(key, None)
        else:
            base[key] = merge_patch(base.get(key), value)
    return base


def parse_exact_json(content: str) -> tuple[dict | None, str]:
    try:
        value = json.loads(content)
    except (TypeError, ValueError) as exc:
        return None, f"invalid_json:{type(exc).__name__}"
    if not isinstance(value, dict):
        return None, "top_level_not_object"
    if set(value) != {"state_patch", "action"}:
        return None, "top_level_keys_not_exact"
    if not isinstance(value["state_patch"], dict):
        return None, "state_patch_not_object"
    if not isinstance(value["action"], dict):
        return None, "action_not_object"
    return value, "valid"


def loadavg() -> str:
    return Path("/proc/loadavg").read_text(encoding="utf-8").strip()


@dataclass
class Episode:
    case: dict
    arm: str
    state: dict = field(default_factory=dict)
    history: list[dict] = field(default_factory=lambda: [{"role": "system", "content": SYSTEM}])
    calls: list[dict] = field(default_factory=list)
    failed_call_outcome: str | None = None
    final_action: dict | None = None
    protocol_valid: bool = True

    def messages(self, step: int) -> list[dict]:
        final = step == len(self.case["observations"]) - 1
        packet = {
            "case_id": self.case["case_id"],
            "step": step + 1,
            "steps_total": len(self.case["observations"]),
            "memory_mode": "mutable_state" if self.arm == "state" else "append_only_history",
            "current_state": self.state if self.arm == "state" else {},
            "latest_observation": {
                "event_id": f"{self.case['case_id']}-E{step + 1:02d}",
                "text": self.case["observations"][step],
            },
            "final": final,
            "final_action_keys": self.case["final_action_keys"] if final else [],
        }
        user = {"role": "user", "content": json.dumps(packet, ensure_ascii=False, sort_keys=True)}
        if self.arm == "state":
            return [{"role": "system", "content": SYSTEM}, user]
        self.history.append(user)
        return self.history

    def accept(self, raw_content: str, parsed: dict | None, step: int, message: dict) -> None:
        if self.arm != "state":
            assistant = {"role": "assistant", "content": raw_content}
            for key in ("reasoning", "reasoning_details"):
                if message.get(key) is not None:
                    assistant[key] = message[key]
            self.history.append(assistant)
        if parsed is None:
            self.protocol_valid = False
            return
        if self.arm == "state":
            self.state = merge_patch(self.state, parsed["state_patch"])
        if step == len(self.case["observations"]) - 1:
            self.final_action = parsed["action"]


def provider_outcome(status: int | None, detail: str) -> str:
    if status == 404:
        return "provider_404"
    if status == 429:
        return "provider_429"
    if status is not None and status >= 400:
        return f"provider_http_{status}"
    if "timeout" in detail.lower():
        return "provider_timeout"
    return "provider_transport_error"


def grade(episode: Episode) -> dict:
    if episode.failed_call_outcome:
        return {"call_outcome": episode.failed_call_outcome, "model_outcome": "not_graded"}
    action = episode.final_action or {}
    gold = episode.case["gold_action"]
    fields = {key: action.get(key) == value for key, value in gold.items()}
    serialized = json.dumps(action, ensure_ascii=False, sort_keys=True)
    forbidden = [value for value in episode.case["forbidden_values"] if value in serialized]
    critical_loss = [key for key in episode.case["critical_keys"] if not fields.get(key, False)]
    score = sum(fields.values()) / len(fields)
    success = episode.protocol_valid and all(fields.values()) and not forbidden
    return {
        "call_outcome": "provider_success",
        "model_outcome": "success" if success else "model_error",
        "protocol_valid": episode.protocol_valid,
        "field_score": score,
        "fields": fields,
        "critical_loss": critical_loss,
        "forbidden_values_present": forbidden,
        "final_action": action,
    }


def total_usage(episode: Episode) -> dict:
    keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    return {key: sum(int(call.get("usage", {}).get(key) or 0) for call in episode.calls) for key in keys}


def rel_abs(a: float, b: float) -> float:
    denominator = (a + b) / 2
    return abs(a - b) / denominator if denominator else 0.0


def summarize(episodes: dict[tuple[str, str], Episode], order: list[dict], route: str) -> dict:
    cases = sorted({case_id for case_id, _ in episodes})
    rows = []
    for case_id in cases:
        row = {"case_id": case_id, "arms": {}}
        for arm in ("append", "state", "append_repeat"):
            episode = episodes[(case_id, arm)]
            row["arms"][arm] = {"grade": grade(episode), "usage": total_usage(episode)}
        rows.append(row)
    complete = [
        row for row in rows
        if all(row["arms"][arm]["grade"]["call_outcome"] == "provider_success"
               for arm in ("append", "state", "append_repeat"))
    ]
    token_noise = [
        rel_abs(row["arms"]["append"]["usage"]["total_tokens"],
                row["arms"]["append_repeat"]["usage"]["total_tokens"])
        for row in complete
    ]
    quality_noise = [
        abs(row["arms"]["append"]["grade"]["field_score"]
            - row["arms"]["append_repeat"]["grade"]["field_score"])
        for row in complete
    ]
    ab_savings = [
        1 - (row["arms"]["state"]["usage"]["total_tokens"]
             / row["arms"]["append"]["usage"]["total_tokens"])
        for row in complete if row["arms"]["append"]["usage"]["total_tokens"]
    ]
    thresholds = {
        "derivation": "worst observed same-arm append-vs-append_repeat instability on completed pilot cases",
        "minimum_total_token_saving": max(token_noise) if token_noise else None,
        "quality_noninferiority_margin": max(quality_noise) if quality_noise else None,
        "critical_reason_losses_allowed": 0,
    }
    return {
        "schema": "skillstate430-pilot-summary-v1",
        "route": route,
        "model_parameters": {"temperature": 0, "max_tokens": 700, "seed": "case-derived"},
        "interleaving": "arm order rotates on every case step; loadavg recorded per request",
        "rows": rows,
        "completed_three_arm_cases": len(complete),
        "provider_outcomes": {
            outcome: sum(
                grade(ep)["call_outcome"] == outcome for ep in episodes.values()
            )
            for outcome in sorted({grade(ep)["call_outcome"] for ep in episodes.values()})
        },
        "noise": {
            "same_arm_total_token_relative_abs": token_noise,
            "same_arm_quality_abs": quality_noise,
        },
        "observed_primary_ab_total_token_saving": ab_savings,
        "frozen_full_benchmark_thresholds": thresholds,
        "request_order": order,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--route", required=True)
    parser.add_argument("--cases", default=str(Path(__file__).with_name("pilot_cases.json")))
    parser.add_argument("--raw", required=True)
    parser.add_argument("--interval", type=float, default=3.2)
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()
    if not args.route.endswith(":free"):
        raise RuntimeError("pilot route must be exact :free")
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    episodes = {
        (case["case_id"], arm): Episode(case=case, arm=arm)
        for case in cases for arm in ("append", "state", "append_repeat")
    }
    raw_path = Path(args.raw)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    key = load_key()
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    order_log: list[dict] = []
    sequence = 0
    with raw_path.open("w", encoding="utf-8") as raw_file, httpx.Client(timeout=args.timeout) as client:
        for case_index, case in enumerate(cases):
            arms = ("append", "state", "append_repeat")
            for step in range(len(case["observations"])):
                rotation = (case_index + step) % len(arms)
                scheduled = arms[rotation:] + arms[:rotation]
                for arm in scheduled:
                    episode = episodes[(case["case_id"], arm)]
                    if episode.failed_call_outcome:
                        continue
                    messages = episode.messages(step)
                    seed_text = f"skillstate430:{case['case_id']}:stable"
                    seed = int(hashlib.sha256(seed_text.encode()).hexdigest()[:8], 16)
                    body = {
                        "model": args.route,
                        "messages": messages,
                        "stream": False,
                        "temperature": 0,
                        "seed": seed,
                        "max_tokens": 700,
                        "usage": {"include": True},
                    }
                    sequence += 1
                    record = {
                        "sequence": sequence,
                        "started_at": utcnow(),
                        "case_id": case["case_id"],
                        "arm": arm,
                        "step": step + 1,
                        "route": args.route,
                        "http_attempts": 1,
                        "loadavg": loadavg(),
                    }
                    order_log.append({key: record[key] for key in ("sequence", "case_id", "arm", "step", "loadavg")})
                    try:
                        response = client.post(API, headers=headers, json=body)
                        record["http_status"] = response.status_code
                        if response.status_code >= 400:
                            outcome = provider_outcome(response.status_code, response.text)
                            record["call_outcome"] = outcome
                            record["detail"] = response.text[:500]
                            episode.failed_call_outcome = outcome
                        else:
                            payload = response.json()
                            choices = payload.get("choices") or []
                            if not choices:
                                outcome = "provider_malformed_success"
                                record.update({
                                    "call_outcome": outcome,
                                    "payload_keys": sorted(payload),
                                    "payload_error": payload.get("error"),
                                })
                                episode.failed_call_outcome = outcome
                            else:
                                message = choices[0].get("message") or {}
                                content = message.get("content") or ""
                                parsed, parse_outcome = parse_exact_json(content)
                                usage = payload.get("usage") or {}
                                record.update({
                                    "call_outcome": "provider_success",
                                    "model_parse_outcome": parse_outcome,
                                    "usage": {key: usage.get(key) for key in (
                                        "prompt_tokens", "completion_tokens", "total_tokens", "cost"
                                    ) if usage.get(key) is not None},
                                    "response_model": payload.get("model"),
                                    "content": content,
                                })
                                episode.calls.append(record)
                                episode.accept(content, parsed, step, message)
                    except (httpx.TimeoutException, httpx.TransportError) as exc:
                        outcome = provider_outcome(None, type(exc).__name__)
                        record.update({"call_outcome": outcome, "detail": type(exc).__name__})
                        episode.failed_call_outcome = outcome
                    raw_file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                    raw_file.flush()
                    time.sleep(args.interval)
    print(json.dumps(summarize(episodes, order_log, args.route), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
