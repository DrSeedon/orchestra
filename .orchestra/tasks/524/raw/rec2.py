import json, collections, pathlib
root = pathlib.Path("/mnt/data/Projects/Python/orchestra")
rec = root / ".orchestra/kb/records/evidence"
paths = collections.Counter(); commits = collections.Counter(); ids=set()
for f in rec.glob("*.json"):
    d = json.loads(f.read_text())
    paths[d["source_path"]] += 1
    commits[d["git_commit"]] += 1
    ids.add(d["stable_id"])
print("records:", sum(paths.values()), "distinct source_path:", len(paths), "distinct stable_id:", len(ids))
print("copies-per-path histogram:", dict(collections.Counter(paths.values())))
print("distinct git_commit:", len(commits))
for c,n in commits.most_common(12): print(f"  {n:6d}  {c}")
m = json.loads((root/".orchestra/kb/manifest.json").read_text())
print()
print("manifest top-level keys:", list(m)[:20])
rows = m.get("records") or []
print("manifest rows:", len(rows))
if rows: print("row sample:", json.dumps(rows[0], ensure_ascii=False)[:600])
