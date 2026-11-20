"""Activate only after a clean replay and an independently checked counterexample."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .abi import Rejected, canonical, check_manifest
from .registry import digest


_REPLAY = """
import sys
sys.path.insert(0, sys.argv[1])
from app.skillcache.replay import main
main()
"""


def qualify(registry, scope, manifest):
    check_manifest(manifest, registry.catalog)
    from .pilots import MANIFESTS, OPERATIONS, TYPES

    # Only the reviewed ABI and plans have an independent fixture oracle in v1.
    if (manifest != MANIFESTS.get(manifest["skill"]) or registry.catalog.operations != OPERATIONS
            or registry.catalog.types != TYPES):
        raise Rejected("capsule has no reviewed qualification suite")
    version = registry.stage(scope, manifest)
    worktree = Path(__file__).resolve().parents[2]
    payload = canonical(manifest)
    proc = subprocess.run(
        [sys.executable, "-I", "-c", _REPLAY, str(worktree)],
        input=payload, text=True, capture_output=True, cwd="/",
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}, timeout=12, check=False,
    )
    if proc.returncode or len(proc.stdout) > 4096:
        raise Rejected("isolated qualification process failed")
    evidence = json.loads(proc.stdout)
    suite = evidence["suite"]
    checks = evidence["checks"]
    if set(checks) != {"baseline", "counterexample", "reject_stale"}:
        raise Rejected("qualification evidence incomplete")
    with registry.write() as conn:
        row = conn.execute("SELECT * FROM sc_capsule WHERE scope=? AND digest=?", (scope, version)).fetchone()
        for case, ok in checks.items():
            conn.execute(
                "INSERT OR REPLACE INTO sc_qualification VALUES (?,?,?,?,?,?,?)",
                (scope, version, case, suite, int(ok is True), f"fixture:{suite}:{case}", int(time.time())),
            )
        current = registry.catalog.dependencies(manifest, scope)
        if all(ok is True for ok in checks.values()) and digest([manifest, current]) == version:
            if row["status"] != "revoked":
                conn.execute(
                    """UPDATE sc_capsule SET status='stale'
                       WHERE scope=? AND skill=? AND intent=? AND status='active' AND digest<>?""",
                    (scope, manifest["skill"], manifest["intent"], version),
                )
                conn.execute("UPDATE sc_capsule SET status='active' WHERE scope=? AND digest=?", (scope, version))
                return version
    raise Rejected("replay or counterexample did not qualify")

