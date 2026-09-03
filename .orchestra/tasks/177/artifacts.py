"""Проза против кода по каждой задаче.

Для каждой docs/tasks/<id>/: байты research.md / plan.md / report.md / codex-review-*.md
и строки прод-кода в смерженных коммитах main с этим #id (из /tmp/diffsize.tsv).
"""
import glob
import os

sizes = {}
with open("/tmp/diffsize.tsv") as f:
    next(f)
    for line in f:
        p = line.rstrip("\n").split("\t")
        if len(p) < 10 or not p[2]:
            continue
        for tid in p[2].split(","):
            a = sizes.setdefault(tid, [0, 0, 0])
            a[0] += int(p[3]) + int(p[4])   # prod
            a[1] += int(p[5]) + int(p[6])   # tests
            a[2] += int(p[7]) + int(p[8])   # docs

print("task\tresearch_kb\tplan_kb\treport_kb\treview_kb\tn_reviews\tprod\ttests\tdocs_lines")
for d in sorted(glob.glob("/home/kesha/orchestra/docs/tasks/*/")):
    tid = d.rstrip("/").split("/")[-1]

    def kb(name):
        p = os.path.join(d, name)
        return round(os.path.getsize(p) / 1024, 1) if os.path.exists(p) else 0

    reviews = glob.glob(os.path.join(d, "codex-review*.md"))
    rv = round(sum(os.path.getsize(x) for x in reviews) / 1024, 1)
    prod, tests, docs = sizes.get(tid, (0, 0, 0))
    print(f"{tid}\t{kb('research.md')}\t{kb('plan.md')}\t{kb('report.md')}\t{rv}"
          f"\t{len(reviews)}\t{prod}\t{tests}\t{docs}")
