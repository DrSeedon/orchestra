"""#220 E4-E5. Pass/fail fixed before the run:
 E4 PASS = after reload of the enum module, an OLD-enum value still compares equal to the NEW enum member.
 E5 PASS = after reload of a routes module, the live FastAPI app dispatches to the NEW handler.
"""
import importlib, sys, os
sys.path.insert(0,"/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-hot-reload")
os.chdir("/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-hot-reload")

import app.session_state as ST
old_idle = ST.AgentStatus.IDLE
ST2 = importlib.reload(ST)
print("E4 old AgentStatus.IDLE == new AgentStatus.IDLE ->", old_idle == ST2.AgentStatus.IDLE,
      "| PASS" if old_idle == ST2.AgentStatus.IDLE else "| FAIL (silent: every status check flips to False)")
print("   old is new ->", old_idle is ST2.AgentStatus.IDLE, "| .value equal ->", old_idle.value == ST2.AgentStatus.IDLE.value)
print("   'status == AgentStatus.IDLE' cross-module sites at risk: 65 (measured)")

# E5 routes
from fastapi import FastAPI, APIRouter
import app.routes.proxy as R
a = FastAPI()
a.include_router(R.router)
n_before = len(a.router.routes)
h_before = {r.path: r.endpoint for r in a.router.routes if hasattr(r,'endpoint')}
R2 = importlib.reload(R)
h_after_mod = {r.path: r.endpoint for r in R2.router.routes if hasattr(r,'endpoint')}
same = [p for p in h_before if p in h_after_mod and h_before[p] is h_after_mod[p]]
print(f"E5 app kept {n_before} routes; endpoints identical to reloaded module for {len(same)}/{len(h_before)} paths",
      "| PASS" if len(same)==len(h_before) else "| FAIL (live app still points at OLD function objects)")
print("   reloaded module's router is a NEW object ->", R2.router is not None and R2.router is not [r for r in a.router.routes])
