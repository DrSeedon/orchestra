import json,sys,collections
for n in ['katya','seedon','orchestra']:
    R=[json.loads(l) for l in open('sim-%s.jsonl'%n)]
    print('==',n,'units',len(R),'tasks',len({r['task'] for r in R}))
    for pol in 'AB':
        ok=sum(1 for r in R if r[pol].get('eq')); err=sum(1 for r in R if r[pol].get('err'))
        rej=sum(1 for r in R if not r[pol].get('eq') and not r[pol].get('err') and r[pol]['rc']!=0)
        silent=sum(1 for r in R if not r[pol].get('eq') and not r[pol].get('err') and r[pol]['rc']==0)
        rem=[r[pol+'_remedy'] for r in R if pol+'_remedy' in r]
        remok=sum(1 for x in rem if x['eq'])
        mb=sorted(x['MB'] for x in rem)
        print(f' policy {pol}: ok-as-is {ok}, rejected(rc!=0) {rej}, SILENT-drop(rc=0,tree differs) {silent}, err {err}; remedy ok {remok}/{len(rem)}; remedy MB median {mb[len(mb)//2] if mb else 0} max {mb[-1] if mb else 0}')
    c=collections.Counter(d.split('/')[1]+'/'+d.split('/')[2] if d.startswith('/.orch') else d.split('/')[1] for r in R if 'B_remedy' in r for d in r['B_remedy']['dirs'])
    print(' B remedy dir kinds:',c.most_common(6))
    tasks_fail={r['task'] for r in R if not r['B'].get('eq')}
    print(' tasks needing remedy under B:',len(tasks_fail),'of',len({r['task'] for r in R}))
    ex=[(r['task'],r['B_remedy']['dirs'][:3],r['B_remedy']['MB']) for r in R if 'B_remedy' in r][:6]; print(' ex',ex)
    sil=[(r['task'],r['A']['files']) for r in R if not r['A'].get('eq') and r['A'].get('rc')==0][:5]; print(' silent ex',sil)
