import json,collections
ev=json.load(open("/tmp/fcaudit/events.json"))
SOL={'polish-tg','research-codex-sleep','feat-usage-analytics','research-opus5','research-codex-cost','research-html-eff','investigate-restart','upgrade-claude5','feat-inscryption-ai','feat-wake-on-reset','sol-pilot','research-codex-cache','codex-limits-source'}
sol=collections.Counter(); cla=collections.Counter()
for ts,ag,tool,args in ev:
    if ag in SOL: sol[tool]+=1
    elif ag.startswith("MAIN:") and ("research-" in ag or "sensar" in ag): cla[tool]+=1
print("=== Sol/Codex full-cycle воркеры: какие тулы вообще есть ===")
for t,n in sol.most_common(20): print(f"  {n:5d} {t}")
print("\n=== Claude full-cycle воркеры ===")
for t,n in cla.most_common(14): print(f"  {n:5d} {t}")
print("\nAgent/Task у Sol:",sol.get("Agent",0)+sol.get("Task",0))
