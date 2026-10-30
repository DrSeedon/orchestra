"""P2: tool pruning evidence + protected tools + deny-list write/restore, Claude and Codex lanes. No model calls.
Replays the fold's decision (ToolingStage + fold.enough_evidence) over synthetic Claude transcripts, then
writes/restores deny lists in a throwaway git repo."""
import sys, os, tempfile, json, subprocess
sys.path.insert(0, "/tmp/v1143-run/repo"); sys.path.insert(0, "/tmp/v1143-run/repo/tests")
from tokeneconomizer.config import ToolingConfig
from tokeneconomizer.toolprune import ToolingStage
from tokeneconomizer.plugin.adapter import LiveAdapter, HIGH_RISK, HIGH_RISK_FACTOR
from tokeneconomizer.plugin import denylist, fold
from tokeneconomizer.plugin.store import Store
from tokeneconomizer.plugin import hosts
from fixtures import write_claude_transcript
tmp = tempfile.mkdtemp(prefix="p2-")
repo = os.path.join(tmp, "repo"); os.makedirs(repo)
subprocess.run(["git","init","-q",repo],check=True)
class Cfg: toolprune_min_sessions=2; toolprune_evidence=10; toolprune_sessions=5
CATALOG = {t:"" for t in ["Bash","Read","Edit","Workflow","NotebookEdit","CronCreate","AskUserQuestion","WebSearch","ScheduleWakeup","mcp__headroom__compress","mcp__acme__q"]}
adapter = LiveAdapter(hosts.ClaudeCode(), repo, catalog=CATALOG, protect=("mcp__headroom__*",))
prot = adapter.protected_tools()
print("protected checks:", {t:(t in prot) for t in ["Bash","AskUserQuestion","WebSearch","Workflow","NotebookEdit","mcp__headroom__compress","mcp__acme__q","CronCreate"]})
stage = ToolingStage(ToolingConfig(evidence=2),"claude","agent",adapter=adapter,repo="r",results_root=tmp,fresh=True)
stage._warned_no_catalog=True
streak_prompts={}
def session(i, calls, prompts):
    d=os.path.join(tmp,f"run{i}"); os.makedirs(d)
    write_claude_transcript(os.path.join(d,"transcript.jsonl"), calls)
    before=dict(stage.tool_unused_streaks); srow={}
    stage.after_task({"instance_id":f"s{i}"},{"untooled_excluded":[]},d,srow)
    for t,n in stage.tool_unused_streaks.items():
        if n==0: streak_prompts[t]=0
        elif n==before.get(t,0)+1: streak_prompts[t]=streak_prompts.get(t,0)+prompts
    raw=[t for t in stage.build_tools({"instance_id":f"after{i}"}, i+1) or []
         if fold.enough_evidence(stage.tool_unused_streaks.get(t,0), streak_prompts.get(t,0), Cfg, high_risk=t in HIGH_RISK)]
    return sorted(raw)
use=[("Bash",{"command":"ls"},"ok"),("Read",{"file_path":"a.py"},"x"),("Edit",{"file_path":"a.py"},"ok")]
print("\n== evidence thresholds: p=10 prompts across >=2 sessions, or 5 sessions; high-risk (NotebookEdit) x3")
for i in range(1,17):
    prompts = 6
    prop = session(i, use, prompts)
    if i in (1,2,3,4,5,6,7,15,16): print(f"session {i:2d} (prompts={prompts}) proposal={prop}")
print("\n== apply to Claude settings.local.json (a user-authored rule must survive)")
os.makedirs(os.path.join(repo,".claude"))
json.dump({"permissions":{"deny":["Bash(rm -rf:*)"],"allow":["Bash(ls)"]}}, open(os.path.join(repo,".claude","settings.local.json"),"w"))
st=Store(os.path.join(tmp,"st"))
added=denylist.apply(repo,["Workflow","CronCreate"],st,host="claude")
print("added:",added); print(open(os.path.join(repo,".claude","settings.local.json")).read())
print("restore one:", denylist.restore(repo,st,["Workflow"],host="claude"))
print(open(os.path.join(repo,".claude","settings.local.json")).read())
print("restore all:", denylist.restore(repo,st,host="claude"))
print(open(os.path.join(repo,".claude","settings.local.json")).read())
print("\n== Codex lane: capability toggles into .codex/config.toml (no `codex` on PATH => codex_config_error() is None, so Codex-side validation is NOT exercised here)")
print("which codex:", __import__("shutil").which("codex"))
print("CODEX_TOGGLES keys:", sorted(denylist.CODEX_TOGGLES))
st2=Store(os.path.join(tmp,"st2"))
print("apply:", denylist.apply(repo,["collaboration","goals","image_media","web"],st2,host="codex"))
print(open(os.path.join(repo,".codex","config.toml")).read())
print("git info/exclude:", open(os.path.join(repo,".git","info","exclude")).read().strip().splitlines()[-2:])
print("restore goals:", denylist.restore(repo,st2,["goals"],host="codex"))
print(open(os.path.join(repo,".codex","config.toml")).read())
print("restore all:", denylist.restore(repo,st2,host="codex"), "file exists after:", os.path.exists(os.path.join(repo,".codex","config.toml")))
print("\n== Codex: committed config.toml is refused")
os.makedirs(os.path.join(repo,".codex"),exist_ok=True); open(os.path.join(repo,".codex","config.toml"),"w").write('model="x"\n')
subprocess.run(["git","-C",repo,"add","-f",".codex/config.toml"],check=True)
try: denylist.apply(repo,["goals"],Store(os.path.join(tmp,"st3")),host="codex")
except RuntimeError as e: print("RuntimeError:", e)
print("\n== Codex trust check (user config in CODEX_HOME):", denylist.codex_project_trusted(repo, {"CODEX_HOME":os.path.join(tmp,"nohome")}))
