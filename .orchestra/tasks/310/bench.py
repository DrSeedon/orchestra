#!/usr/bin/env python3
"""Frozen #310 adapter over the accepted #208 Fast benchmark harness."""

from __future__ import annotations

import hashlib
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "208" / "fast_bench.py"
EXPECTED_SOURCE_SHA256 = "4fd2e878e3f50081cd5f731ee75fdac01500204ef71dea2421585d0e8c396ed4"


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one harness anchor, got {count}: {old!r}")
    return text.replace(old, new)


raw = SOURCE.read_bytes()
actual = hashlib.sha256(raw).hexdigest()
if actual != EXPECTED_SOURCE_SHA256:
    raise RuntimeError(f"#208 harness drift: expected {EXPECTED_SOURCE_SHA256}, got {actual}")

source = raw.decode()
source = replace_once(source, 'MODEL = "gpt-5.6-sol"', 'MODEL = "gpt-5.6-luna"')
source = replace_once(
    source,
    'OUT = Path(__file__).with_name("fast-mode-results.json")',
    'OUT = Path(__file__).with_name("results.json")',
)
source = replace_once(
    source,
    'PRICING_SOURCE_COMMIT = "d38f8785a73df506ef13fdfe8c8bf9911c050c8e"',
    'PRICING_SOURCE_COMMIT = "f7fa7eb70296ce785f58fa83c9cdf3a93e48766b"',
)
source = replace_once(
    source,
    'PRICE_TABLE = {"input": 5.0, "cached": 0.5, "write": 6.25, "output": 30.0}',
    'PRICE_TABLE = {"input": 0.2, "cached": 0.02, "write": 0.25, "output": 1.2}',
)
source = replace_once(source, '}) or 0, 0.0024)', '}) or 0, 0.000096)')
source = replace_once(
    source,
    'f"208:{sequence}:{replicate}:{tier}"',
    'f"310:{sequence}:{replicate}:{tier}"',
)

namespace = {"__name__": "__main__", "__file__": str(HERE / "bench.py")}
exec(compile(source, str(SOURCE), "exec"), namespace)
