import re, app.pipeline as P
for r in ("orchestrator","sub-orchestrator","worker","full-cycle","reducer"):
    out = P.build_system_prompt("default", r)
    tags = re.findall(r"^<([a-z-]+)>$", out, re.M)
    dup = {t: tags.count(t) for t in set(tags) if tags.count(t) > 1}
    print(r, "->", dup)
