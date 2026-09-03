"""#220 E1-E3: does importlib.reload update LIVE objects and importer bindings?

Pass/fail fixed BEFORE the run:
  E1 PASS = live instance created before reload returns the NEW method value.
  E2 PASS = app.manager.AgentSession is app.session.AgentSession after reload.
  E3 PASS = a deferred (function-level) import returns the NEW class.
"""
import importlib, pathlib, shutil, subprocess, sys, os, time
sys.path.insert(0, "/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-hot-reload")
os.chdir("/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-hot-reload")

import app.session as S
import app.manager as M

SRC = pathlib.Path("app/session.py")
inst = S.AgentSession(id="x", name="n", scope="/tmp", cwd="/tmp")
OldClass = S.AgentSession
print("before: _display_status() ->", repr(inst._display_status()))
print("before: app.manager.AgentSession is app.session.AgentSession ->", M.AgentSession is S.AgentSession)

bak = SRC.with_suffix(".py.bak")
shutil.copy(SRC, bak)
try:
    txt = SRC.read_text()
    old = '    def _display_status(self) -> str:'
    assert txt.count(old) == 1, f"anchor count = {txt.count(old)}"
    txt = txt.replace(old, old + '\n        return "MUTATED-220"')
    SRC.write_text(txt)
    os.utime(SRC, None)
    time.sleep(1.1)                      # defeat (mtime,size) pyc granularity
    os.utime(SRC, None)
    importlib.invalidate_caches()
    S2 = importlib.reload(S)
    print("\n--- after importlib.reload(app.session) ---")
    print("E1 live instance ._display_status() ->", repr(inst._display_status()),
          "| PASS" if inst._display_status() == "MUTATED-220" else "| FAIL")
    print("   type(inst) is new class ->", type(inst) is S2.AgentSession)
    print("   isinstance(inst, new AgentSession) ->", isinstance(inst, S2.AgentSession))
    fresh = S2.AgentSession(id="y", name="n", scope="/tmp", cwd="/tmp")
    print("   fresh instance from reloaded module ->", repr(fresh._display_status()))
    print("E2 app.manager.AgentSession is app.session.AgentSession ->", M.AgentSession is S2.AgentSession,
          "| PASS" if M.AgentSession is S2.AgentSession else "| FAIL")
    print("   manager's binding still the OLD class ->", M.AgentSession is OldClass)
    # E3 deferred import
    def deferred():
        from app.session import AgentSession
        return AgentSession
    print("E3 deferred 'from app.session import AgentSession' is new ->", deferred() is S2.AgentSession,
          "| PASS" if deferred() is S2.AgentSession else "| FAIL")
finally:
    shutil.move(str(bak), str(SRC))
    os.utime(SRC, None)
    print("\nrollback: marker count in file =",
          subprocess.run(["grep","-c","MUTATED-220",str(SRC)],capture_output=True,text=True).stdout.strip())
