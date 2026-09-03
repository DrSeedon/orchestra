import json,re,collections
ev=json.load(open("/tmp/fcaudit/events.json"))
SOL={'polish-tg','research-codex-sleep','feat-usage-analytics','research-opus5','research-codex-cost','research-html-eff','investigate-restart','upgrade-claude5','feat-inscryption-ai','feat-wake-on-reset','sol-pilot','research-codex-cache','codex-limits-source'}
WEB=re.compile(r'curl |wget |https?://|web_search|WebSearch',re.I)
n=collections.Counter(); ex=[]
for ts,ag,tool,args in ev:
    if ag not in SOL: continue
    if tool in ("exec_command","run","local_shell_call") and WEB.search(args):
        n[ag]+=1
        if len(ex)<8: ex.append((ag,args[:170]))
print("Sol-воркеры: shell-вызовы с признаками веб-доступа:",sum(n.values()))
for a,c in n.most_common(): print(f"  {a}: {c}")
print("\nпримеры:")
for a,s in ex: print(f"  [{a}] {s}")
# spawn_worker on sol side
sp=[e for e in ev if e[1] in SOL and 'spawn' in e[2].lower()]
print("\nspawn_worker у Sol full-cycle:",len(sp), collections.Counter(e[2] for e in sp))
