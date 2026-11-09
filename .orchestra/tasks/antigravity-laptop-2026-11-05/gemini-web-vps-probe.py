"""VPS one-shot receiver: authorized web cookies are consumed from stdin only."""
import asyncio
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import resource
import sys

ROOT = Path(__file__).resolve().parent


def main():
    os.nice(10)
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    Path("/proc/self/oom_score_adj").write_text("1000")
    ctypes.CDLL(None).prctl(4, 0, 0, 0, 0)
    spec = importlib.util.spec_from_file_location("web_pilot", ROOT / "pilot.py")
    pilot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pilot)
    try:
        incoming = json.load(sys.stdin)
        cookies = incoming.pop("cookies")
        if set(cookies) != set(pilot.COOKIE_NAMES):
            raise ValueError("unexpected authentication material")
        asyncio.run(asyncio.wait_for(
            pilot.check_web(cookies, None, incoming["expected_email"], True), timeout=110,
        ))
    except Exception as error:
        pilot.report(result="failed", error_type=type(error).__name__)
        return 1
    finally:
        (ROOT / "server-result.json").write_text(json.dumps(pilot.RESULT, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
