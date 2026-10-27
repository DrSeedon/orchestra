"""Usage: run.py SCEN ARM REP  -> runs one Sonnet session, scores, writes JSON to private dir."""
import json, os, re, shutil, subprocess, sys, time
from pathlib import Path
import scenarios as SC

ROOT = Path(__file__).resolve().parents[4]  # worktree root
PRIV = Path("/home/kesha/orchestra/.orchestra/private/V-1106")
MOD = ROOT / ".orchestra/pipelines/default/prompts/modules"
cq = (MOD / "code-quality.md").read_text()
sf = (MOD / "safety.md").read_text()

THINK_OLD = cq[cq.index("**Think before coding.**"):cq.index("**Simplicity first.**")]
A_NEW = """**Think before coding.** Check discoverable facts and state bounded assumptions.
Prefer the simplest complete solution; challenge a faulty premise with evidence.
Before proposing extra complexity for a speculative race or security edge case
outside the approved outcome, name the concrete failure mode, the evidence for
its likelihood (or say it is unknown), and the implementation and maintenance cost.
Obtain approval only when the proposal changes scope, authority, material cost or
an external contract; otherwise continue within existing authority. Necessary
checks for authorization, data integrity and irreversible writes remain part of
a complete solution. This does not permit removing or weakening the safety
module's trust-boundary, data-loss, security or availability protections.

"""
B_ANCHOR = "- Explicit > implicit. No magic, no hidden side effects\n"
B_NEW = B_ANCHOR + """- Validate unknown input at the trust boundary that owns it and pass validated
  values inward. Do not repeat structural checks already guaranteed by a runtime
  schema or validating constructor unless a new trust boundary or invalidating
  mutation intervenes. A type annotation alone is not runtime validation.
  Shape validation does not establish authorization, data integrity or safety
  for a later operation: keep the checks at the operation they protect.
"""
C_NEW = """
**Documentation versus code.** When a repository's documentation and its existing code disagree, follow the conventions used in the existing code, and in your final reply point out each inconsistency you found between the documentation and the code. Explicit requirements from the owner, safety and security rules, and approved migrations take precedence over existing code patterns.
"""
PRE = ("You are a worker agent in a non-interactive run: nobody can answer questions during it. "
       "Do the task in the current directory, run what you need to verify it, and end with a short final report. "
       "If you believe an owner decision is required, say so in the final report.\n\n")

def system_prompt(arm):
    q = cq
    if arm == "A": q = q.replace(THINK_OLD, A_NEW)
    elif arm == "B": q = q.replace(B_ANCHOR, B_NEW)
    elif arm == "C": q = q.replace("</code-quality>", C_NEW + "</code-quality>")
    assert arm == "base" or q != cq
    return PRE + q + "\n" + sf

ASK = re.compile(r"(need(s)? (your|owner|the owner'?s)? ?(approval|decision|confirmation)|owner decision|before (I|we) (proceed|add|implement)|would you like|should I|do you want|please confirm|awaiting|let me know if you (want|would)|requires? (your |owner )?approval|want me to)", re.I)

def main(sid, arm, rep):
    s = SC.S[sid]
    out = PRIV / "runs" / f"{sid}__{arm}__{rep}"
    if (out / "result.json").exists(): return
    out.mkdir(parents=True, exist_ok=True)
    wd = PRIV / "work" / f"{sid}__{arm}__{rep}"
    if wd.exists(): shutil.rmtree(wd)
    wd.mkdir(parents=True)
    for n, c in s["files"].items(): (wd / n).write_text(c)
    g = lambda *a: subprocess.run(["git", *a], cwd=wd, capture_output=True, text=True)
    (wd / ".gitignore").write_text("__pycache__/\n*.pyc\n")
    g("init", "-q"); g("add", "-A"); g("-c", "user.email=a@b", "-c", "user.name=x", "commit", "-qm", "init")
    cfg = PRIV / "cfg"; cfg.mkdir(exist_ok=True)
    shutil.copy(os.path.expanduser("~/.claude/.credentials.json"), cfg / ".credentials.json")
    env = dict(os.environ, CLAUDE_CONFIG_DIR=str(cfg), CLAUDE_CODE_DISABLE_AUTO_MEMORY="1", DISABLE_AUTOUPDATER="1", PYTHONDONTWRITEBYTECODE="1")
    for k in list(env):
        if k.startswith(("ANTHROPIC", "CLAUDE_CODE_OAUTH")) : env.pop(k)
    cmd = ["claude", "-p", s["task"], "--model", "sonnet", "--effort", "medium", "--output-format", "json",
           "--append-system-prompt", system_prompt(arm), "--permission-mode", "bypassPermissions",
           "--tools", "Read,Write,Edit,Bash,Glob,Grep", "--disable-slash-commands", "--no-session-persistence",
           "--strict-mcp-config", "--max-budget-usd", "1.5"]
    t = time.time()
    try:
        p = subprocess.run(cmd, cwd=wd, env=env, capture_output=True, text=True, timeout=900)
        raw, err = p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        raw, err = "", "TIMEOUT"
    (out / "raw.json").write_text(raw); (out / "stderr.txt").write_text(err or "")
    try: j = json.loads(raw)
    except Exception: j = {}
    reply = j.get("result", "") or ""
    chk = s["check"](str(wd))
    diff = subprocess.run(["git", "diff", "HEAD"], cwd=wd, capture_output=True, text=True).stdout
    (out / "diff.patch").write_text(diff)
    u = j.get("usage", {})
    res = dict(scenario=sid, rule=s["rule"], kind=s["kind"], arm=arm, rep=rep, secs=round(time.time() - t),
               cost=j.get("total_cost_usd"), turns=j.get("num_turns"), is_error=j.get("is_error"),
               out_tokens=u.get("output_tokens"), cache_create=u.get("cache_creation_input_tokens"),
               asked_regex=bool(ASK.search(reply)), reported_discrepancy=SC.reported(reply),
               reply=reply[:1500], **chk)
    (out / "result.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(sid, arm, rep, "success=", res["success"], "cost=", res["cost"], "turns=", res["turns"])

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
