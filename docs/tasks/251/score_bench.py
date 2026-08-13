#!/usr/bin/env python3
"""Score the frozen #251 X-retrieval corpus exactly as prereg.md specifies."""

from __future__ import annotations

import itertools
import json
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).parent
RAW = ROOT / "raw"
EXPECTED = {
    "A": {
        "id": "1948007957700268362",
        "handle": "grok",
        "content": (
            "Here are my available tool calls",
            "x_keyword_search",
            "x_semantic_search",
            "x_user_search",
            "x_thread_fetch",
        ),
    },
    "B": {
        "id": "2087564648325530099",
        "handle": "ArtificialAnlys",
        "facts": ("Grok 4.6", "61", "GPT-5.6 Sol"),
        "content": ("SpaceXAI's Grok 4.6 scores 61", "in line with GPT-5.6 Sol"),
    },
    "C": {
        "id": "2035155040218874325",
        "handle": "grok",
        "content": ("Use the right one per task—no universal king.",),
    },
}
MODELS = ("grok-4.5", "grok-4.6")


def snowflake_time(post_id: str) -> datetime:
    milliseconds = (int(post_id) >> 22) + 1288834974657
    return datetime.fromtimestamp(milliseconds / 1000, timezone.utc)


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=timezone.utc)


def extract_answer(text: str) -> tuple[dict, bool]:
    decoder = json.JSONDecoder()
    objects = []
    for offset, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[offset:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "found" in value and "post_url" in value:
            objects.append(value)
    if not objects:
        raise ValueError("no answer object")
    strict_json = isinstance(json.loads(text), dict) if text.startswith("{") else False
    return objects[-1], strict_json


def post_id_from_url(value: str | None) -> str | None:
    if not value:
        return None
    match = re.fullmatch(r"https://x\.com/[^/]+/status/(\d+)", value)
    return match.group(1) if match else None


def load_run(path: Path) -> dict:
    text_chunks = []
    completed_x = []
    fetched_ids = []
    end = None
    for line in path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("type") == "text":
            text_chunks.append(event.get("data", ""))
        elif event.get("type") == "tool_call_update" and event.get("status") == "completed":
            raw = event.get("rawOutput") or {}
            name = raw.get("name", "")
            if name.startswith("x_"):
                completed_x.append(name)
            if name == "x_thread_fetch":
                tool_input = json.loads(raw.get("input") or "{}")
                if tool_input.get("post_id"):
                    fetched_ids.append(str(tool_input["post_id"]))
        elif event.get("type") == "end":
            end = event
    answer, strict_json = extract_answer("".join(text_chunks))
    return {
        "answer": answer,
        "strict_json": strict_json,
        "completed_x": completed_x,
        "fetched_ids": fetched_ids,
        "end": end or {},
    }


def no_fabrication(run: dict) -> bool:
    """Check that an asserted X URL and timestamp are structurally consistent.

    Grok's public streaming JSON redacts tool result bodies. The persisted session retains
    encrypted results, so this is the strongest reproducible check available without asking
    another model to restate the same result.
    """
    answer = run["answer"]
    asserted_id = post_id_from_url(answer.get("post_url"))
    if answer.get("post_url") and not asserted_id:
        return False
    asserted_time = parse_time(answer.get("timestamp"))
    if asserted_time:
        # Search results expose posts directly; a final URL need not also be fetched as a
        # thread. With no URL, require the asserted timestamp to match a fetched post id.
        candidates = [asserted_id] if asserted_id else run["fetched_ids"]
        if not any(abs((asserted_time - snowflake_time(item)).total_seconds()) < 1 for item in candidates):
            return False
    return True


def score(task: str, run: dict) -> tuple[int, dict]:
    expected = EXPECTED[task]
    answer = run["answer"]
    text = answer.get("verbatim_text") or ""
    exact_url = post_id_from_url(answer.get("post_url")) == expected["id"]
    exact_handle = (answer.get("author_handle") or "").lstrip("@").lower() == expected["handle"].lower()
    if task == "B":
        fact_count = sum(fact in text for fact in expected["facts"])
        facts_or_time = 2 if fact_count == 3 else 1 if fact_count == 2 else 0
    else:
        timestamp = parse_time(answer.get("timestamp"))
        facts_or_time = int(
            timestamp is not None
            and abs((timestamp - snowflake_time(expected["id"])).total_seconds()) < 1
        ) * 2
    content = int(all(anchor in text for anchor in expected["content"])) * 2
    x_tool = int(bool(run["completed_x"])) * 2
    clean = int(no_fabrication(run))
    parts = {
        "permalink": int(exact_url) * 2,
        "handle": int(exact_handle),
        "facts_or_time": facts_or_time,
        "content": content,
        "x_tool": x_tool,
        "no_fabrication": clean,
    }
    return sum(parts.values()), parts


def main() -> None:
    rows = []
    for task in EXPECTED:
        for model in MODELS:
            for repetition in (1, 2, 3):
                path = RAW / f"{task}-{model}-{repetition}.jsonl"
                run = load_run(path)
                points, parts = score(task, run)
                rows.append({
                    "task": task,
                    "model": model,
                    "rep": repetition,
                    "score": points,
                    "parts": parts,
                    "strict_json": run["strict_json"],
                    "x_tool_calls": len(run["completed_x"]),
                    "cost_usd": run["end"].get("total_cost_usd"),
                })

    timings = {}
    for line in (RAW / "timings.tsv").read_text().splitlines():
        task, model, repetition, rc, milliseconds = line.split("\t")
        assert rc == "0"
        timings[(task, model, int(repetition))] = int(milliseconds)
    for row in rows:
        row["wall_ms"] = timings[(row["task"], row["model"], row["rep"])]

    by_model = {}
    noise = []
    for model in MODELS:
        model_rows = [row for row in rows if row["model"] == model]
        by_model[model] = {
            "scores": [row["score"] for row in model_rows],
            "mean_score": statistics.mean(row["score"] for row in model_rows),
            "mean_score_unambiguous_AB": statistics.mean(
                row["score"] for row in model_rows if row["task"] in "AB"
            ),
            "median_wall_ms": statistics.median(row["wall_ms"] for row in model_rows),
            "strict_json_runs": sum(row["strict_json"] for row in model_rows),
            "successful_x_runs": sum(row["x_tool_calls"] > 0 for row in model_rows),
            "completed_x_calls": sum(row["x_tool_calls"] for row in model_rows),
            "reported_cost_usd_not_billing_truth": sum(row["cost_usd"] or 0 for row in model_rows),
        }
        for task in EXPECTED:
            task_scores = [row["score"] for row in model_rows if row["task"] == task]
            noise.extend(abs(left - right) for left, right in itertools.combinations(task_scores, 2))

    result = {
        "rows": rows,
        "summary": by_model,
        "difference_4.6_minus_4.5": by_model["grok-4.6"]["mean_score"] - by_model["grok-4.5"]["mean_score"],
        "difference_AB_only": by_model["grok-4.6"]["mean_score_unambiguous_AB"] - by_model["grok-4.5"]["mean_score_unambiguous_AB"],
        "median_own_noise": statistics.median(noise),
        # Public JSONL redacts X result bodies. Structural URL/time checks are reproducible,
        # but they cannot establish that every quote came verbatim from the hidden body.
        "fabrication_check_complete": False,
        "delete_4.5_threshold_passed": False,
        "caveat": (
            "Task C is non-unique: both models fetched multiple real later @grok posts that "
            "satisfy the semantic description, so its frozen exact-target score is reported "
            "but must not be treated as a valid retrieval-quality discriminator. Reported "
            "cost is not billing truth; see usage-reconciliation.json."
        ),
    }
    advantage = result["difference_4.6_minus_4.5"]
    scores_46_a = [row["score"] for row in rows if row["model"] == "grok-4.6" and row["task"] == "A"]
    result["delete_4.5_threshold_passed"] = bool(
        advantage >= 1
        and advantage > result["median_own_noise"]
        and result["fabrication_check_complete"]
        and all(row["parts"]["no_fabrication"] for row in rows if row["model"] == "grok-4.6")
        and min(scores_46_a) >= 8
        and by_model["grok-4.6"]["successful_x_runs"] >= by_model["grok-4.5"]["successful_x_runs"]
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
