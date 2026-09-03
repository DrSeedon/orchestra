"""#220 E6: can a live FastAPI app swap a router module's handlers without restart?
Pass/fail fixed before the run:
  E6 PASS = after reload+re-include, an HTTP request to the path returns the NEW handler's body,
            AND the module-level singleton (deps.manager) is the SAME object as before.
"""
import importlib, pathlib, shutil, os, sys, time
sys.path.insert(0,"/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-hot-reload")
os.chdir("/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-hot-reload")
from fastapi import FastAPI
from fastapi.testclient import TestClient
import app.deps as D
import app.routes.proxy as R

mgr_before = D.manager
a = FastAPI(); a.include_router(R.router)
c = TestClient(a)
paths = sorted({r.path for r in a.router.routes if hasattr(r,'endpoint')})
print("routes:", paths)
probe = "/api/proxy/list"
print("before:", c.get(probe).status_code)

SRC = pathlib.Path("app/routes/proxy.py"); bak = SRC.with_suffix(".py.bak")
shutil.copy(SRC, bak)
try:
    t = SRC.read_text()
    anchor = 'async def proxy_list():'
    assert t.count(anchor) == 1, t.count(anchor)
    i = t.index(anchor); j = t.index('\n', i)
    body_start = t.index('\n', j+1)
    t = t[:j+1] + '    return {"MUTATED_220": True}\n' + t[j+1:]
    SRC.write_text(t); os.utime(SRC, None); time.sleep(1.1); os.utime(SRC, None)
    importlib.invalidate_caches()
    R2 = importlib.reload(R)
    # hot-swap: drop old routes of this module, re-include the reloaded router
    old_paths = {r.path for r in R2.router.routes}
    a.router.routes = [r for r in a.router.routes if getattr(r,'path',None) not in old_paths]
    a.include_router(R2.router)
    r = c.get(probe)
    body = r.json()
    print("after swap:", r.status_code, str(body)[:80])
    print("E6 handler swapped ->", body.get("MUTATED_220") is True,
          "| PASS" if body.get("MUTATED_220") is True else "| FAIL")
    print("   deps.manager identity preserved ->", D.manager is mgr_before)
    print("   app.deps was NOT reloaded, its singleton survived ->", importlib.import_module('app.deps').manager is mgr_before)
finally:
    shutil.move(str(bak), str(SRC)); os.utime(SRC, None)
    import subprocess
    print("rollback marker count:", subprocess.run(["grep","-c","MUTATED_220",str(SRC)],capture_output=True,text=True).stdout.strip())
