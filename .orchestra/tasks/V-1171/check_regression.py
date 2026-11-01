"""Offline, one-shot negative controls for V-1171; restore source after pytest.

Run sequentially, with no other tests using this checkout:
  uv run --frozen python .orchestra/tasks/V-1171/check_regression.py original-seam
  uv run --frozen python .orchestra/tasks/V-1171/check_regression.py skip-durable
"""

import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import uuid


ROOT = Path(__file__).resolve().parents[3]
TEST = "test_restart_context_drains_current_logs_before_signal_with_a_stale_session"
MUTATIONS = {
    "original-seam": (
        "tests/test_hot_apply.py",
        '        monkeypatch.setattr(system.manager, "sessions", {s.id: s for s in sessions})',
        '        monkeypatch.setattr(system, "_drain_sessions", lambda: list(sessions))',
    ),
    "skip-durable": (
        "app/routes/system.py",
        "    durable_state = await _drain_restart_durable_state()",
        '    durable_state = {"ok": True, "drained": 0}',
    ),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mutation", choices=MUTATIONS)
    args = parser.parse_args()
    relative, old, new = MUTATIONS[args.mutation]
    source = ROOT / relative
    original = source.read_bytes()
    text = original.decode()
    if text.count(old) != 1:
        raise SystemExit("mutation anchor must occur exactly once")
    uv = Path.home() / ".local/share/orchestra/tools/uv/0.11.28/bin/uv"
    environment = dict(os.environ)
    environment["PATH"] = str(uv.parent) + os.pathsep + environment.get("PATH", "")
    log = Path(__file__).parent / "private-evidence" / f"negative-{args.mutation}.log"
    log.parent.mkdir(exist_ok=True)
    basetemp = Path(tempfile.gettempdir()) / f"orchestra-v1171-{uuid.uuid4().hex}"
    try:
        source.write_text(text.replace(old, new))
        result = subprocess.run(
            [str(uv), "run", "--frozen", "python", "-m", "pytest",
             f"tests/test_hot_apply.py::{TEST}", "-q", "--timeout=30",
             f"--basetemp={basetemp}"],
            cwd=ROOT, env=environment, capture_output=True, text=True,
        )
    finally:
        source.write_bytes(original)
    output = result.stdout + result.stderr
    log.write_text(output)
    if result.returncode != 1 or "1 failed" not in output or "TimeoutError" not in output:
        raise SystemExit(f"{args.mutation}: expected behavioral failure was not observed; see {log.name}")
    print(f"{args.mutation}: expected regression failure observed (1 failed); source restored")


if __name__ == "__main__":
    main()
