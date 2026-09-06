import json, os, collections, pathlib
root = pathlib.Path("/mnt/data/Projects/Python/orchestra")
rec = root / ".orchestra/kb/records/evidence"
files = sorted(rec.glob("*.json"))
pref = collections.Counter(); rtype = collections.Counter(); sclass = collections.Counter()
status = collections.Counter(); scope = collections.Counter(); keys = collections.Counter()
missing = 0; present = 0; missing_pref = collections.Counter(); total_bytes = 0
present_bytes = 0
for f in files:
    total_bytes += f.stat().st_size
    d = json.loads(f.read_text())
    keys.update(d.keys())
    rtype[d.get("record_type")] += 1
    sclass[d.get("source_class")] += 1
    status[d.get("status")] += 1
    scope[d.get("source_scope")] += 1
    sp = str(d.get("source_path") or "")
    p = "/".join(sp.split("/")[:2])
    pref[p] += 1
    tgt = root / sp
    if sp and tgt.is_file():
        present += 1; present_bytes += tgt.stat().st_size
    else:
        missing += 1; missing_pref[p] += 1
print("total records:", len(files), "json bytes:", total_bytes)
print("keys seen:", dict(keys))
print("record_type:", dict(rtype))
print("source_class:", dict(sclass))
print("status:", dict(status))
print("source_scope:", dict(scope))
print()
print("source_path EXISTS on disk:", present, " MISSING:", missing)
print()
print("top-25 source_path prefixes (all):")
for k,v in pref.most_common(25): print(f"  {v:6d}  {k}")
print()
print("top-25 prefixes among MISSING:")
for k,v in missing_pref.most_common(25): print(f"  {v:6d}  {k}")
