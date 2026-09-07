from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts/recon429"))

from generation_432 import _result_outcome


def test_live_canary_pass_is_scheduler_success() -> None:
    assert _result_outcome(
        "canary",
        {
            "pass": True,
            "provider_status": "completed",
            "terminal_count": 1,
            "command_execution_events": 0,
            "mcp_events": 10,
            "sessions_before": 502,
            "sessions_after": 502,
        },
    ) == "success"
