#!/usr/bin/env python3
"""Read-only Turbovec candidate benchmark on Orchestra's current RAG corpus.

The live sqlite-vec database is opened read-only. Candidate indexes and results are written
only below --work-dir / --output. No production table, index, service, or configuration changes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import statistics
import time
from pathlib import Path

import numpy as np

from app.rag import DIM, POOL_MULT, RagMemory


def load_holdout(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def load_vectors(memory: RagMemory, table: str, project: str) -> tuple[np.ndarray, np.ndarray]:
    rows = memory.conn.execute(
        f"SELECT chunk_id, embedding FROM {table} WHERE project=? ORDER BY chunk_id",
        (project,),
    ).fetchall()
    ids = np.empty(len(rows), dtype=np.uint64)
    vectors = np.empty((len(rows), DIM), dtype=np.float32)
    for i, row in enumerate(rows):
        ids[i] = row["chunk_id"]
        vectors[i] = np.frombuffer(row["embedding"], dtype=np.float32, count=DIM)
    return ids, vectors


def evaluate(cases: list[dict], outputs: list[list[dict]]) -> dict:
    items = []
    for case, results in zip(cases, outputs, strict=True):
        fact_rank = None
        canonical_rank = None
        forbidden = 0
        for rank, result in enumerate(results, 1):
            content = result.get("content") or ""
            if fact_rank is None and case["must_contain"] in content:
                fact_rank = rank
            if canonical_rank is None and result.get("path") == case["gold_path"]:
                canonical_rank = rank
            forbidden += any(x in content for x in case.get("must_not_contain") or [])
        items.append(
            {
                "id": case["id"],
                "class": case["class"],
                "fact_rank": fact_rank,
                "canonical_path_rank": canonical_rank,
                "forbidden_hit_count": forbidden,
                "task_success_proxy": fact_rank is not None
                and (case["class"] != "current" or forbidden == 0),
                "results": [
                    {
                        "rank": rank,
                        "source": result.get("source"),
                        "path": result.get("path"),
                        "kind": result.get("kind"),
                        "log_id": result.get("log_id"),
                        "content_sha256": hashlib.sha256(
                            (result.get("content") or "").encode()
                        ).hexdigest(),
                    }
                    for rank, result in enumerate(results, 1)
                ],
            }
        )

    def stats(group: list[dict]) -> dict:
        n = len(group)
        return {
            "n": n,
            "fact_recall_at_5": sum(x["fact_rank"] is not None for x in group) / n,
            "canonical_path_recall_at_5": sum(
                x["canonical_path_rank"] is not None for x in group
            )
            / n,
            "task_success_proxy": sum(x["task_success_proxy"] for x in group) / n,
            "mrr_at_5": sum(1 / x["fact_rank"] if x["fact_rank"] else 0 for x in group) / n,
        }

    classes = sorted({x["class"] for x in items})
    current = [x for x in items if x["class"] == "current"]
    return {
        "all": stats(items),
        "by_class": {c: stats([x for x in items if x["class"] == c]) for c in classes},
        "stale_contradiction_rate_current": sum(
            x["forbidden_hit_count"] > 0 for x in current
        )
        / len(current),
        "items": items,
    }


def vector_agreement(exact: list[int], candidate: list[int]) -> dict:
    exact_set = set(exact)
    candidate_set = set(candidate)
    return {
        "exact_top1_in_candidate_top20": bool(exact and exact[0] in candidate_set),
        "exact_top5_in_candidate_top20": (
            sum(x in candidate_set for x in exact[:5]) / min(5, len(exact))
            if exact
            else None
        ),
        "overlap_at_20": (
            len(exact_set & candidate_set) / min(len(exact_set), len(candidate_set))
            if exact_set and candidate_set
            else None
        ),
    }


def make_index(cls, dim: int, bit_width: int, ids: np.ndarray, vectors: np.ndarray, seed: int):
    index = cls(dim=dim, bit_width=bit_width)
    rng = np.random.default_rng(seed)
    sample_n = min(1024, len(vectors))
    sample = vectors[rng.choice(len(vectors), size=sample_n, replace=False)]
    t0 = time.perf_counter()
    index.calibrate(sample)
    calibration_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    index.add_with_ids(vectors, ids)
    add_s = time.perf_counter() - t0
    return index, calibration_s, add_s


def candidate_search(index, query_vec: list[float], pool: int) -> list[int]:
    query = np.asarray(query_vec, dtype=np.float32).reshape(1, -1)
    _scores, ids = index.search(query, k=pool)
    return [int(x) for x in np.asarray(ids).reshape(-1)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("data/vec.db"))
    parser.add_argument("--holdout", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    from turbovec import IdMapIndex, __version__ as turbovec_version

    args.work_dir.mkdir(parents=True, exist_ok=True)
    memory = RagMemory(args.db, readonly=True)
    cases = load_holdout(args.holdout)

    t0 = time.perf_counter()
    query_vectors = np.asarray(
        memory._embed([x["query"] for x in cases], is_query=True), dtype=np.float32
    )
    embed_batch_s = time.perf_counter() - t0

    file_ids, file_vectors = load_vectors(memory, "vec_files", args.project)
    log_ids, log_vectors = load_vectors(memory, "vec_logs", args.project)

    original_embed = memory._embed
    original_file = memory._vec_search_files
    original_log = memory._vec_search_logs
    limit = 5
    pool = max(limit * POOL_MULT, limit)

    artifact = {
        "schema": "orchestra-turbovec-pilot-v1",
        "created_at": time.time(),
        "git_head": os.popen("git rev-parse HEAD").read().strip(),
        "project": args.project,
        "holdout_sha256": hashlib.sha256(args.holdout.read_bytes()).hexdigest(),
        "hardware": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "loadavg_start": os.getloadavg(),
        },
        "versions": {"turbovec": turbovec_version, "dim": DIM},
        "corpus": {
            "file_vectors": len(file_ids),
            "log_vectors": len(log_ids),
            "raw_fp32_bytes": int(file_vectors.nbytes + log_vectors.nbytes),
            "embed_18_queries_batch_s": embed_batch_s,
        },
        "candidates": {},
    }

    for bit_width in (4, 2):
        file_index, file_cal_s, file_add_s = make_index(
            IdMapIndex, DIM, bit_width, file_ids, file_vectors, 3900 + bit_width
        )
        log_index, log_cal_s, log_add_s = make_index(
            IdMapIndex, DIM, bit_width, log_ids, log_vectors, 4900 + bit_width
        )
        file_path = args.work_dir / f"files-{bit_width}bit.tvim"
        log_path = args.work_dir / f"logs-{bit_width}bit.tvim"
        t0 = time.perf_counter()
        file_index.write(str(file_path))
        file_write_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        log_index.write(str(log_path))
        log_write_s = time.perf_counter() - t0

        baseline_outputs: list[list[dict]] = []
        candidate_outputs: list[list[dict]] = []
        baseline_ms: list[float] = []
        baseline_control_ms: list[float] = []
        candidate_ms: list[float] = []
        file_agreement = []
        log_agreement = []

        for i, (case, query_np) in enumerate(zip(cases, query_vectors, strict=True)):
            query_vec = query_np.tolist()
            exact_files = original_file(args.project, query_vec, pool, False)
            exact_logs = original_log(args.project, query_vec, pool, False, None)
            tq_files = candidate_search(file_index, query_vec, pool)
            tq_logs = candidate_search(log_index, query_vec, pool)
            file_agreement.append(vector_agreement(exact_files, tq_files))
            log_agreement.append(vector_agreement(exact_logs, tq_logs))

            memory._embed = lambda _texts, is_query=True, q=query_vec: [q]

            def run_baseline():
                memory._vec_search_files = original_file
                memory._vec_search_logs = original_log
                started = time.perf_counter()
                value = memory.search(args.project, case["query"], limit=limit)
                return value, (time.perf_counter() - started) * 1000

            def run_candidate():
                memory._vec_search_files = (
                    lambda _project, q, p, cross, idx=file_index: candidate_search(idx, q, p)
                )
                memory._vec_search_logs = (
                    lambda _project, q, p, cross, kinds, idx=log_index:
                    candidate_search(idx, q, p)
                )
                started = time.perf_counter()
                value = memory.search(args.project, case["query"], limit=limit)
                return value, (time.perf_counter() - started) * 1000

            order = i % 3
            if order == 0:
                baseline, baseline_t = run_baseline()
                candidate, candidate_t = run_candidate()
                _control, control_t = run_baseline()
            elif order == 1:
                candidate, candidate_t = run_candidate()
                baseline, baseline_t = run_baseline()
                _control, control_t = run_baseline()
            else:
                baseline, baseline_t = run_baseline()
                _control, control_t = run_baseline()
                candidate, candidate_t = run_candidate()
            baseline_outputs.append(baseline)
            candidate_outputs.append(candidate)
            baseline_ms.append(baseline_t)
            baseline_control_ms.append(control_t)
            candidate_ms.append(candidate_t)

        memory._embed = original_embed
        memory._vec_search_files = original_file
        memory._vec_search_logs = original_log

        def aggregate_agreement(rows: list[dict]) -> dict:
            return {
                "top1_in_top20": sum(x["exact_top1_in_candidate_top20"] for x in rows)
                / len(rows),
                "top5_coverage_in_top20": statistics.mean(
                    x["exact_top5_in_candidate_top20"] for x in rows
                ),
                "mean_overlap_at_20": statistics.mean(x["overlap_at_20"] for x in rows),
            }

        artifact["candidates"][str(bit_width)] = {
            "build": {
                "calibration_s": file_cal_s + log_cal_s,
                "add_s": file_add_s + log_add_s,
                "write_s": file_write_s + log_write_s,
                "persisted_bytes": file_path.stat().st_size + log_path.stat().st_size,
            },
            "latency_excluding_embedding_ms": {
                "baseline_median": statistics.median(baseline_ms),
                "baseline_control_median": statistics.median(baseline_control_ms),
                "candidate_median": statistics.median(candidate_ms),
                "aa_absolute_delta_median": statistics.median(
                    abs(a - b) for a, b in zip(baseline_ms, baseline_control_ms, strict=True)
                ),
                "paired_gain_median": statistics.median(
                    ((a + b) / 2) - c
                    for a, b, c in zip(
                        baseline_ms, baseline_control_ms, candidate_ms, strict=True
                    )
                ),
                "baseline_samples": baseline_ms,
                "baseline_control_samples": baseline_control_ms,
                "candidate_samples": candidate_ms,
            },
            "vector_agreement": {
                "files": aggregate_agreement(file_agreement),
                "logs": aggregate_agreement(log_agreement),
            },
            "retrieval": {
                "baseline": evaluate(cases, baseline_outputs),
                "candidate": evaluate(cases, candidate_outputs),
            },
        }

    artifact["hardware"]["loadavg_end"] = os.getloadavg()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(artifact, ensure_ascii=False))


if __name__ == "__main__":
    main()
