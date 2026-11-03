"""Worst case for V-1179: rollout with no token_count row at all (full scan both ways)."""
import importlib.util, json, statistics, sys, time
from pathlib import Path


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod


def timed(fn, n=5):
    xs = []
    for _ in range(n):
        t = time.perf_counter(); fn(); xs.append(time.perf_counter() - t)
    return statistics.median(xs) * 1000


root = Path(sys.argv[1]); p = root / "no-token-count.jsonl"
with p.open("w") as fh:
    for i in range(8000):
        fh.write(json.dumps({"type": "response_item", "payload": {"output": "x" * 4096}}) + "\n")
for label, path in (("old", sys.argv[2]), ("new", sys.argv[3])):
    m = load(label, path)
    b = m.CodexBackend.__new__(m.CodexBackend); b._thread_id = "t"; b._rollout_path = p
    print(f"{label}: size={p.stat().st_size/1e6:.1f}MB send_path={timed(b._runtime_totals):.1f}ms "
          f"turn_end_path={timed(lambda: (b._runtime_totals(), b._runtime_context())):.1f}ms")
