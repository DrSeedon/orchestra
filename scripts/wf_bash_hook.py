"""PreToolUse command hook for workflow Claude tasks: same Bash filter as managed workers (V-773).

`claude -p` cannot take the SDK's python hook, so the CLI runs this script per Bash call.
Any failure exits 2 (block): a crashed hook must never become an open shell.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        from app.backend_claude import _classify_bash_payload, _make_pretooluse_hooks

        hooks = _make_pretooluse_hooks(_classify_bash_payload, cwd=payload.get("cwd"))
        if not hooks:
            raise RuntimeError("Bash filter unavailable")
        out = asyncio.run(hooks[0].hooks[0](payload))
        sys.stdout.write(json.dumps(out))
        return 0
    except BaseException as exc:  # noqa: BLE001 - fail closed
        sys.stderr.write(f"Bash blocked: workflow filter failed ({type(exc).__name__})\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
