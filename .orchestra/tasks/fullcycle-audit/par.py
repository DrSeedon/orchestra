import json,re,collections
ev=json.load(open("/tmp/fcaudit/events.json"))
FC=re.compile(r'(polish-tg|research-|feat-usage-analytics|upgrade-claude5|investigate-restart|sensar-|mobile-os-strategy|codex-limits|feat-inscryption|pricing-research|feat-ru-jobs|feat-outreach|audit-both|mass-job-hunter|sol-pilot|feat-wake|feat-rag)')
sw=collections.Counter(); ag_t=collections.Counter()
for ts,agn,tool,args in ev:
    if not FC.search(agn): continue
    if tool=="mcp__orchestra__spawn_worker": sw[agn]+=1
    if tool in ("Agent","Task"): ag_t[agn]+=1
print("ТОЧНЫЕ вызовы тулов у full-cycle-агентов:")
print(f"  spawn_worker: {sum(sw.values())} вызовов, {len(sw)} агентов -> {dict(sw)}")
print(f"  built-in Agent: {sum(ag_t.values())} вызовов, {len(ag_t)} агентов -> {dict(ag_t)}")
