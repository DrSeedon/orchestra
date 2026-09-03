"""#364 — GigaEmbeddings 480M vs production bge-m3 on the #134 corpus.

The retrieval and scoring primitives are imported from the frozen #134 harness.
Production data is never opened writable: the candidate database is created with
``sqlite3.Connection.backup`` and only that copy has its vector rows replaced.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import random
import resource
import sqlite3
import statistics
import struct
import sys
import time
from pathlib import Path
from typing import Callable


ROOT = Path(os.environ.get("ORCHESTRA_ROOT", Path(__file__).resolve().parents[4]))
HERE = Path(__file__).resolve().parent
QUERY_PATH = ROOT / "docs/tasks/134/bench/queries.json"
HARNESS_PATH = ROOT / "docs/tasks/134/bench/retrieval_bench.py"
QUERY_SHA256 = "516b0755416b763233df0d8c5835b16c875284144e55be9ca6e91d0f4d4dbd0a"
HARNESS_SHA256 = "5175a900e5d3ab14cb6ea2fe17c4f80d34958451421ac1f64419ca584fee2d84"
CORPUS_SHA256 = "92808d6b4170daf3e5c8784377c1e0a48dfebc60a9c53c3dbf514a2b49135ab2"
PROJECT = "/mnt/data/Projects/Python/orchestra"
SQLITE_VEC_SITE = Path(PROJECT) / ".venv/lib/python3.12/site-packages"
MODEL_REPO = "ai-sage/Giga-Embeddings-instruct-480M-0826"
MODEL_REVISION = "2d0c1a92716eef0e5b6972df85b5883eb5b4f57a"
MODEL_WEIGHT_SHA256 = "9ce03c6c5ae02baebb42ce3015b6f3e628c5fec7b7745bc2490f6ff961a654a5"
BASELINE_MODEL_REVISION = "a4136c5faa1b666e68595c9d0cb2dac7f196ddd5"
BASELINE_ONNX_SHA256 = "17dbde8d0da550b94f5b8840e4305a0374d700a5c844d65b3bc9646369c559ce"
INSTRUCTION = "Given a query, retrieve relevant passages"
QUERY_PREFIX = f"Instruct: {INSTRUCTION}\nQuery: "
DIM = 1024
SPLIT_HALF_REPEATS = 20_000
SPLIT_HALF_SEED = 135


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_harness():
    actual = sha256(HARNESS_PATH)
    if actual != HARNESS_SHA256:
        raise RuntimeError(f"#134 harness sha256 mismatch: {actual}")
    spec = importlib.util.spec_from_file_location("retrieval_bench_134", HARNESS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {HARNESS_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PROJECT = PROJECT
    return module


def load_queries() -> list[dict]:
    actual = sha256(QUERY_PATH)
    if actual != QUERY_SHA256:
        raise RuntimeError(f"queries sha256 mismatch: {actual}")
    return json.loads(QUERY_PATH.read_text())["queries"]


def load_sqlite_vec(conn: sqlite3.Connection) -> None:
    try:
        import sqlite_vec
    except ModuleNotFoundError:
        # The GPU runtime deliberately reuses the task-independent CUDA PyTorch
        # environment. sqlite-vec stays owned by Orchestra's production venv.
        sys.path.append(str(SQLITE_VEC_SITE))
        import sqlite_vec
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)


def open_db(path: Path, *, readonly: bool) -> sqlite3.Connection:
    target = f"file:{path}?mode=ro" if readonly else str(path)
    conn = sqlite3.connect(target, uri=readonly, isolation_level=None)
    conn.row_factory = sqlite3.Row
    load_sqlite_vec(conn)
    return conn


def score_arm(
    db_path: Path,
    arm: str,
    embed_queries: Callable[[list[str]], list[list[float]]],
) -> dict:
    harness = load_harness()
    queries = load_queries()
    conn = open_db(db_path, readonly=True)
    per_query = []
    started = time.monotonic()
    try:
        for idx, item in enumerate(queries, start=1):
            qvec = embed_queries([item["q"]])[0]
            v_files, v_logs = harness.vec_search(conn, qvec, harness.RERANK_POOL)
            f_files, f_logs = harness.fts_search(conn, item["q"], harness.RERANK_POOL)
            ranked = harness.rrf(v_files, f_files, v_logs, f_logs)
            gold = set(item["gold"])
            rank = next(
                (pos for pos, (_tag, chunk_id) in enumerate(ranked[: harness.FINAL_K], 1)
                 if chunk_id in gold),
                None,
            )
            rr = 0.0 if rank is None else 1.0 / rank
            per_query.append({"index": idx, "q": item["q"], "gold": item["gold"],
                              "rank": rank, "rr": rr})
            print(f"{arm} {idx:02d}/28 rank={rank or 0} rr={rr:.4f}", flush=True)
    finally:
        conn.close()
    rrs = [row["rr"] for row in per_query]
    ranks = [row["rank"] for row in per_query]
    n = len(rrs)
    return {
        "arm": arm,
        "summary": {
            "n": n,
            "MRR": sum(rrs) / n,
            "R@3": sum(rank is not None and rank <= 3 for rank in ranks) / n,
            "R@5": sum(rank is not None and rank <= 5 for rank in ranks) / n,
            "elapsed_s": time.monotonic() - started,
        },
        "per_query": per_query,
    }


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    print(f"WROTE {path}")


def baseline(args: argparse.Namespace) -> None:
    db_path = Path(args.db)
    actual = sha256(db_path)
    if actual != CORPUS_SHA256:
        raise RuntimeError(f"#134 corpus sha256 mismatch: {actual}")
    os.environ.setdefault("FASTEMBED_CACHE_PATH", str(ROOT / "data/models"))
    os.environ.setdefault("RAG_ONNX_THREADS", "1")
    baseline_onnx = (
        Path(os.environ["FASTEMBED_CACHE_PATH"])
        / "models--AlpEge--bge-m3-onnx-int8/snapshots"
        / BASELINE_MODEL_REVISION
        / "model_quantized.onnx"
    )
    onnx_sha = sha256(baseline_onnx)
    if onnx_sha != BASELINE_ONNX_SHA256:
        raise RuntimeError(f"baseline ONNX sha256 mismatch: {onnx_sha}")
    harness = load_harness()
    result = score_arm(db_path, "prod_bge_m3_hybrid", harness.embed_local)
    result["provenance"] = {
        "corpus": str(db_path),
        "corpus_sha256": actual,
        "queries": str(QUERY_PATH),
        "queries_sha256": QUERY_SHA256,
        "harness": str(HARNESS_PATH),
        "harness_sha256": HARNESS_SHA256,
        "model": "AlpEge/bge-m3-onnx-int8",
        "model_revision": BASELINE_MODEL_REVISION,
        "model_onnx_sha256": onnx_sha,
        "pooling": "CLS + L2",
        "query_prefix": None,
    }
    write_json(Path(args.out), result)


class GigaEmbedder:
    def __init__(self, model_path: Path, *, batch_size: int):
        import torch
        import transformers
        from transformers import AutoModel, AutoTokenizer

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required for this bounded laptop run")
        self.torch = torch
        self.transformers_version = transformers.__version__
        self.batch_size = batch_size
        self.model_path = model_path
        weight_sha = sha256(model_path / "model.safetensors")
        if weight_sha != MODEL_WEIGHT_SHA256:
            raise RuntimeError(f"model weight sha256 mismatch: {weight_sha}")
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_path, trust_remote_code=True, local_files_only=True
        )
        # GTX 1650 (compute capability 7.5) has no native BF16. FP16 is the
        # bounded GPU path; the exact BF16 checkpoint bytes remain pinned above.
        self.model = AutoModel.from_pretrained(
            model_path,
            trust_remote_code=True,
            local_files_only=True,
            dtype=torch.float16,
        ).cuda().eval()

    def encode(self, texts: list[str], *, is_query: bool) -> list[list[float]]:
        torch = self.torch
        source = [QUERY_PREFIX + text for text in texts] if is_query else texts
        out: list[list[float]] = []
        for start in range(0, len(source), self.batch_size):
            batch = source[start:start + self.batch_size]
            encoded = self.tokenizer(
                batch,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=512,
            )
            encoded = {name: tensor.cuda() for name, tensor in encoded.items()}
            with torch.inference_mode():
                hidden = self.model(**encoded).last_hidden_state
                mask = encoded["attention_mask"].unsqueeze(-1).to(hidden.dtype)
                # Accumulate and normalize in FP32 so the only precision change
                # from the pinned checkpoint is the documented FP16 model path.
                pooled = (hidden.float() * mask.float()).sum(1)
                pooled = pooled / mask.float().sum(1).clamp(min=1e-6)
                pooled = torch.nn.functional.normalize(pooled, dim=-1)
            out.extend(pooled.cpu().tolist())
        return out

    def metadata(self) -> dict:
        torch = self.torch
        props = torch.cuda.get_device_properties(0)
        return {
            "repo": MODEL_REPO,
            "revision": MODEL_REVISION,
            "weights_sha256": MODEL_WEIGHT_SHA256,
            "transformers": self.transformers_version,
            "torch": torch.__version__,
            "device": props.name,
            "compute_capability": f"{props.major}.{props.minor}",
            "model_dtype": "float16 (BF16 checkpoint converted for GTX 1650)",
            "pooling": "mean over non-padding tokens + L2",
            "document_prefix": None,
            "query_prefix": QUERY_PREFIX,
            "max_length": 512,
            "batch_size": self.batch_size,
        }


def probe(args: argparse.Namespace) -> None:
    model = GigaEmbedder(Path(args.model), batch_size=args.batch_size)
    texts = [
        "SQLite хранит данные в таблицах и поддерживает транзакции.",
        "Векторный поиск ранжирует документы по близости эмбеддингов.",
        "Оркестратор запускает агентов в отдельных рабочих деревьях.",
    ]
    vectors = model.encode(texts, is_query=False)
    queries = model.encode(["как устроен векторный поиск"], is_query=True)
    norms = [math.sqrt(sum(x * x for x in vector)) for vector in vectors + queries]
    sims = [sum(a * b for a, b in zip(queries[0], vector)) for vector in vectors]
    result = {
        "metadata": model.metadata(),
        "dimensions": [len(vector) for vector in vectors + queries],
        "norms": norms,
        "similarities": sims,
        "best_document_index": max(range(len(sims)), key=sims.__getitem__),
        "cuda_max_memory_allocated_bytes": model.torch.cuda.max_memory_allocated(),
        "rss_max_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    if result["dimensions"] != [DIM] * 4:
        raise RuntimeError(f"wrong embedding dimensions: {result['dimensions']}")
    if any(abs(norm - 1.0) > 1e-5 for norm in norms):
        raise RuntimeError(f"embeddings are not L2-normalized: {norms}")
    write_json(Path(args.out), result)


def backup_database(source: Path, candidate: Path) -> None:
    if candidate.exists():
        raise RuntimeError(f"candidate already exists; use --resume or remove explicitly: {candidate}")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src, sqlite3.connect(candidate) as dst:
        src.backup(dst, pages=4096)
    print(f"BACKUP {candidate} elapsed_s={time.monotonic() - started:.3f}", flush=True)


def reindex_kind(
    source: sqlite3.Connection,
    candidate: sqlite3.Connection,
    model: GigaEmbedder,
    kind: str,
    batch_size: int,
) -> int:
    if kind == "file":
        select_sql = (
            "SELECT fc.chunk_id, fc.file_id AS owner_id, NULL AS kind, fc.text "
            "FROM file_chunks fc JOIN files f USING(file_id) "
            "WHERE f.project=? AND fc.chunk_id>? ORDER BY fc.chunk_id LIMIT ?"
        )
        vec_table = "vec_files"
        insert_sql = (
            "INSERT INTO vec_files(chunk_id,file_id,project,embedding) VALUES(?,?,?,?)"
        )
    elif kind == "log":
        select_sql = (
            "SELECT lc.chunk_id, lc.log_id AS owner_id, lc.kind, lc.text "
            "FROM log_chunks lc JOIN logs_indexed li USING(log_id) "
            "WHERE li.project=? AND lc.chunk_id>? ORDER BY lc.chunk_id LIMIT ?"
        )
        vec_table = "vec_logs"
        insert_sql = (
            "INSERT INTO vec_logs(chunk_id,log_id,kind,project,embedding) VALUES(?,?,?,?,?)"
        )
    else:
        raise ValueError(kind)

    row = candidate.execute(
        "SELECT last_chunk_id FROM bench364_progress WHERE kind=?", (kind,)
    ).fetchone()
    last = int(row[0]) if row else -1
    done = 0
    started = time.monotonic()
    while True:
        rows = source.execute(select_sql, (PROJECT, last, batch_size)).fetchall()
        if not rows:
            break
        vectors = model.encode([row["text"] for row in rows], is_query=False)
        candidate.execute("BEGIN")
        try:
            for row, vector in zip(rows, vectors):
                candidate.execute(f"DELETE FROM {vec_table} WHERE chunk_id=?", (row["chunk_id"],))
                blob = struct.pack(f"{len(vector)}f", *vector)
                if kind == "file":
                    params = (row["chunk_id"], row["owner_id"], PROJECT, blob)
                else:
                    params = (row["chunk_id"], row["owner_id"], row["kind"], PROJECT, blob)
                candidate.execute(insert_sql, params)
            last = int(rows[-1]["chunk_id"])
            candidate.execute(
                "INSERT OR REPLACE INTO bench364_progress(kind,last_chunk_id,model_revision) "
                "VALUES(?,?,?)", (kind, last, MODEL_REVISION)
            )
            candidate.execute("COMMIT")
        except Exception:
            candidate.execute("ROLLBACK")
            raise
        done += len(rows)
        elapsed = time.monotonic() - started
        rate = done / elapsed if elapsed else 0.0
        print(f"REINDEX {kind} batch={len(rows)} total_this_run={done} "
              f"last={last} rate={rate:.2f}/s", flush=True)
    return done


def giga(args: argparse.Namespace) -> None:
    source_path = Path(args.source)
    candidate_path = Path(args.candidate)
    try:
        aliases_source = source_path.samefile(candidate_path)
    except FileNotFoundError:
        aliases_source = source_path.resolve() == candidate_path.resolve()
    if aliases_source:
        raise RuntimeError("source and candidate must be different SQLite files")
    if sha256(source_path) != CORPUS_SHA256:
        raise RuntimeError("source is not the pinned #134 corpus")
    if not args.resume:
        backup_database(source_path, candidate_path)
    elif not candidate_path.exists():
        raise RuntimeError("--resume requires an existing candidate database")

    source = open_db(source_path, readonly=True)
    candidate = open_db(candidate_path, readonly=False)
    candidate.execute(
        "CREATE TABLE IF NOT EXISTS bench364_progress("
        "kind TEXT PRIMARY KEY,last_chunk_id INTEGER NOT NULL,model_revision TEXT NOT NULL)"
    )
    progress = candidate.execute(
        "SELECT DISTINCT model_revision FROM bench364_progress"
    ).fetchall()
    if progress and {row[0] for row in progress} != {MODEL_REVISION}:
        raise RuntimeError(f"candidate progress belongs to another revision: {progress}")

    model = GigaEmbedder(Path(args.model), batch_size=args.batch_size)
    started = time.monotonic()
    try:
        reindex_kind(source, candidate, model, "file", args.batch_size)
        reindex_kind(source, candidate, model, "log", args.batch_size)
        expected_files = source.execute(
            "SELECT count(*) FROM file_chunks fc JOIN files f USING(file_id) WHERE f.project=?",
            (PROJECT,),
        ).fetchone()[0]
        expected_logs = source.execute(
            "SELECT count(*) FROM log_chunks lc JOIN logs_indexed li USING(log_id) "
            "WHERE li.project=?", (PROJECT,),
        ).fetchone()[0]
        actual_files = candidate.execute(
            "SELECT count(*) FROM vec_files WHERE project=?", (PROJECT,)
        ).fetchone()[0]
        actual_logs = candidate.execute(
            "SELECT count(*) FROM vec_logs WHERE project=?", (PROJECT,)
        ).fetchone()[0]
        if (actual_files, actual_logs) != (expected_files, expected_logs):
            raise RuntimeError(
                f"vector coverage mismatch: {(actual_files, actual_logs)} != "
                f"{(expected_files, expected_logs)}"
            )
    finally:
        source.close()
        candidate.close()

    result = score_arm(
        candidate_path,
        "giga_480m_hybrid",
        lambda texts: model.encode(texts, is_query=True),
    )
    result["provenance"] = {
        "source_corpus": str(source_path),
        "source_corpus_sha256": CORPUS_SHA256,
        "candidate_db": str(candidate_path),
        "queries": str(QUERY_PATH),
        "queries_sha256": QUERY_SHA256,
        "harness": str(HARNESS_PATH),
        "harness_sha256": HARNESS_SHA256,
        "model": model.metadata(),
        "reindex_and_score_elapsed_s": time.monotonic() - started,
        "cuda_max_memory_allocated_bytes": model.torch.cuda.max_memory_allocated(),
        "rss_max_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "vector_counts": {"files": actual_files, "logs": actual_logs},
    }
    write_json(Path(args.out), result)


def paired_t(candidate: list[float], baseline_values: list[float]) -> tuple[float, float]:
    if len(candidate) != len(baseline_values):
        raise RuntimeError(
            f"paired RR length mismatch: {len(candidate)} != {len(baseline_values)}"
        )
    diffs = [a - b for a, b in zip(candidate, baseline_values)]
    mean = statistics.fmean(diffs)
    if len(diffs) < 2:
        return mean, 0.0
    stdev = statistics.stdev(diffs)
    return mean, (mean / (stdev / math.sqrt(len(diffs))) if stdev else 0.0)


def split_half_noise(values: list[float]) -> dict:
    if len(values) % 2:
        raise RuntimeError("split-half requires an even query count")
    rng = random.Random(SPLIT_HALF_SEED)
    indices = list(range(len(values)))
    half = len(values) // 2
    gaps = []
    for _ in range(SPLIT_HALF_REPEATS):
        left = set(rng.sample(indices, half))
        a = statistics.fmean(values[i] for i in left)
        b = statistics.fmean(values[i] for i in indices if i not in left)
        gaps.append(abs(a - b))
    gaps.sort()
    return {
        "repeats": SPLIT_HALF_REPEATS,
        "seed": SPLIT_HALF_SEED,
        "median_abs_gap": statistics.median(gaps),
        "p90_abs_gap": gaps[math.ceil(0.90 * len(gaps)) - 1],
        "p95_abs_gap": gaps[math.ceil(0.95 * len(gaps)) - 1],
    }


def analyze(args: argparse.Namespace) -> None:
    baseline_result = json.loads(Path(args.baseline).read_text())
    giga_result = json.loads(Path(args.giga).read_text())
    base_rows = baseline_result["per_query"]
    giga_rows = giga_result["per_query"]
    if len(base_rows) != len(giga_rows) or len(base_rows) != 28:
        raise RuntimeError(
            f"paired row count mismatch: baseline={len(base_rows)}, giga={len(giga_rows)}"
        )
    for base_row, giga_row in zip(base_rows, giga_rows):
        for field in ("index", "q", "gold"):
            if base_row[field] != giga_row[field]:
                raise RuntimeError(
                    f"paired row identity mismatch at index={base_row['index']}: {field}"
                )
    bp = baseline_result["provenance"]
    gp = giga_result["provenance"]
    expected_pairs = (
        (bp["corpus_sha256"], gp["source_corpus_sha256"], CORPUS_SHA256, "corpus"),
        (bp["queries_sha256"], gp["queries_sha256"], QUERY_SHA256, "queries"),
        (bp["harness_sha256"], gp["harness_sha256"], HARNESS_SHA256, "harness"),
    )
    for baseline_hash, giga_hash, expected_hash, label in expected_pairs:
        if baseline_hash != giga_hash or baseline_hash != expected_hash:
            raise RuntimeError(
                f"paired {label} provenance mismatch: {baseline_hash}, {giga_hash}"
            )
    if bp["model_onnx_sha256"] != BASELINE_ONNX_SHA256:
        raise RuntimeError("baseline model provenance mismatch")
    if gp["model"]["revision"] != MODEL_REVISION:
        raise RuntimeError("Giga model provenance mismatch")
    base_rr = [row["rr"] for row in base_rows]
    giga_rr = [row["rr"] for row in giga_rows]
    delta, t_value = paired_t(giga_rr, base_rr)
    noise = split_half_noise(base_rr)
    verdict = (
        "меняем" if delta > noise["median_abs_gap"] and abs(t_value) > 2.052
        else "не меняем"
    )
    result = {
        "arms": [baseline_result["summary"], giga_result["summary"]],
        "comparison": {
            "delta_MRR": delta,
            "paired_t": t_value,
            "df": len(base_rr) - 1,
            "two_sided_t_threshold_0.05": 2.052,
            "split_half_noise": noise,
            "delta_exceeds_median_noise": abs(delta) > noise["median_abs_gap"],
            "verdict": verdict,
        },
        "baseline": baseline_result,
        "giga": giga_result,
    }
    write_json(Path(args.out), result)
    print(json.dumps(result["comparison"], ensure_ascii=False, indent=2))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("baseline")
    b.add_argument("--db", required=True)
    b.add_argument("--out", required=True)
    b.set_defaults(func=baseline)

    pr = sub.add_parser("probe")
    pr.add_argument("--model", required=True)
    pr.add_argument("--batch-size", type=int, default=4)
    pr.add_argument("--out", required=True)
    pr.set_defaults(func=probe)

    g = sub.add_parser("giga")
    g.add_argument("--source", required=True)
    g.add_argument("--candidate", required=True)
    g.add_argument("--model", required=True)
    g.add_argument("--batch-size", type=int, default=16)
    g.add_argument("--resume", action="store_true")
    g.add_argument("--out", required=True)
    g.set_defaults(func=giga)

    a = sub.add_parser("analyze")
    a.add_argument("--baseline", required=True)
    a.add_argument("--giga", required=True)
    a.add_argument("--out", required=True)
    a.set_defaults(func=analyze)
    return p


if __name__ == "__main__":
    args = parser().parse_args()
    args.func(args)
