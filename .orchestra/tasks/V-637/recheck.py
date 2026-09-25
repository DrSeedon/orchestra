"""Re-run the machine checks against the CURRENT stand state (after fixing the checker, not the stand)."""
import json, sys
from pathlib import Path
import stand_run
from scenarios import SCENARIOS
env = stand_run.Env(); env.py_before = {"проверка_лицензий.py"}
BASES = {"S5": 6, "S8": 9}
for sc in SCENARIOS:
    f = Path(sys.argv[1]) / f"{sc['id']}.row.json"
    if not f.exists(): continue
    row = json.loads(f.read_text()); env.final_text = row["final_text"]; env.task_base = BASES.get(sc["id"], 4)
    ok, detail = sc["check"](env)
    print(sc["id"], ok, detail[:200])
