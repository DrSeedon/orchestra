import json,re,collections
ev=json.load(open("/tmp/fcaudit/events.json"))
FC=re.compile(r'(polish-tg|research-|feat-usage-analytics|upgrade-claude5|investigate-restart|sensar-|mobile-os-strategy|codex-limits|feat-inscryption|pricing-research|feat-ru-jobs|feat-outreach|audit-both|mass-job-hunter|sol-pilot|feat-wake|feat-rag)')
fc=[e for e in ev if FC.search(e[1])]
print("событий у full-cycle-подобных агентов:",len(fc))
tests={
 'точная команда из промпта UV_CACHE_DIR=/tmp/uv-cache': r'UV_CACHE_DIR=/tmp/uv-cache',
 'любой pytest': r'pytest',
 'pytest -x -q как в промпте': r'pytest -x -q|pytest -q -x',
 'запуск в /tmp (эксперименты)': r'/tmp/',
 'spawn_worker (фан-аут ресёрча)': r'spawn_worker',
 'встроенный Agent/Task': r'^(Agent|Task)$',
 'search_memory (модуль memory-search)': r'search_memory',
 'update_progress': r'update_progress',
 'report_bug': r'report_bug',
 'bg_create': r'bg_create',
 'git commit': r'git commit',
}
for label,pat in tests.items():
    p=re.compile(pat)
    n=sum(1 for ts,ag,tool,args in fc if p.search(tool) or p.search(args))
    agents=len(set(ag for ts,ag,tool,args in fc if p.search(tool) or p.search(args)))
    print(f"  {label:46s} вызовов={n:5d}  агентов={agents}")
