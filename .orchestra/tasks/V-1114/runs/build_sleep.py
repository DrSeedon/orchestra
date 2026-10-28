"""Build the three sleep-call prompts (S1,S2,S3). Input: labelled memory + canonical layer. No bank, no gold."""
import json, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
V = ROOT/".orchestra/tasks/V-1114"
sys.path.insert(0, str(V))
import harness
P = (V/"prompts.md").read_text()
def prompt(tag):
    m = re.search(rf"## {tag} .*?```text\n(.*?)\n```", P, re.S); return m[1]
def labelled(text):
    out=[]
    for n,line in enumerate(text.splitlines(),1):
        out.append(f"[M{n:02d}] {line}" if line.startswith("- **") else line)
    return "\n".join(out)+"\n"
def canonical():
    parts=[]
    for rel in ["AGENTS.md",".orchestra/pipelines/default/prompts/modules/knowledge.md",".orchestra/pipelines/default/prompts/modules/model-routing.md"]:
        parts.append(f"### {rel}\n{(ROOT/rel).read_text()}")
    return "\n\n".join(parts)
MEM = labelled(harness.MEMORY.read_text())
CANON = canonical()
def sleep_prompt(tag):
    return (prompt(tag)+"\n\nYou have no need for tools; use none. Everything required is below.\n\n"
            "=== CANONICAL POLICY (authoritative, immutable; not part of the memory to rewrite) ===\n"+CANON+
            "\n=== PERSONAL MEMORY (blocks labelled [Mxx]; immutable archive) ===\n"+MEM+"=== END ===\n")
if __name__=="__main__":
    specs=[]
    for tag in ["S1","S2","S3"]:
        t={"prompt":sleep_prompt(tag),"model":"opus"}
        if tag=="S3":
            t["schema"]={"type":"object","properties":{"memory":{"type":"string"},"unresolved":{"type":"array","items":{"type":"string"}},"omitted_source_ids":{"type":"array","items":{"type":"string"}}},"required":["memory","unresolved","omitted_source_ids"]}
        specs.append(t)
    (V/"runs/sleep_tasks.json").write_text(json.dumps(specs,ensure_ascii=False))
    print([len(s["prompt"].encode()) for s in specs])
