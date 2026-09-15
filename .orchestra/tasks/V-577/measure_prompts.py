import sys, app.pipeline as P, app
ROLES = ["orchestrator", "sub-orchestrator", "worker", "full-cycle", "reducer"]
print("app module:", app.__file__)
root = P.PIPELINES_DIR / "default" / "prompts"
total = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
print(f"catalog_bytes\t{total}")
for r in ROLES:
    out = P.build_system_prompt("default", r)
    print(f"role\t{r}\t{len(out.encode())}")
