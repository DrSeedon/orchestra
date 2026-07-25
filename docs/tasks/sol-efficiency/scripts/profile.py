"""Sol-worker efficiency forensics. Reads /tmp/orch.db read-only, emits TSVs."""
import sqlite3, json, re, os, hashlib, collections, sys

OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/solan"
os.makedirs(OUT, exist_ok=True)
db = sqlite3.connect("file:/tmp/orch.db?mode=ro", uri=True)
db.row_factory = sqlite3.Row

sessions = {r["id"]: dict(r) for r in db.execute(
    "SELECT id,name,role,backend_type,model,is_orchestrator,created_at FROM sessions")}

TOOL_RE = re.compile(r"^([A-Za-z_][\w\-]*(?:__[\w\-]+)*):\s*(\{.*)$", re.S)
TURN_RE = re.compile(
    r"turn ended \(([^,]+), (\d+) turns, \$([\d.]+) turn, \$([\d.]+) ctx, "
    r"\$([\d.]+) session, \$([\d.]+) total(?: ctx:(\d+)%)?\)")


def parse_tool(content):
    m = TOOL_RE.match(content)
    if not m:
        return content.split(":")[0][:40], None
    name, raw = m.group(1), m.group(2)
    try:
        inp = json.loads(raw)
    except Exception:
        inp = None
    return name, inp


def is_image(c):
    return c.startswith("{'type': 'image'") or c.startswith('{"type": "image"')


rows = db.execute(
    "SELECT id,session_id,ts,type,content FROM logs ORDER BY session_id, id")

# ---- pass 1: per-session walk, FIFO pairing tool -> tool_result ----
calls = []          # one record per tool call
turns = []          # one record per turn ended
cur_sess, pending, turn_idx, turn_start_id = None, None, 0, 0

for r in rows:
    sid = r["session_id"]
    if sid != cur_sess:
        cur_sess, pending, turn_idx = sid, collections.deque(), 0
    s = sessions.get(sid, {})
    t, c = r["type"], r["content"]
    if t == "tool":
        name, inp = parse_tool(c)
        rec = dict(id=r["id"], sid=sid, sname=s.get("name"), role=s.get("role"),
                   backend=s.get("backend_type"), ts=r["ts"], turn=turn_idx,
                   tool=name, in_bytes=len(c), out_bytes=None, img=0,
                   target="", cmd="")
        if isinstance(inp, dict):
            if name == "Bash":
                rec["cmd"] = inp.get("command", "") or ""
                rec["target"] = (rec["cmd"] or "")[:0]
            elif name in ("Read", "Write", "Edit", "NotebookEdit"):
                rec["target"] = inp.get("file_path", "") or ""
            elif name in ("Grep", "Glob"):
                rec["target"] = (inp.get("pattern", "") or "")[:80]
            else:
                rec["target"] = ""
        calls.append(rec)
        pending.append(rec)
    elif t == "tool_result":
        rec = pending.popleft() if pending else None
        if rec is not None:
            rec["out_bytes"] = len(c)
            rec["img"] = 1 if is_image(c) else 0
    elif t == "status" and c.startswith("turn ended"):
        m = TURN_RE.search(c)
        if m:
            turns.append(dict(
                sid=sid, sname=s.get("name"), role=s.get("role"),
                backend=s.get("backend_type"), model=s.get("model"),
                ts=r["ts"], end_id=r["id"], turn=turn_idx,
                reason=m.group(1), inner=int(m.group(2)),
                cost=float(m.group(3)), ctx_cost=float(m.group(4)),
                ctx_pct=int(m.group(7)) if m.group(7) else None,
                start_id=turn_start_id))
        turn_idx += 1
        turn_start_id = r["id"]
    if t in ("user_message",):
        pass

# map calls -> owning turn (by end_id boundary within session)
by_sess_turns = collections.defaultdict(list)
for t in turns:
    by_sess_turns[t["sid"]].append(t)

# ---- write raw TSVs ----
with open(f"{OUT}/calls.tsv", "w") as f:
    f.write("id\tsid\tsname\trole\tbackend\tts\tturn\ttool\tin_bytes\tout_bytes\timg\ttarget\tcmd_sha\tcmd_len\tcmd\n")
    for c in calls:
        cmd = (c["cmd"] or "").replace("\t", " ").replace("\n", "\\n")
        sha = hashlib.sha1((c["cmd"] or "").encode()).hexdigest()[:10] if c["cmd"] else ""
        f.write("\t".join(str(x) for x in [
            c["id"], c["sid"][:8], c["sname"], c["role"], c["backend"], c["ts"],
            c["turn"], c["tool"], c["in_bytes"],
            c["out_bytes"] if c["out_bytes"] is not None else "", c["img"],
            (c["target"] or "").replace("\t", " "), sha, len(c["cmd"] or ""),
            cmd[:400]]) + "\n")

with open(f"{OUT}/turns.tsv", "w") as f:
    f.write("sid\tsname\trole\tbackend\tmodel\tts\tturn\treason\tinner\tcost\tctx_cost\tctx_pct\tstart_id\tend_id\n")
    for t in turns:
        f.write("\t".join(str(x) if x is not None else "" for x in [
            t["sid"][:8], t["sname"], t["role"], t["backend"], t["model"], t["ts"],
            t["turn"], t["reason"], t["inner"], t["cost"], t["ctx_cost"],
            t["ctx_pct"], t["start_id"], t["end_id"]]) + "\n")

print("calls", len(calls), "turns", len(turns))
print("unpaired(no result)", sum(1 for c in calls if c["out_bytes"] is None))
