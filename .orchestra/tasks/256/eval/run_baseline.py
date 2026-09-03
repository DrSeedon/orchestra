#!/usr/bin/env python3
"""Read-only #256 retrieval baseline against Orchestra's live memory route.

The artifact deliberately stores no retrieved text. It retains source identifiers,
content hashes, ranks, latency, and whether preregistered anchors were present.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import subprocess
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def load_holdout(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def post_json(url: str, token: str, payload: dict) -> tuple[dict, int, float]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, method="POST", headers=headers)
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read()
    return json.loads(raw), len(raw), (time.perf_counter() - started) * 1000


def aggregate(items: list[dict], limit: int) -> dict:
    by_class: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        by_class[item["class"]].append(item)

    def stats(group: list[dict]) -> dict:
        count = len(group)
        return {
            "n": count,
            "fact_recall": sum(x["fact_rank"] is not None for x in group) / count,
            "canonical_path_recall": sum(x["canonical_path_rank"] is not None for x in group) / count,
            "task_success_proxy": sum(x["task_success_proxy"] for x in group) / count,
            "mrr": sum((1 / x["fact_rank"]) if x["fact_rank"] else 0 for x in group) / count,
            **{
                f"recall_at_{k}": sum(
                    x["fact_rank"] is not None and x["fact_rank"] <= k for x in group
                ) / count
                for k in (1, 3, limit)
            },
        }

    latencies = [x["latency_ms"] for x in items]
    current = by_class.get("current", [])
    matched = [x for x in items if x["fact_rank"] is not None]
    return {
        "all": stats(items),
        "by_class": {key: stats(value) for key, value in sorted(by_class.items())},
        "stale_contradiction_rate_current": (
            sum(x["forbidden_hit_count"] > 0 for x in current) / len(current) if current else None
        ),
        "canonical_provenance_accuracy_when_fact_found": (
            sum(x["canonical_fact_match"] for x in matched) / len(matched) if matched else None
        ),
        "cross_project_leak_rate": sum(x["cross_project_result_count"] > 0 for x in items) / len(items),
        "latency_ms": {
            "median": statistics.median(latencies),
            "p95_nearest_rank": percentile(latencies, 0.95),
            "max": max(latencies),
        },
        "median_chars_before_first_fact": statistics.median(
            x["chars_before_first_fact"] for x in items if x["fact_rank"] is not None
        ) if matched else None,
        "median_token_proxy_before_first_fact_chars_div_3": statistics.median(
            x["token_proxy_before_first_fact_chars_div_3"] for x in matched
        ) if matched else None,
        "tool_calls_to_first_fact_protocol": {
            "retrieval_only": 1,
            "cold_memory_gate_plus_retrieval": 2,
            "note": "README read + one search_memory call; excludes pwd, which is setup rather than knowledge retrieval",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--holdout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8888/api/memory/search")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    token = os.environ.get("INTERNAL_TOKEN", "")
    holdout = load_holdout(args.holdout)
    items = []
    for case in holdout:
        payload = {
            "scope": args.scope,
            "query": case["query"],
            "limit": args.limit,
            "cross_project": False,
        }
        response, response_bytes, latency_ms = post_json(args.url, token, payload)
        if response.get("error"):
            raise RuntimeError(f"{case['id']}: {response['error']}")
        results = response.get("results") or []
        must = case["must_contain"]
        forbidden = case.get("must_not_contain") or []
        fact_rank = None
        canonical_rank = None
        canonical_fact_match = False
        forbidden_hit_count = 0
        chars_before = 0
        metadata = []
        for rank, result in enumerate(results, 1):
            content = result.get("content") or ""
            has_fact = must in content
            bad = [text for text in forbidden if text in content]
            if fact_rank is None and has_fact:
                fact_rank = rank
                canonical_fact_match = result.get("path") == case["gold_path"]
            if canonical_rank is None and result.get("path") == case["gold_path"]:
                canonical_rank = rank
            if fact_rank is None:
                chars_before += len(content)
            forbidden_hit_count += bool(bad)
            metadata.append({
                "rank": rank,
                "source": result.get("source"),
                "path": result.get("path"),
                "kind": result.get("kind"),
                "log_id": result.get("log_id"),
                "project": result.get("project"),
                "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "contains_gold_anchor": has_fact,
                "forbidden_anchor_count": len(bad),
            })
        if fact_rank is None:
            chars_before = sum(len(result.get("content") or "") for result in results)
        task_success = fact_rank is not None and (
            case["class"] != "current" or forbidden_hit_count == 0
        )
        items.append({
            "id": case["id"],
            "class": case["class"],
            "query": case["query"],
            "gold_path": case["gold_path"],
            "gold_anchor_sha256": hashlib.sha256(must.encode("utf-8")).hexdigest(),
            "fact_rank": fact_rank,
            "canonical_path_rank": canonical_rank,
            "canonical_fact_match": canonical_fact_match,
            "forbidden_hit_count": forbidden_hit_count,
            "task_success_proxy": task_success,
            "latency_ms": round(latency_ms, 3),
            "response_bytes": response_bytes,
            "chars_before_first_fact": chars_before,
            "token_proxy_before_first_fact_chars_div_3": math.ceil(chars_before / 3),
            "cross_project_result_count": sum(
                result.get("project") != args.scope for result in results
            ),
            "index": response.get("index") or {},
            "results": metadata,
        })

    git_head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    artifact = {
        "schema": "orchestra-kb-baseline-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_head": git_head,
        "scope": args.scope,
        "endpoint": args.url,
        "limit": args.limit,
        "holdout_sha256": hashlib.sha256(args.holdout.read_bytes()).hexdigest(),
        "token_measurement": "proxy only: Unicode characters / 3, rounded up; no tokenizer installed",
        "items": items,
        "summary": aggregate(items, args.limit),
    }
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
