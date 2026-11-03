from __future__ import annotations

import argparse
import importlib.util
import math
from pathlib import Path


def load(path: Path):
    candidate = path / "src" / "accounting.py"
    if not candidate.exists():
        candidate = path / "accounting.py"
    spec = importlib.util.spec_from_file_location("candidate_accounting", candidate)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True, type=Path)
    args = parser.parse_args()
    module = load(args.candidate)

    mixed = {
        "fresh_input_tokens": 10,
        "cache_read_tokens": 4,
        "cache_write_tokens": 3,
        "output_tokens": 5,
    }
    no_write = {**mixed, "cache_write_tokens": 0}
    assert math.isclose(module.estimate_cost("fixture-codex", mixed), 71.0)
    assert math.isclose(module.estimate_cost("fixture-codex", no_write), 62.0)
    try:
        module.estimate_cost("unpriced-fixture-model", mixed)
    except ValueError:
        pass
    else:
        raise AssertionError("unknown model must fail visibly")
    print("PASS: fresh/cache/write/output counted once; unknown model refused")


if __name__ == "__main__":
    main()
