#!/usr/bin/env python3
"""Create the human-readable #240 measurement table from sanitized JSONL."""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read(name: str) -> list[dict]:
    return [json.loads(line) for line in (HERE / name).read_text().splitlines()]


base = read("raw-runs.jsonl")
rerun = read("raw-backend-rerun.jsonl")
ab = read("raw-ab-final.jsonl")
real = read("raw-real-history.jsonl")
reload = read("raw-reconnect.jsonl")
mcp_control = read("raw-mcp-control.jsonl")[0]

selected = []
selected += ab
selected += [r for r in base if r.get("arm") in {"C_wrapper", "D_managed_full", "E_warm_resume"}]
selected += [r for r in rerun if r.get("arm") in {"C_wrapper", "D_managed_full", "E_warm_resume"}]
selected += [r for r in base if str(r.get("arm", "")).startswith("F_")]
selected += [r for r in rerun if str(r.get("arm", "")).startswith("F_")]
selected += real

for row in selected:
    if row["arm"] in {"A_exec", "B_appserver", "C_wrapper"}:
        row.setdefault("system_prompt_bytes", 0)
        row.setdefault("project_doc_bytes", 104615)
        row.setdefault("mcp_schema_bytes", 0)
        row.setdefault("history_mode", "fresh")
    row.setdefault("history_source_bytes", 0)
    if row["arm"] in {
        "D_managed_full",
        "E_warm_resume",
        "E_real_archived_history",
        "F_no_role_prompt",
        "F_no_project_doc",
    }:
        # Static tools/list payload was corrected after the first serializer omitted schemas.
        row["mcp_schema_bytes"] = 32634
    if row["arm"] == "E_real_archived_history":
        # Read-only stat immediately before the turn. raw-real-history records post-turn size.
        row["history_source_bytes"] = 1370598


def fmt(value, digits: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    if isinstance(value, list):
        return "/".join(str(x) for x in value)
    return str(value)


lines = [
    "# #240 measurement table",
    "",
    "All model rows used CLI 0.149.0, `gpt-5.6-sol`, `xhigh`, `service_tier=default`, "
    "the same cwd, 60-byte task, proxy `http://127.0.0.1:12339`, and zero tool rounds. "
    "`system` means Orchestra's extra `developerInstructions`, not Codex's common internal prompt.",
    "",
    "Time origins: A `final wall` starts at process launch; B–F `final wall` starts at `turn/start`. "
    "`total-to-final` is comparable: A final wall, B–F connect + final wall.",
    "",
    "| arm/rep | argv sha256 | config sha256 | bytes input/system/doc/MCP/history-source | connect / ack / TTFT / final wall / total-to-final, s | tokens input/cached/output/reasoning | loadavg | outcome |",
    "|---|---|---|---:|---:|---:|---:|---|",
]
for row in selected:
    byte_cell = "/".join(
        fmt(row.get(key), 0)
        for key in ("input_bytes", "system_prompt_bytes", "project_doc_bytes", "mcp_schema_bytes", "history_source_bytes")
    )
    total_to_final = row["final_answer_wall_seconds"] + (row.get("connect_init_seconds") or 0)
    time_cell = " / ".join(
        fmt(row.get(key))
        for key in ("connect_init_seconds", "turn_start_ack_seconds", "ttft_seconds", "final_answer_wall_seconds")
    ) + f" / {fmt(total_to_final)}"
    token_cell = "/".join(
        fmt(row.get(key), 0)
        for key in ("input_tokens", "cached_tokens", "output_tokens", "reasoning_tokens")
    )
    lines.append(
        f"| {row['arm']}/{row.get('rep', '—')} | `{row.get('argv_sha256', '—')}` | "
        f"`{row.get('config_sha256', '—')}` | {byte_cell} | {time_cell} | {token_cell} | "
        f"{fmt(row.get('loadavg'))} | {row.get('outcome')} |"
    )

lines += [
    "",
    "## Exact argv catalog",
    "",
]
seen = set()
for row in selected:
    key = row.get("argv_sha256")
    if not key or key in seen:
        continue
    seen.add(key)
    lines += [f"`{key}`", "", "```json", json.dumps(row["argv"], ensure_ascii=False), "```", ""]

local = base[0]
cold = next(r for r in base if r.get("arm") == "N_cold_connect_no_model")
lines += [
    "## No-model controls",
    "",
    f"- Local Python JSON-RPC stdio echo: n={local['samples']}, median={local['median_ms']:.6f} ms, "
    f"p95={local['p95_ms']:.6f} ms, max={local['max_ms']:.6f} ms, load={fmt(local['loadavg'])}.",
    f"- Empty-home app-server initialize + thread/start: {cold['connect_init_seconds']:.6f} s, "
    f"outcome={cold['outcome']}, load={fmt(cold['loadavg'])}.",
]
for row in reload:
    lines.append(
        f"- Config digest rep {row['rep']}: unchanged={row['unchanged_digest_check_seconds']:.6f} s; "
        f"forced reconnect={row['changed_digest_reconnect_seconds']:.6f} s; "
        f"initial connect={row['initial_connect_seconds']:.6f} s; load={fmt(row['loadavg'])}."
    )
orchestra_status = next(server for server in mcp_control["servers"] if server["name"] == "orchestra")
lines.append(
    f"- MCP positive control: startup notifications contain Orchestra `ready`; "
    f"mcpServerStatus/list returned {orchestra_status['tool_count']} Orchestra tools, "
    f"expected={mcp_control['expected_tool_count']}, missing={len(mcp_control['missing_tools'])}."
)


def group(arm: str) -> list[dict]:
    return [r for r in selected if r["arm"] == arm]


analysis = {
    "authoritative_ab_total_to_final_delta_b_minus_a_seconds": [
        round(b["connect_init_seconds"] + b["final_answer_wall_seconds"] - a["final_answer_wall_seconds"], 6)
        for a, b in zip(group("A_exec"), group("B_appserver"))
    ],
    "authoritative_ab_total_to_ttft_delta_b_minus_a_seconds": [
        round(b["connect_init_seconds"] + b["ttft_seconds"] - a["ttft_seconds"], 6)
        for a, b in zip(group("A_exec"), group("B_appserver"))
    ],
    "d_minus_c_final_seconds": [
        round(d["final_answer_wall_seconds"] - c["final_answer_wall_seconds"], 6)
        for c, d in zip(group("C_wrapper"), group("D_managed_full"))
    ],
    "d_minus_c_connect_seconds": [
        round(d["connect_init_seconds"] - c["connect_init_seconds"], 6)
        for c, d in zip(group("C_wrapper"), group("D_managed_full"))
    ],
    "e_minus_d_final_seconds": [
        round(e["final_answer_wall_seconds"] - d["final_answer_wall_seconds"], 6)
        for d, e in zip(group("D_managed_full"), group("E_warm_resume"))
    ],
}


def correlation(xs: list[float], ys: list[float]) -> float:
    mx, my = statistics.mean(xs), statistics.mean(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(
        sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)
    )


analysis["authoritative_input_ttft_r"] = correlation(
    [row["input_tokens"] for row in selected], [row["ttft_seconds"] for row in selected]
)
analysis["authoritative_load1_ttft_r"] = correlation(
    [row["loadavg"][0] for row in selected], [row["ttft_seconds"] for row in selected]
)
comparable_ttft = [
    row["ttft_seconds"] + (row.get("connect_init_seconds") or 0) for row in selected
]
analysis["authoritative_input_total_to_ttft_r"] = correlation(
    [row["input_tokens"] for row in selected], comparable_ttft
)
analysis["authoritative_load1_total_to_ttft_r"] = correlation(
    [row["loadavg"][0] for row in selected], comparable_ttft
)
for arm in ("A_exec", "B_appserver", "C_wrapper", "D_managed_full", "E_warm_resume"):
    vals = [r["final_answer_wall_seconds"] for r in group(arm)]
    analysis[f"{arm}_final_median_seconds"] = statistics.median(vals)
    analysis[f"{arm}_final_range_seconds"] = [min(vals), max(vals)]

(HERE / "measurements.md").write_text("\n".join(lines) + "\n")
(HERE / "analysis.json").write_text(json.dumps(analysis, indent=2, sort_keys=True) + "\n")
print(json.dumps({"rows": len(selected), "analysis": analysis}, sort_keys=True))
