import json,re,collections
ev=json.load(open("/tmp/fcaudit/events.json"))
# classify touch of docs/tasks/<id>/<file>
PAT=re.compile(r'docs/tasks/([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+\.md)')
READ_TOOLS={"Read","read_file","view_image","ViewImage"}
WRITE_TOOLS={"Write","Edit","NotebookEdit","apply_patch","MultiEdit","FileChange"}
touch=collections.defaultdict(list)
for ts,ag,tool,args in ev:
    for m in PAT.finditer(args):
        key=(m.group(1),m.group(2))
        if tool in READ_TOOLS: act="READ"
        elif tool in WRITE_TOOLS: act="WRITE"
        elif tool in ("Bash","shell","local_shell_call"):
            a=args
            # find the command substring near the match
            if re.search(r'\b(cat|sed -n|head|tail|less|bat|nl)\b[^"]{0,200}'+re.escape(m.group(1)+"/"+m.group(2)), a): act="BASH_READ"
            elif re.search(r'\b(grep|rg|ag)\b', a): act="GREP"
            elif re.search(r'\b(git add|git commit|git status|git diff|ls |find )', a): act="GIT/LS"
            elif re.search(r'(cat|tee|>|heredoc|EOF)', a): act="BASH_WRITE"
            else: act="BASH_OTHER"
        elif tool.startswith("mcp__orchestra__codex_review"): act="CODEX_TARGET"
        elif tool in ("Grep","grep","search_for_pattern","mcp__serena__search_for_pattern"): act="GREP"
        elif tool in ("Agent","Task"): act="SUBAGENT_MENTION"
        elif tool.startswith("mcp__orchestra__send_message") or tool=="send_message": act="MENTION_IN_MSG"
        else: act="OTHER:"+tool
        touch[key].append((ts,ag,act))

def summarize(fname):
    print(f"\n########## {fname} ##########")
    rows=[]
    for (tid,f),lst in sorted(touch.items()):
        if f!=fname: continue
        lst.sort()
        writers=[x for x in lst if x[2] in ("WRITE","BASH_WRITE")]
        reads=[x for x in lst if x[2] in ("READ","BASH_READ")]
        first_w=writers[0][0] if writers else None
        # reads by someone AFTER first write
        later=[x for x in reads if first_w and x[0]>first_w]
        by_other=[x for x in later if not writers or x[1]!=writers[0][1]]
        rows.append((tid,len(writers),len(reads),len(later),len(by_other),
                     sorted(set(x[1] for x in by_other))[:3]))
    tot=len(rows)
    print(f"{'task':32s} W  R  R_after  R_by_other  who")
    for r in rows: print(f"{r[0][:32]:32s} {r[1]:2d} {r[2]:2d}  {r[3]:5d}   {r[4]:6d}     {','.join(r[5])[:60]}")
    print(f"-- {tot} tasks; with any read-by-other-agent-after-write: {sum(1 for r in rows if r[4]>0)}")

for f in ["retro.md","report.md","plan.md","research.md"]:
    summarize(f)
