#!/usr/bin/env python3
"""Move an SDK-launched provider CLI into the agent cgroup before exec."""

import os
import sys
from pathlib import Path

if __package__:
    from .agent_cgroups import set_agent_oom_score_adj
else:
    from agent_cgroups import set_agent_oom_score_adj


def main() -> None:
    target = os.environ["ORCHESTRA_AGENT_CLI"]
    cgroup = os.environ.get("ORCHESTRA_AGENT_CGROUP", "")
    set_agent_oom_score_adj()
    if cgroup:
        (Path(cgroup) / "cgroup.procs").write_text(str(os.getpid()))
    elif os.environ.get("ORCHESTRA_AGENT_CGROUP_REQUIRED") == "1":
        raise RuntimeError("delegated agent cgroup is unavailable; refusing to launch provider CLI")
    os.execvp(target, [target, *sys.argv[1:]])


if __name__ == "__main__":
    main()
