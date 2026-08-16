"""Reproducible warm-model benchmark for the #300 ONNX thread cap.

Run from the repository root with the server interpreter:
  env RAG_ONNX_THREADS=2 /home/kesha/orchestra/.venv/bin/python docs/tasks/300/measure_benchmark.py --benchmark
  env RAG_ONNX_THREADS=1 /home/kesha/orchestra/.venv/bin/python docs/tasks/300/measure_benchmark.py --benchmark
  env RAG_ONNX_THREADS=1 /home/kesha/orchestra/.venv/bin/python docs/tasks/300/measure_benchmark.py --quality
"""

import argparse
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from app import rag  # noqa: E402


def _cpu_ticks() -> int:
    fields = Path("/proc/self/stat").read_text().split()
    return int(fields[13]) + int(fields[14])


async def _heartbeat(stop: asyncio.Event, samples: list[float], loads: list[float]) -> None:
    previous = time.perf_counter()
    while not stop.is_set():
        await asyncio.sleep(0.01)
        now = time.perf_counter()
        samples.append((now - previous - 0.01) * 1000)
        loads.append(os.getloadavg()[0])
        previous = now


async def benchmark() -> None:
    embedder = rag._get_embedder()
    list(embedder.embed(["warm model before timed bounded workload"]))
    texts = ["bounded workload: glacier observatory telemetry and maintenance"]
    heartbeat_samples: list[float] = []
    load_samples: list[float] = []
    stop = asyncio.Event()
    heartbeat = asyncio.create_task(_heartbeat(stop, heartbeat_samples, load_samples))
    start_ticks = _cpu_ticks()
    start = time.perf_counter()
    loop = asyncio.get_running_loop()
    vectors = await loop.run_in_executor(
        None, lambda: list(embedder.embed(texts, batch_size=rag.EMBED_BATCH)
    ))
    elapsed = time.perf_counter() - start
    stop.set()
    await heartbeat
    hz = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
    cpu_pct = ((_cpu_ticks() - start_ticks) / hz) / elapsed * 100
    print({
        "threads": rag.RAG_ONNX_THREADS,
        "items": len(vectors),
        "elapsed_s": round(elapsed, 3),
        "cpu_avg_pct": round(cpu_pct, 1),
        "load_peak_1m": round(max(load_samples or [os.getloadavg()[0]]), 2),
        "heartbeat_max_ms": round(max(heartbeat_samples or [0.0]), 2),
        "quality_vector_dim": len(vectors[0]),
    })


def quality() -> None:
    with tempfile.TemporaryDirectory(prefix="rag300-") as tmp:
        db = rag.RagMemory(Path(tmp) / "vec.db")
        db.index_file("probe", "alpha.md", "glacier observatory stores ice-core telemetry and weather logs.")
        db.index_file("probe", "beta.md", "a cookbook lists pasta, tomatoes, basil, and olive oil.")
        rows = db.search("probe", "glacier observatory", limit=1)
        print({
            "indexed_chunks": db.conn.execute("SELECT COUNT(*) FROM file_chunks").fetchone()[0],
            "search_completed": bool(rows),
            "top_path": rows[0]["path"] if rows else None,
            "expected": "alpha.md",
        })
        assert rows and rows[0]["path"] == "alpha.md"
        db.conn.close()


parser = argparse.ArgumentParser()
parser.add_argument("--benchmark", action="store_true")
parser.add_argument("--quality", action="store_true")
args = parser.parse_args()
if args.benchmark == args.quality:
    parser.error("choose exactly one of --benchmark or --quality")
if args.benchmark:
    asyncio.run(benchmark())
else:
    quality()
