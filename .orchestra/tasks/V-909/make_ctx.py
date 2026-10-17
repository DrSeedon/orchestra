import json, subprocess, os, re
R = "/home/kesha/orchestra"
def g(*a):
    return subprocess.run(["git", "-C", R, *a], capture_output=True, text=True, errors="replace").stdout
EX = [":(exclude).orchestra/tasks", ":(exclude).orchestra/kb", ":(exclude).orchestra/workers"]
def ctx(name, base, head, outdir):
    paths = [p for p in g("diff", "--name-only", f"{base}...{head}", "--", ".", *EX).split() if p]
    diff = g("diff", "-U20", f"{base}...{head}", "--", ".", *EX).splitlines()
    out = [f"# Context for {name}\n\n## Diff reviewed (-U20, capped at 1500 lines)\n"] + diff[:1500]
    out.append("\n\n## Later history of the touched files on main (after this commit)\n")
    log = g("log", "main", "--format=%h %ad %s", "--date=short", f"{head}..main", "--", *paths).splitlines()
    out.append(f"{len(log)} later commits touch these paths; the first 40 (oldest first):")
    log = list(reversed(log))[:40]
    out += log
    out.append("\n## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)\n")
    for l in log[:8]:
        h = l.split()[0]
        p = g("show", "--format=### %h %s", "-U5", h, "--", *paths).splitlines()[:150]
        out += p
    open(f"{outdir}/{name}.ctx.md", "w").write("\n".join(out))
os.makedirs("label", exist_ok=True)
S = {i["id"]: i for i in json.load(open("sample.json"))["items"]}
for name, rid in json.load(open("label_key.json")).items():
    sha = S[rid]["sha"]
    ctx(name, sha + "^1", sha, "label")
rk = json.load(open("label_retro_key.json"))
for name in rk:
    t = open(f"label_retro/{name}.md").read()
    m = re.search(r"diff ([0-9a-f]{40})\.\.\.([0-9a-f]{40})", t)
    if m:
        ctx(name, m.group(1), m.group(2), "label_retro")
