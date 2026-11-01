"""Offline JavaScript behavior; a missing Node runner is an explicit failure."""
import shutil
import subprocess
from pathlib import Path


def test_compact_sse_refresh_and_unknown_context():
    node = shutil.which("node")
    assert node, "Node.js is required to run the offline compact UI regression"
    result = subprocess.run(
        [node, str(Path(__file__).with_suffix(".cjs"))],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
