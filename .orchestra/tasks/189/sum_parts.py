"""#189 — сложить результаты параллельных прогонов replay.py в одну картину."""
import json
import sys
from collections import Counter
from pathlib import Path

out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/replay189")
parts = sorted(out.glob("part-*.json"))
if not parts:
    raise SystemExit(f"нет результатов в {out}")

tot = {k: Counter() for k in ("delivered", "chars", "glued", "edits", "queue")}
fed = stuck = 0
bursts = []
for p in parts:
    d = json.loads(p.read_text())
    fed += d["fed"]
    stuck += d.get("stuck_in_bucket", 0)
    bursts += d.get("burst_ids", [])
    for key in tot:
        tot[key].update(d.get(key, {}))

msgs = sum(tot["delivered"].values())
chars = sum(tot["chars"].values())
print(f"пачек {len(bursts)}, строк журнала скормлено {fed}\n")
print(f"{'класс':22}{'доехало':>9}{'%':>5}{'знаков':>10}{'%':>5}")
for k in sorted(tot["delivered"], key=lambda k: -tot["delivered"][k]):
    n, c = tot["delivered"][k], tot["chars"][k]
    print(f"{k:22}{n:9}{n * 100 // msgs:5}{c:10}{c * 100 // max(chars, 1):5}")
print(f"{'ИТОГО':22}{msgs:9}{100:5}{chars:10}{100:5}")
print(f"\nсклеено чужих тел внутри доставленных сообщений: {sum(tot['glued'].values())}")
print(f"осталось тел в batch_bucket (уедут со следующим ходом): {stuck}")
print(f"правки уже стоящих сообщений: {dict(tot['edits'])}")
print(f"счётчики очереди: {dict(tot['queue'])}")
(out / "total.json").write_text(json.dumps(
    {"messages": msgs, "chars": chars, "fed": fed, "stuck": stuck,
     "delivered": dict(tot["delivered"]), "chars_by_class": dict(tot["chars"]),
     "glued": dict(tot["glued"]), "edits": dict(tot["edits"]),
     "queue": dict(tot["queue"]), "bursts": sorted(bursts)},
    ensure_ascii=False, indent=2))
print(f"\n→ {out / 'total.json'}")
