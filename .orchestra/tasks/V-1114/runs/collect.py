"""collect.py <run_id>...  -> runs/raw/<key>.json (response+usage) ; then analyze.py scores."""
import json, sqlite3, sys
from pathlib import Path
RUNS = Path(__file__).parent; (RUNS/"raw").mkdir(exist_ok=True)
c = sqlite3.connect('file:/home/kesha/orchestra/data/orchestra.db?mode=ro', uri=True)
for rid in sys.argv[1:]:
    d = Path(f"/home/kesha/orchestra/data/workflow-runs/{rid}")
    spec = json.loads((d/"request.json").read_text())["tasks"]
    for l in (d/"journal.jsonl").read_text().splitlines():
        e = json.loads(l)
        if e.get("event") != "completed": continue
        key = e["label"]
        ck = e["call_key"]
        u = c.execute("select input_tokens,output_tokens,cache_read_tokens,cache_create_tokens,cost_usd,quota_seven_day_pct from turn_usage where event_id like ?", (f"wf:{rid}:{ck}%",)).fetchall()
        (RUNS/"raw"/f"{key}.json").write_text(json.dumps({"key": key, "run": rid, "ok": e.get("reason") == "completed", "cost_usd": e.get("cost_usd"), "usage_rows": u, "response": e["value"]["data"] if e.get("value") else None}, ensure_ascii=False, indent=1))
        print(key, e.get("reason"), e.get("cost_usd"), u)
