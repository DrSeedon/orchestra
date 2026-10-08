#!/usr/bin/env python3
"""Move an SDK-launched provider CLI into the agent cgroup before exec."""

import os
import sys
from pathlib import Path


def main() -> None:
    target = os.environ["ORCHESTRA_AGENT_CLI"]
    cgroup = os.environ.get("ORCHESTRA_AGENT_CGROUP", "")
    if cgroup:
        (Path(cgroup) / "cgroup.procs").write_text(str(os.getpid()))
    os.execvp(target, [target, *sys.argv[1:]])


if __name__ == "__main__":
    main()
