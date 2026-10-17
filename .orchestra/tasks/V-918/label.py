"""V-918 step A: blind labeling of findings. python -I label.py <model>"""
import sys, os, json, re, random, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm
from concurrent.futures import ThreadPoolExecutor
R = "/home/kesha/orchestra"
def g(*a): return subprocess.run(["git", "-C", R, *a], capture_output=True, text=True, errors="replace").stdout
EX = [":(exclude).orchestra/tasks", ":(exclude).orchestra/kb", ":(exclude).orchestra/workers"]
S = {i["id"]: i for i in json.load(open("sample.json"))["items"]}
ids = sorted(f[4:-10] for f in os.listdir("raw") if f.startswith("raw/") or f.endswith(".review.md")) if False else sorted(f[:-10] for f in os.listdir("raw") if f.endswith(".review.md"))
if not os.path.exists("label_key.json"):
    sh = ids[:]; random.Random(918).shuffle(sh)
    json.dump({f"item-{n:02d}": r for n, r in enumerate(sh)}, open("label_key.json", "w"), indent=1)
key = json.load(open("label_key.json"))
PROTO = open("label_protocol.md").read()
def ctx(sha):
    base, head = sha + "^1", sha
    paths = [p for p in g("diff", "--name-only", f"{base}...{head}", "--", ".", *EX).split() if p]
    diff = g("diff", "-U20", f"{base}...{head}", "--", ".", *EX).splitlines()[:1500]
    log = list(reversed(g("log", "main", "--format=%h %ad %s", "--date=short", f"{head}..main", "--", *paths).splitlines()))[:40]
    out = ["## Diff reviewed (-U20, capped 1500 lines)"] + diff + ["", f"## Later commits on main touching these paths ({len(log)} shown, oldest first)"] + log + ["", "## Patches of first 8 later commits (restricted to touched paths, 150 lines each)"]
    for l in log[:8]:
        out += g("show", "--format=### %h %s", "-U5", l.split()[0], "--", *paths).splitlines()[:150]
    return "\n".join(out)[:90000]
out = f"label_{sys.argv[1]}.json"; res = json.load(open(out)) if os.path.exists(out) else {}
def one(item):
    if item in res and not res[item].startswith("ERR"): return
    rid = key[item]; base = rid.rsplit(".r", 1)[0]
    review = open(f"raw/{rid}.review.md").read()
    p = (PROTO.split("Steps for each item file:")[0].replace("You have NO shell", "You have no tools") +
         "\nSteps: 1) extract each distinct finding of the REVIEW below (ignore praise/summary; a pure 'confirm intent' question = question_only). "
         "2) judge each claim against the diff and the later history given below (a later fix of that spot is strong evidence for real; its absence is not proof of noise). "
         "3) label real|noise|preexisting|question_only; for real add importance high|low. Be skeptical both ways.\n"
         "Reply with ONLY JSON, no prose, no code fence: {\"findings\":[{\"claim\":\"short\",\"label\":\"real|noise|preexisting|question_only\",\"importance\":\"high|low|-\",\"evidence\":\"1-2 sentences\"}]} (empty list if no findings).\n\n"
         f"# REVIEW\n{review}\n\n# CONTEXT\n{ctx(S[base]['sha'])}")
    res[item] = llm.run(sys.argv[1], p).strip()
    json.dump(res, open(out, "w"), indent=1)
with ThreadPoolExecutor(5) as ex: list(ex.map(one, sorted(key)))
