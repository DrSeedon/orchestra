"""#57 — разбор сырых CPU-профилей: занятость главного потока по окнам, файлам и функциям.

Времена профиля (µs, свой ноль) переводятся в `performance.now()` страницы по якорю
`__now_at_stop`, снятому вплотную к `Profiler.stop`.

Запуск: .venv/bin/python docs/tasks/57/measurements/analyze.py b1 b2 b3
        .venv/bin/python docs/tasks/57/measurements/analyze.py --diff b1,b2,b3 t1,t2,t3
"""
import collections, json, pathlib, statistics, sys

D = pathlib.Path(__file__).parent
ARMS = ("cold", "warm1", "warm2")


def load(label, arm):
    prof = json.loads((D / f"raw-{arm}-{label}.cpuprofile").read_text())
    meta = json.loads((D / f"prof-{label}.json").read_text())[arm]
    nodes = {n["id"]: n for n in prof["nodes"]}
    parent = {}
    for n in prof["nodes"]:
        for c in n.get("children", []):
            parent[c] = n["id"]
    # времена сэмплов в шкале performance.now()
    t, times = prof["startTime"], []
    for d in prof["timeDeltas"]:
        t += d
        times.append(t)
    shift = meta["now_at_stop"] - prof["endTime"] / 1000.0
    times = [x / 1000.0 + shift for x in times]
    return prof, meta, nodes, parent, times


def label_of(nodes, nid):
    cf = nodes[nid]["callFrame"]
    fn = cf.get("functionName") or "(anonymous)"
    url = cf.get("url", "").split("?")[0].rsplit("/", 1)[-1]
    ln = cf.get("lineNumber", -1) + 1
    return fn, url, ln


def window(label, arm, lo, hi):
    """self-время по узлам в окне [lo, hi) мс от начала навигации."""
    prof, meta, nodes, parent, times = load(label, arm)
    self_ms = collections.Counter()
    incl_ms = collections.Counter()
    for i, sid in enumerate(prof["samples"]):
        ts = times[i]
        if ts < lo or ts >= hi:
            continue
        dt = prof["timeDeltas"][i] / 1000.0
        if dt > 60:          # длинный простой сэмплера — не работа потока
            dt = min(dt, 60)
        self_ms[sid] += dt
        seen, nid = set(), sid
        while nid is not None and nid not in seen:
            seen.add(nid)
            incl_ms[nid] += dt
            nid = parent.get(nid)
    return prof, meta, nodes, self_ms, incl_ms


def by_file(nodes, self_ms):
    agg = collections.Counter()
    for nid, ms in self_ms.items():
        fn, url, _ = label_of(nodes, nid)
        if fn in ("(idle)", "(program)", "(garbage collector)", "(root)"):
            agg[fn] += ms
        else:
            agg[url or "(native)"] += ms
    return agg


def by_fn(nodes, cnt, skip_meta=True):
    agg = collections.Counter()
    for nid, ms in cnt.items():
        fn, url, ln = label_of(nodes, nid)
        if skip_meta and fn in ("(idle)", "(root)"):
            continue
        agg[f"{fn} [{url}:{ln}]"] += ms
    return agg


def report(labels, arm, lo, hi, title):
    files, fns, incl, busy = [], [], [], []
    for lb in labels:
        prof, meta, nodes, s, inc = window(lb, arm, lo, hi)
        f = by_file(nodes, s)
        files.append(f)
        fns.append(by_fn(nodes, s))
        incl.append(by_fn(nodes, inc))
        busy.append(sum(v for k, v in f.items() if k != "(idle)"))
    med = lambda seq, k: statistics.median([c.get(k, 0.0) for c in seq])
    keys_f = sorted({k for c in files for k in c}, key=lambda k: -med(files, k))
    keys_n = sorted({k for c in fns for k in c}, key=lambda k: -med(fns, k))
    keys_i = sorted({k for c in incl for k in c}, key=lambda k: -med(incl, k))
    print(f"\n### {title} — {arm}, окно [{lo:.0f}, {hi:.0f}) мс, n={len(labels)}")
    print(f"занято главного потока: медиана {statistics.median(busy):.0f} мс  (прогоны: "
          + ", ".join(f"{b:.0f}" for b in busy) + ")")
    print("  self по файлам:")
    for k in keys_f[:10]:
        if k == "(idle)":
            continue
        print(f"   {med(files, k):7.1f}  {k}")
    print("  self по функциям:")
    for k in keys_n[:14]:
        if med(fns, k) < 3:
            break
        print(f"   {med(fns, k):7.1f}  {k}")
    print("  inclusive (с потомками):")
    for k in keys_i[:14]:
        if med(incl, k) < 10 or k.startswith("(program)"):
            continue
        print(f"   {med(incl, k):7.1f}  {k}")
    return statistics.median(busy)


def marks(labels, arm):
    out = collections.defaultdict(list)
    for lb in labels:
        m = json.loads((D / f"prof-{lb}.json").read_text())[arm]
        for k, v in m["marks"].items():
            out[k].append(v)
        out["dcl"].append(m["nav"]["domContentLoaded"])
        out["longtasks_ms"].append(sum(x["dur"] for x in m["longtasks"]))
        out["chatNodes"].append(m["chatNodes"])
    return {k: round(statistics.median(v), 1) for k, v in out.items()}


if __name__ == "__main__":
    if sys.argv[1] == "--diff":
        a, b = sys.argv[2].split(","), sys.argv[3].split(",")
        for arm in ARMS:
            ma, mb = marks(a, arm), marks(b, arm)
            print(f"\n=== {arm}: базовый {ma}\n           заглушка {mb}")
            for k in ("dcl", "chatFirst", "chat20", "longtasks_ms"):
                if k in ma and k in mb:
                    print(f"   {k:14s} {ma[k]:8.0f} → {mb[k]:8.0f}   ({mb[k]-ma[k]:+.0f})")
    else:
        labels = sys.argv[1:]
        for arm in ARMS:
            m = marks(labels, arm)
            print(f"\n{'='*70}\n{arm}: {m}")
            report(labels, arm, 0, m.get("chatFirst", 1e9), "до первой строки чата")
            report(labels, arm, m.get("chatFirst", 0), m.get("chat20", 1e9), "первая строка → 20 строк")
            report(labels, arm, 0, 6000, "первые 6 с целиком")
