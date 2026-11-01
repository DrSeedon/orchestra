"""P3: loop guard (TurnGuard + rules) on synthetic traces. The 'judge' is a deterministic local stub (NO model call);
verdicts are therefore not evidence about real judge quality. Thresholds follow plugin/controller.py (gate_over_envelope=False,
gate_min_turns=max(gate_min_turns,min_turns))."""
import sys, json
sys.path.insert(0, "/tmp/v1143-run/repo")
from tokeneconomizer import loopguard
from tokeneconomizer.loopguard import TurnGuard
from tokeneconomizer.loopguard.rules import scaled_thresholds
thr = scaled_thresholds("default"); thr = dict(thr, gate_over_envelope=False, gate_min_turns=max(thr["gate_min_turns"], thr["min_turns"]))
class StubAsyncJudge:
    """start() computes a verdict immediately from `fn`; poll() hands it over on the next PostToolUse (as plugin/judge.py does)."""
    def __init__(self, fn): self.fn, self.res, self.starts, self.digests = fn, {}, 0, []
    def start(self, g, digest):
        self.starts += 1; self.digests.append(digest); job = f"j{self.starts}"; self.res[job] = self.fn(digest); return job
    def poll(self, g):
        p = g.judge_pending or {}
        return (True, self.res[p["id"]]) if p.get("id") in self.res else (False, None)
def run(name, calls, envelope, judge=None, budget=1):
    g = TurnGuard(turn_key=name); out = []
    for i, (tool, args, res, code) in enumerate(calls, 1):
        d = g.fold(tool, args, res, code, envelope=envelope, thr=thr, judge=judge, nudge_budget=budget)
        if d:
            out.append((i, d))
            if d[0] == "nudge": g.after_nudge()
    print(f"[{name}] calls={len(calls)} envelope={envelope} decisions={out} judge_starts={getattr(judge,'starts',None)} resolved_proxy={g.resolved_proxy()}")
    return g
FAIL = "E   AssertionError: assert 1 == 2\nFAILED tests/test_a.py::test_x - AssertionError"
def loop(n):  # edit one file, rerun the same failing test
    c = []
    for k in range(n // 2): c += [("Edit", {"file_path": "src/a.py"}, "", None), ("Bash", {"command": "python -m pytest tests/test_a.py -q"}, FAIL, 1)]
    return c
stuck_stub = lambda dg: {"stuck": True, "confidence": 0.9, "reason": "same failure", "_nudge": "STUB-REDIRECT", "_tokens": 0}
prod_stub  = lambda dg: {"stuck": False, "confidence": 0.9, "reason": "progress", "_tokens": 0}
print("== S0 no envelope (repository has <5 green turns): guard never acts, judge never started")
j = StubAsyncJudge(stuck_stub); run("no-envelope", loop(40), None, None)
print("\n== S1a genuine loop, SMALL envelope=6 (backstop = 2.5x = 15 turns < min_turns 20): the strict rule's backstop fires with NO judge call")
j = StubAsyncJudge(stuck_stub); run("true-loop-small-envelope", loop(60), 6.0, j)
print("\n== S1b genuine loop, envelope=14 (backstop 35): judge path; stub judge says stuck@0.9, nudge budget r=1")
j = StubAsyncJudge(stuck_stub); g = run("true-loop", loop(60), 14.0, j)
print("   first judge digest sent (verbatim):\n" + j.digests[0])
print("\n== S2 same loop but stub judge says productive: spared; judge re-asked with growing gap (5,10,15,20)")
j = StubAsyncJudge(prod_stub); run("loop-judge-productive", loop(80), 30.0, j); print("   judge starts:", j.starts)
print("\n== S3 changing failures + many edits (productive grind), stub judge productive")
c = []
for k in range(20): c += [("Edit", {"file_path": f"src/f{k%4}.py"}, "", None), ("Bash", {"command": "python -m pytest -q"}, f"E   AssertionError: case {k} differs in line {k*7}\nFAILED tests::t{k}", 1)]
j = StubAsyncJudge(prod_stub); run("changing-failures", c, 30.0, j); print("   judge starts:", j.starts)
print("\n== S4 FALSE-POSITIVE LIMIT: productive turn, tiny learned envelope (5), NO judge wired / judge paused -> deterministic rule+backstop only")
c = []
for k in range(10): c += [("Edit", {"file_path": f"src/f{k%3}.py"}, "", None), ("Bash", {"command": "python -m pytest tests -q"}, FAIL, 1)]
c += [("Edit", {"file_path": "src/f0.py"}, "", None), ("Bash", {"command": "python -m pytest tests -q"}, "5 passed in 0.4s", 0)]
run("productive-but-repetitive-red-then-green (ends GREEN at call 22)", c, 5.0, None)
print("   (same trace with envelope=20: )"); run("same-trace-envelope-20", c, 20.0, None)
print("\n== S5 no-progress that never fails visibly: 40 identical successful greps -> no error signal, nothing fires")
run("silent-spin", [("Grep", {"pattern": "foo"}, "src/a.py:1: foo", 0)] * 40, 6.0, StubAsyncJudge(stuck_stub))
print("\n== S6 exit-code hiding: pipe/|| after the test run (loopguard.turn.status_of_tests / runner_verdict)")
from tokeneconomizer.loopguard import turn as T
for cmd, out in [("npm test 2>&1 | tail -n 8", "not ok 1 - a\n# fail 1"), ("pytest -q || true", "1 failed, 4 passed in 0.5s"),
                 ("pytest -q; echo exit=$?", "4 passed in 0.5s\nexit=0"), ("pytest -q", "1 failed in 0.1s")]:
    print(f"   {cmd!r:34} status_of_tests={T.status_of_tests(cmd)!r} runner_verdict={T.runner_verdict(out)!r}")
print("\n== S7 what the judge/writer is sent: first 90 chars of every shell command (no secret masking)")
from tokeneconomizer.loopguard.state import SpiralState
st = SpiralState(); st.update("Bash", {"command": 'curl -H "Authorization: Bearer sk-FAKE-0123456789abcdef" https://internal.example/api && pytest'}, FAIL, True)
print(st.recent_digest())
print("\n== S8 persistence: TurnGuard.to_dict() JSON round-trip size (stored per hook call under session json)")
print(len(json.dumps(g.to_dict())), "bytes; events:", json.dumps(g.events[-2:])[:400])
