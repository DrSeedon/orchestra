"""Live read-only reconciliation: chart curve value (JS) vs gate line_limit (Python), Sol lane."""
import json, sqlite3, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from app.quota_gate import quota_policy, quota_policy_snapshot, window_progress, line_limit

DB = "file:/home/kesha/orchestra/data/orchestra.db?mode=ro"
con = sqlite3.connect(DB, uri=True)
cur = con.execute("select ts, provider_usage from usage_snapshots where ts>=? and ts<? order by id",
                  ("2026-10-23T00:00", "2026-10-28T00:00"))
rows, last = [], 0
raw = {}
for ts, pu in cur:
    t = datetime.fromisoformat(ts).timestamp()
    if t - last < 1800:
        continue
    last = t
    d = json.loads(pu).get("codex") or {}
    w = next((x for x in d.get("windows", []) if x.get("window_minutes") == 10080), None)
    if not w:
        continue
    rows.append({"ts": ts, "providers": {"codex": {"windows": [w]}}})
    raw[ts] = (t, w)
policy = quota_policy()
rule = quota_policy_snapshot(policy)
NODE = r"""
const src = process.argv[1];
const grab = re => new RegExp(re).exec(src)[0];
eval(['const _QL_RESET_HISTORY_HOURS[^\\n]*', 'const _QL_RESET_JUMP_MS[^\\n]*'].map(r => grab(r).replace('const ', 'var ')).join(';')
 + ';' + ['function _qlObservedWindowResets[\\s\\S]*?\\n}\\n','function _qlResetCycles[\\s\\S]*?\\n}\\n','function _qlHardStop[\\s\\S]*?\\n}\\n','function _qlLimitAt[\\s\\S]*?\\n}\\n'].map(grab).join(String.fromCharCode(10)));
const {rows, rule, probes} = JSON.parse(process.argv[2]);
const win = rows[rows.length-1].providers.codex.windows[0];
const events = _qlObservedWindowResets({rows, step_minutes: 30}, 'codex', win);
const duration = 10080*60000, reset = Date.parse(win.resets_at);
const cycles = _qlResetCycles(events, reset, duration, Date.now());
console.log(JSON.stringify(probes.map(ms => {
  const c = cycles.find(c => ms >= c.start && ms <= c.end);
  if (!c) return null;
  const prog = Math.max(0, Math.min(1, (ms - c.windowStart) / duration));
  return {prog, limit: _qlLimitAt(prog, rule, 'sol', 10080, c.windowStart)};
})));
"""
keys = list(raw)
probes = [keys[i] for i in range(len(keys)//10, len(keys), len(keys)//6)]
res = subprocess.run(["node", "-e", NODE, (ROOT/"app/static/js/quota-lines.js").read_text(),
                      json.dumps({"rows": rows, "rule": rule, "probes": [raw[k][0]*1000 for k in probes]})],
                     capture_output=True, text=True)
if res.returncode: sys.exit(res.stderr[:1500])
js = json.loads(res.stdout)
print("| snapshot (UTC) | resets_at then | gate progress | gate limit % | chart progress | chart limit % |")
print("|---|---|---|---|---|---|")
for k, j in zip(probes, js):
    t, w = raw[k]
    prog, started = window_progress(w, t)
    gate = line_limit(prog, "sol", policy, window_minutes=10080, window_start_at=started)
    print(f"| {k[:16]} | {w['resets_at']} | {prog:.4f} | {gate:.2f} | {j['prog']:.4f} | {j['limit']:.2f} |" if j else f"| {k[:16]} | - | no cycle | | | |")
