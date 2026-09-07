"""Summarize only usage counters for the two closed KB-work turns; never export prompts."""
import collections
import json
from pathlib import Path
import sys

TURN_IDS = {
    "implementation": "01a070be-c186-7270-86d3-cc8ebc5310a5",
    "merge": "01a070dd-364c-7631-8862-4ec955845f13",
}
KEYS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens",
        "output_tokens", "reasoning_output_tokens")


def audit(path):
    rows = {k: {"turn_id": v, "calls": 0, "tokens": collections.Counter(), "tiers": set()}
            for k, v in TURN_IDS.items()}
    active = tier = previous = None
    duplicates = 0
    for line in path.open():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        payload = record.get("payload") or {}
        if record.get("type") == "turn_context":
            active = payload.get("turn_id")
        if record.get("type") != "event_msg":
            continue
        kind = payload.get("type")
        if kind == "thread_settings_applied":
            tier = (payload.get("thread_settings") or {}).get("service_tier")
        selected = next((row for row in rows.values() if row["turn_id"] == active), None)
        if kind == "task_complete" and selected:
            selected["duration_ms"] = payload.get("duration_ms")
        if kind != "token_count" or not payload.get("info"):
            continue
        info = payload["info"]
        total, last = info["total_token_usage"], info["last_token_usage"]
        duplicate = previous is not None and all(total.get(k, 0) == previous.get(k, 0) for k in KEYS)
        if selected and previous and not duplicate:
            assert all(total.get(k, 0) - previous.get(k, 0) == last.get(k, 0) for k in KEYS), "counter discontinuity"
        previous = total
        if not selected:
            continue
        if duplicate:
            duplicates += 1
            continue
        selected["calls"] += 1
        selected["tokens"].update({k: last.get(k, 0) for k in KEYS})
        selected["tiers"].add(tier)
        selected.setdefault("first_usage_utc", record["timestamp"])
        selected["last_usage_utc"] = record["timestamp"]
    for row in rows.values():
        t = row["tokens"]
        assert row["calls"] and t["input_tokens"] >= t["cached_input_tokens"]
        assert t["output_tokens"] >= t["reasoning_output_tokens"]
        fresh = t["input_tokens"] - t["cached_input_tokens"] - t["cache_write_input_tokens"]
        input_equivalent = (fresh * 10 + t["cached_input_tokens"] + t["cache_write_input_tokens"] * 12.5) / 1e6
        output_equivalent = t["output_tokens"] * 50 / 1e6
        row.update(fresh_input_tokens=fresh,
                   cache_hit=t["cached_input_tokens"] / t["input_tokens"],
                   orchestra_flat_api_equivalent_usd=input_equivalent+output_equivalent,
                   input_cost_share=input_equivalent/(input_equivalent+output_equivalent),
                   estimated_fast_credits=2.5*(fresh*250+t["cached_input_tokens"]*25+t["output_tokens"]*1250)/1e6)
        row["tiers"] = sorted(row["tiers"])
    return {"turns": rows, "duplicate_snapshots_skipped": duplicates,
            "currency_note": "USD is Orchestra's flat standard API-equivalent formula, not cash billing; credits are a rate-table estimate, not an observed account debit."}


if __name__ == "__main__":
    result = audit(Path(sys.argv[1]))
    destination = Path(__file__).with_name("usage-summary.json")
    with destination.open("x") as output:
        json.dump(result, output, indent=2)
    print(json.dumps(result, indent=2))
