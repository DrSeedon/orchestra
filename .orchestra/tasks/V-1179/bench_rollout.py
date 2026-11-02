"""Synthetic rollout benchmark for V-1179 (no real sessions, no network)."""
import json, random, statistics, sys, time
from pathlib import Path
from unittest.mock import patch

from app.backend_codex import CodexBackend, _read_rollout_context, _read_rollout_totals


def make(path: Path, turns: int, out_kb: int) -> None:
    rnd = random.Random(1179)
    total = 0
    with path.open("w") as fh:
        for i in range(turns):
            fh.write(json.dumps({"type": "response_item", "payload": {
                "type": "function_call_output",
                "output": "x" * (out_kb * 1024 + rnd.randint(0, 512))}}) + "\n")
            total += 1000 + i
            fh.write(json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": {
                "total_token_usage": {"input_tokens": total, "cached_input_tokens": total // 2,
                                      "output_tokens": i},
                "last_token_usage": {"input_tokens": 1000 + i, "cached_input_tokens": 500},
                "model_context_window": 258400}}}) + "\n")


def timed(fn, n=5):
    xs = []
    for _ in range(n):
        t = time.perf_counter(); fn(); xs.append(time.perf_counter() - t)
    return statistics.median(xs)


def main(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for turns, out_kb in ((2000, 4), (4000, 8)):
        p = root / f"rollout-{turns}.jsonl"
        make(p, turns, out_kb)
        b = CodexBackend.__new__(CodexBackend)
        b._thread_id = "t"; b._rollout_path = p
        size = p.stat().st_size / 1e6
        print(f"size={size:.1f}MB rows={2*turns} "
              f"context={timed(lambda: _read_rollout_context(p))*1000:.1f}ms "
              f"totals={timed(lambda: _read_rollout_totals(p))*1000:.1f}ms "
              f"send_path(_runtime_totals)={timed(b._runtime_totals)*1000:.1f}ms "
              f"turn_end_path={timed(lambda: (b._runtime_totals(), b._runtime_context()))*1000:.1f}ms")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
