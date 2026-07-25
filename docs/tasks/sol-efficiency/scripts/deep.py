import csv, collections, re, statistics as st, json

C = list(csv.DictReader(open("/tmp/solan/calls.tsv"), delimiter="\t"))
for c in C:
    for k in ("in_bytes", "img", "cmd_len", "turn"):
        c[k] = int(c[k])
    c["out_bytes"] = int(c["out_bytes"]) if c["out_bytes"] else 0
    c["orch"] = c["role"] in ("orchestrator", "sub-orchestrator")

SOLW = [c for c in C if c["backend"] == "codex" and not c["orch"]]
CLAW = [c for c in C if c["backend"] == "claude" and not c["orch"]]

print("### A. Bash shape: zsh -lc wrapper prevalence & length")
for label, S in (("SOL", SOLW), ("CLAUDE", CLAW)):
    b = [c for c in S if c["tool"] == "Bash"]
    if not b: continue
    zsh = [c for c in b if "zsh -lc" in c["cmd"]]
    L = sorted(c["cmd_len"] for c in b)
    print(f"{label}: bash={len(b)} zsh-lc={len(zsh)} ({100*len(zsh)/len(b):.0f}%) "
          f"cmd_len med={L[len(L)//2]} p90={L[int(len(L)*.9)]} max={max(L)} "
          f"total_cmd_kB={sum(L)/1024:.0f}")
    # wrapper overhead: the literal '/usr/bin/zsh -lc ' + quoting
    print(f"   in_bytes total={sum(c['in_bytes'] for c in b)/1024:.0f}kB  "
          f"out med={sorted(c['out_bytes'] for c in b)[len(b)//2]} "
          f"p90={sorted(c['out_bytes'] for c in b)[int(len(b)*.9)]} "
          f"max={max(c['out_bytes'] for c in b)}")

print("\n### B. Sol bash: leading verb histogram (what is it actually running)")
def verbs(cmd):
    c = cmd
    c = re.sub(r"^/usr/bin/zsh -lc ['\"]?", "", c)
    c = re.sub(r"^(cd [^&;|]+(&&|;)\s*)+", "", c)
    toks = re.split(r"[\s]+", c.strip())
    v = toks[0] if toks else ""
    v = v.strip("'\"(){}")
    if v in ("python3", "python", "uv", "/home/maxim/polus/.venv/bin/python"): v = "python"
    if v.startswith("sqlite3"): v = "sqlite3"
    return v[:22]

for label, S in (("SOL", SOLW), ("CLAUDE", CLAW)):
    b = [c for c in S if c["tool"] == "Bash"]
    d = collections.Counter(verbs(c["cmd"]) for c in b)
    ob = collections.Counter()
    for c in b: ob[verbs(c["cmd"])] += c["out_bytes"]
    print(f"-- {label} (n={len(b)})")
    for k, n in d.most_common(14):
        print(f"   {k:24} {n:4}  {100*n/len(b):5.1f}%  out={ob[k]/1024:8.0f}kB")

print("\n### C. Duplicate work: identical command hashes within one session")
for label, S in (("SOL", SOLW), ("CLAUDE", CLAW)):
    b = [c for c in S if c["tool"] == "Bash" and c["cmd"]]
    per = collections.defaultdict(list)
    for c in b: per[(c["sname"], c["cmd_sha"])].append(c)
    dupcalls = sum(len(v) - 1 for v in per.values() if len(v) > 1)
    dupbytes = sum(sum(x["out_bytes"] for x in v[1:]) for v in per.values() if len(v) > 1)
    print(f"{label}: bash={len(b)} unique={len(per)} repeat_calls={dupcalls} "
          f"({100*dupcalls/max(len(b),1):.1f}%) repeat_out={dupbytes/1024:.0f}kB "
          f"({100*dupbytes/max(sum(c['out_bytes'] for c in b),1):.1f}% of bash out)")
    if label == "SOL":
        top = sorted((v for v in per.values() if len(v) > 1), key=lambda v: -sum(x["out_bytes"] for x in v[1:]))[:12]
        for v in top:
            print(f"   x{len(v):3} out_wasted={sum(x['out_bytes'] for x in v[1:])/1024:7.1f}kB "
                  f"[{v[0]['sname'][:22]}] {v[0]['cmd'][:110]}")

print("\n### D. Reorientation commands (git status/ls/pwd/cat/git diff/git log)")
REORIENT = re.compile(r"\b(git status|git branch|pwd|^ls\b|git log|git diff --stat|git rev-parse)")
for label, S in (("SOL", SOLW), ("CLAUDE", CLAW)):
    b = [c for c in S if c["tool"] == "Bash" and c["cmd"]]
    r = [c for c in b if REORIENT.search(c["cmd"])]
    print(f"{label}: reorient_calls={len(r)}/{len(b)} ({100*len(r)/max(len(b),1):.1f}%) "
          f"out={sum(c['out_bytes'] for c in r)/1024:.0f}kB in={sum(c['in_bytes'] for c in r)/1024:.0f}kB")

print("\n### E. Same-file re-reads within a session (Read tool + bash cat/sed)")
FILEGET = re.compile(r"\b(?:cat|sed -n|head|tail|less|bat)\s+(?:-[\w-]+\s+)*['\"]?([/\w.\-]+\.\w+)")
for label, S in (("SOL", SOLW), ("CLAUDE", CLAW)):
    per = collections.defaultdict(list)
    for c in S:
        if c["tool"] == "Read" and c["target"]:
            per[(c["sname"], c["target"])].append(c)
        elif c["tool"] == "Bash":
            for m in FILEGET.finditer(c["cmd"]):
                per[(c["sname"], m.group(1))].append(c)
    tot = sum(len(v) for v in per.values())
    rep = sum(len(v) - 1 for v in per.values() if len(v) > 1)
    repb = sum(sum(x["out_bytes"] for x in v[1:]) for v in per.values() if len(v) > 1)
    print(f"{label}: file-fetches={tot} distinct={len(per)} repeats={rep} "
          f"({100*rep/max(tot,1):.1f}%) repeat_bytes~={repb/1024:.0f}kB")
    top = sorted(per.items(), key=lambda kv: -len(kv[1]))[:8]
    for (sn, fp), v in top:
        if len(v) > 1:
            print(f"   x{len(v):3} [{sn[:20]}] {fp[-70:]}")

print("\n### F. FileChange (Sol's edit tool) input weight")
fc = [c for c in SOLW if c["tool"] == "FileChange"]
L = sorted(c["in_bytes"] for c in fc)
print(f"n={len(fc)} in_total={sum(L)/1024:.0f}kB med={L[len(L)//2]} p90={L[int(len(L)*.9)]} max={max(L)}")
oo = sorted(c["out_bytes"] for c in fc)
print(f"   out_total={sum(oo)/1024:.0f}kB med={oo[len(oo)//2]} p90={oo[int(len(oo)*.9)]} max={max(oo)}")
ed = [c for c in CLAW if c["tool"] in ("Edit", "Write")]
print(f"CLAUDE Edit+Write n={len(ed)} in={sum(c['in_bytes'] for c in ed)/1024:.0f}kB "
      f"out={sum(c['out_bytes'] for c in ed)/1024:.0f}kB")
