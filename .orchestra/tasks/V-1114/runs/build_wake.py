"""Build wake tasks. usage: build_wake.py <repeat list e.g. 0,1,2> <block list e.g. 0,1,2,3> <arms csv|all> <out.json>
Randomisation (seed 1114): block partition, question order and A/B/C option order per call; maps saved in maps/."""
import json, random, re, sys, hashlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from build_sleep import ROOT, V, harness, prompt, MEM, CANON, labelled
RUNS = V/"runs"
ARMS = {"full/W0":("full","W0"),"full/W1":("full","W1"),"S1/W0":("S1","W0"),"S2/W0":("S2","W0"),"S2/W1":("S2","W1"),"S3/W1":("S3","W1")}
bank = json.loads((V/"bank.json").read_text()); byid = {c["id"]:c for c in bank}
rows = harness.blocks(harness.MEMORY.read_text())
rng = random.Random(1114)
facts = [c["id"] for c in bank if c["kind"]=="fact"]; beh = [c["id"] for c in bank if c["kind"]=="behavior"]
rng.shuffle(facts); rng.shuffle(beh)
BLOCKS = [facts[6*b:6*b+6]+beh[4*b:4*b+4] for b in range(4)]
def memory_text(src):
    if src == "full": return MEM
    return (RUNS/"sleep_frozen"/f"{src}.memory.txt").read_text()
def make(arm, rep, blk):
    src, w = ARMS[arm]; r = random.Random(f"1114|{arm}|{rep}|{blk}")
    ids = BLOCKS[blk][:]; r.shuffle(ids)
    qs, maps = [], {}
    for i in ids:
        c = byid[i]; keys = [k for k in c["options"] if k != "UNKNOWN"]; texts = [c["options"][k] for k in keys]
        perm = list(range(len(keys))); r.shuffle(perm)
        opts, m = {}, {}
        for newk, p in zip("ABC"[:len(keys)], perm):
            opts[newk] = texts[p]; m[newk] = keys[p]
        opts["UNKNOWN"] = c["options"]["UNKNOWN"]; m["UNKNOWN"] = "UNKNOWN"
        qs.append({"id": i, "question": c["question"], "options": opts}); maps[i] = m
    packet_ids = []
    if w == "W1":
        for q in qs:
            for b in harness.retrieve(q["question"], rows):
                if b not in packet_ids: packet_ids.append(b)
        packet_ids.sort()
    packet = "".join(f"[{b}] {rows[b]}\n" for b in packet_ids)
    body = ("=== CANONICAL POLICY ===\n"+CANON+"\n=== LOADED PERSONAL MEMORY ===\n"+memory_text(src)+"\n=== END MEMORY ===\n\n"
            +prompt(w)+"\n\nNo tools are needed or allowed; answer only from the text in this message.\n")
    if w == "W1": body += "\n=== RETRIEVED SOURCE PACKET (original memory blocks, labelled [Mxx]) ===\n"+packet+"=== END PACKET ===\n"
    body += ("\n=== QUESTIONS ===\n"+json.dumps(qs, ensure_ascii=False, indent=1)+
             "\n\nReturn {\"answers\":[{\"id\":..., \"choice\":\"A|B|C|UNKNOWN\", \"evidence_ids\":[\"Mxx\",...]}, ...]} with exactly one entry per question.")
    schema = {"type":"object","properties":{"answers":{"type":"array","items":{"type":"object","properties":{"id":{"type":"string"},"choice":{"type":"string"},"evidence_ids":{"type":"array","items":{"type":"string"}}},"required":["id","choice","evidence_ids"]}}},"required":["answers"]}
    key = f"{arm.replace('/','-')}_r{rep}_b{blk}"
    return {"prompt": body, "model":"opus","schema":schema,"task_id":key,"label":key}, {"key":key,"arm":arm,"rep":rep,"blk":blk,"maps":maps,"packet_ids":packet_ids,"bytes":len(body.encode())}
if __name__=="__main__":
    reps = [int(x) for x in sys.argv[1].split(",")]; blks = [int(x) for x in sys.argv[2].split(",")]
    arms = list(ARMS) if sys.argv[3]=="all" else sys.argv[3].split(",")
    jobs = [(a,r,b) for r in reps for b in blks for a in arms]; random.Random(f"order|{sys.argv[1:4]}").shuffle(jobs)
    tasks, meta = [], []
    for a,r,b in jobs:
        t,m = make(a,r,b); tasks.append(t); meta.append(m)
    Path(sys.argv[4]).write_text(json.dumps(tasks, ensure_ascii=False))
    (RUNS/"maps").mkdir(exist_ok=True)
    for m in meta: (RUNS/"maps"/f"{m['key']}.json").write_text(json.dumps(m, ensure_ascii=False, indent=1))
    (RUNS/"blocks.json").write_text(json.dumps(BLOCKS))
    print(len(tasks), [m["bytes"] for m in meta])
