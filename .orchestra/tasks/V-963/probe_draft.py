"""V-963 пробa: где рождается понижение — в черновике или в AUDIT/FINAL. Только черновик, uni hop4, 4 запуска."""
import sys, json, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tasks" / "V-961"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import stand
from concurrent.futures import ThreadPoolExecutor
segs, tails, pre0 = stand.load("uni")
prev = (stand.RUNS / "base" / "uni" / "hop3" / "summary.md").read_text()
rows = [dict(id=0, ts="", type="user_message", tool_name=None, tool_is_error=0, content=stand.preamble_text(prev, tails[3]))] + segs[3]
tr = stand.render(rows)
prompt = ("Below is the transcript of your session so far (tool calls/results truncated).\n\n"
          f"=== TRANSCRIPT ===\n{tr}\n=== END ===\n\n{stand._compact_prompt('uni')}")
out = Path(stand.BASE / "probe"); out.mkdir(exist_ok=True)
def one(i):
    t, _ = stand.claude(prompt, out / f"d{i}", label=f"probe:{i}")
    (out / f"draft{i}.md").write_text(t)
    toks = ["ФЛОКС-26", "mx9", "draft-6978", "omega-4", "#ops-95", "247"]
    return i, len(t), [x in t for x in toks]
with ThreadPoolExecutor(4) as ex:
    for r in ex.map(one, range(4)): print(r, flush=True)
