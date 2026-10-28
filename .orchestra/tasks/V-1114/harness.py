"""Offline research fixture. No provider, service, credential or network access."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MEMORY = ROOT / ".orchestra/workers/Orchestra-orchestrator.md"
SOURCES = [
    MEMORY,
    ROOT / "AGENTS.md",
    ROOT / ".orchestra/pipelines/default/prompts/modules/knowledge.md",
    ROOT / ".orchestra/pipelines/default/prompts/modules/model-routing.md",
    ROOT / ".orchestra/kb/prompt-engineering.md",
    ROOT / ".orchestra/kb/models-and-quotas.md",
]


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def blocks(text):
    return {f"M{n:02d}": line for n, line in enumerate(text.splitlines(), 1)
            if line.startswith("- **")}


def headline(line):
    match = re.search(r"^- \*\*(.*?)\*\*(?=\s|$)", line)
    if not match:
        raise ValueError("missing bold headline")
    return match[1]


def proxies(text):
    """Mechanical bounds, NOT outputs of the three sleep prompts."""
    rows = blocks(text)
    return {
        "full": text,
        "headlines": "\n".join(headline(line) for line in rows.values()) + "\n",
        "index": "\n".join(f"{bid}: {headline(line)} [archive:{bid}]"
                            for bid, line in rows.items()) + "\n",
        "head_tail": "\n".join(
            f"{bid}: {line if len(line) <= 320 else line[:160] + ' […] ' + line[-160:]}"
            for bid, line in rows.items()) + "\n",
    }


def terms(text):
    # Fixed crude morphology, documented rather than tuned to this question bank.
    return {word[:5] for word in re.findall(r"[\w-]{4,}", text.casefold())}


def retrieve(question, rows, k=3):
    query = terms(question)
    ranked = sorted(rows, key=lambda bid: (-len(query & terms(rows[bid])), bid))
    return ranked[:k]


def bank():
    return json.loads((HERE / "bank.json").read_text())


def validate_bank(cases, rows):
    ids = [c["id"] for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate question ID")
    for case in cases:
        if case["kind"] not in {"fact", "behavior"}:
            raise ValueError("unknown case kind")
        if case["expected"] not in case["options"] or "UNKNOWN" not in case["options"]:
            raise ValueError(f"bad options: {case['id']}")
        for item in case["evidence"]:
            if item["quote"] not in rows[item["id"]]:
                raise ValueError(f"evidence anchor missing: {case['id']}")


def coverage(text, case):
    # Literal anchor survival, not semantic QA or factual accuracy.
    return all(item["quote"] in text for item in case["evidence"])


def score(response, cases, available_ids=None):
    """Exact finite-choice score, with evidence validity separate from decision score."""
    source_ids = set(blocks(MEMORY.read_text()))
    if available_ids is None:
        available_ids = source_ids
    if not isinstance(available_ids, (set, list)) or not all(
            isinstance(c, str) and c in source_ids for c in available_ids):
        raise ValueError("available evidence must be real memory block IDs")
    available_ids = set(available_ids)
    result = {"decision_correct": 0, "supported_correct": 0, "n": len(cases),
              "invalid_schema": False, "items": []}
    if not isinstance(response, dict) or not isinstance(response.get("answers"), list):
        result["invalid_schema"] = True
        return result
    answers = response["answers"]
    if (not all(isinstance(a, dict) and isinstance(a.get("id"), str) for a in answers)
            or len({a["id"] for a in answers}) != len(answers)
            or {a["id"] for a in answers} != {c["id"] for c in cases}):
        result["invalid_schema"] = True
        return result
    by_id = {a["id"]: a for a in answers}
    for case in cases:
        answer = by_id[case["id"]]
        citations = answer.get("evidence_ids")
        required = {e["id"] for e in case["evidence"]}
        correct = answer.get("choice") == case["expected"]
        supported = (isinstance(citations, list)
                     and all(isinstance(c, str) and c in available_ids
                             for c in citations)
                     and required <= set(citations))
        result["decision_correct"] += int(correct)
        result["supported_correct"] += int(correct and supported)
        result["items"].append({"id": case["id"], "correct": correct,
                                "supported": supported})
    return result


def measure():
    text = MEMORY.read_text()
    rows = blocks(text)
    cases = bank()
    validate_bank(cases, rows)
    versions = proxies(text)
    manifest = {str(p.relative_to(ROOT)): {"bytes": len(p.read_bytes()),
                "sha256": sha(p.read_bytes())} for p in SOURCES}
    previous = HERE / "source-manifest.json"
    if previous.exists() and json.loads(previous.read_text()) != manifest:
        raise ValueError("source changed since frozen manifest")
    dump(previous, manifest)
    results = []
    detailed = []
    for name, content in versions.items():
        for retrieval in (False, True):
            observed_sizes = []
            for case in cases:
                ids = retrieve(case["question"], rows) if retrieval else []
                packet = "\n".join(f"{bid}: {rows[bid]}" for bid in ids)
                loaded = content + packet
                size = len(loaded.encode())
                observed_sizes.append(size)
                detailed.append({"variant": name, "retrieval": retrieval,
                    "case": case["id"], "kind": case["kind"],
                    "anchor_survival": coverage(loaded, case),
                    "retrieved_ids": ids, "bytes_memory_and_packet": size})
            own = [r for r in detailed if r["variant"] == name
                   and r["retrieval"] == retrieval]
            results.append({"variant": name, "retrieval": retrieval,
                "artifact_bytes": len(content.encode()),
                "artifact_characters": len(content),
                "artifact_sha256": sha(content.encode()),
                "loaded_bytes_min": min(observed_sizes),
                "loaded_bytes_mean": sum(observed_sizes) / len(observed_sizes),
                "loaded_bytes_max": max(observed_sizes),
                "anchors_fact": sum(r["anchor_survival"] for r in own if r["kind"] == "fact"),
                "n_fact": sum(r["kind"] == "fact" for r in own),
                "anchors_behavior": sum(r["anchor_survival"] for r in own if r["kind"] == "behavior"),
                "n_behavior": sum(r["kind"] == "behavior" for r in own),
                "model_runs": 0, "model_accuracy": None, "tokens": None,
                "cost_usd": None})
    dump(HERE / "offline-measurements.json", {"source_snapshots": 1,
         "metric": "literal required-anchor survival, not Claude performance",
         "memory_blocks": len(rows), "variants": results})
    dump(HERE / "offline-per-case.json", detailed)
    # No raw archive duplicate: the existing unchanged source and its hash are the archive.
    for name in ("headlines", "index", "head_tail"):
        (HERE / f"proxy-{name}.md").write_text(versions[name])
    public = [{k: v for k, v in c.items() if k in {"id", "kind", "question", "options"}}
              for c in cases]
    dump(HERE / "questions-public.json", public)
    dump(HERE / "execution-status.json", {
        "claude_calls": 0, "claude_observed_spend_usd": 0,
        "claude_billing": "api_credit required, not available here",
        "sleep_prompt_runs": 0, "model_performance_verdict": "unmeasured",
        "blockers": ["dynamic_workflow tool absent in worker tool catalog",
                     "exact live reader model/effort not present in copied sources"],
        "not_used": ["subscription Claude CLI", "direct paid API", "child workers"],
        "app_import": "not available: app/ absent in provisioned copy",
    })
    print(json.dumps({"blocks": len(rows), "cases": len(cases),
                      "variants": results}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["measure", "score"])
    parser.add_argument("response", nargs="?", type=Path)
    parser.add_argument("--available-evidence", type=Path,
                        help="JSON list of source IDs actually delivered in this request")
    args = parser.parse_args()
    if args.command == "measure":
        measure()
    elif args.response:
        if not args.available_evidence:
            parser.error("score requires --available-evidence; do not credit unread sources")
        result = score(json.loads(args.response.read_text()), bank(),
                       json.loads(args.available_evidence.read_text()))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return int(result["invalid_schema"] or result["supported_correct"] != result["n"])
    else:
        parser.error("score requires a response JSON file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
