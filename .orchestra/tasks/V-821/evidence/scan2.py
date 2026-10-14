import subprocess,re,sys,json,collections,os
repo=sys.argv[1]; res=json.load(open(os.path.basename(repo)+'-scan.json'))
def g(*a): return subprocess.run(['git','-C',repo,'-c','core.quotepath=false',*a],capture_output=True,text=True,errors='replace').stdout
out=g('log','--since=30 days ago','--no-merges','--format=@@%s','--name-only','main')
own=collections.defaultdict(set)
for blk in out.split('@@')[1:]:
    L=blk.split('\n'); m=re.search(r'\bV-(\d+)',L[0]) or re.search(r'#(\d+)',L[0])
    if not m: continue
    t='V-'+m.group(1); n=m.group(1)
    for f in L[1:]:
        p=f.split('/')
        if p[0]=='artifacts' and len(p)>1:
            own[t].add('own' if re.search(r'(?<!\d)'+n+r'(?!\d)',p[1]) else 'foreign:'+p[1])
        if p[0]=='resources' and len(p)>1: own[t].add('res:'+p[1])
# report references
pat=re.compile(r'(?<![\w/.-])((?:artifacts|resources|research|reference|docs|ops|tools|site|pipeline|archive)/[\w.\-/а-яА-ЯёЁ ]*[\w.\-/а-яА-ЯёЁ])|(\.orchestra/tasks/V-\d+)')
refs=collections.defaultdict(lambda:collections.defaultdict(set))
for t in res:
    if t=='NOTASK': continue
    fl=g('ls-tree','-r','--name-only','main','.orchestra/tasks/'+t+'/').split('\n')
    for f in fl:
        if not f.endswith('.md'): continue
        txt=g('show','main:'+f)
        for m in pat.finditer(txt):
            p=m.group(1) or m.group(2)
            top=p.split('/')[0]
            if m.group(2) and p.split('/')[-1]!=t: refs[t]['foreign-task'].add(p)
            elif top in('artifacts',) :
                n=t[2:]; sub=p.split('/')[1] if '/' in p else ''
                (refs[t]['artifacts-own'] if re.search(r'(?<!\d)'+n+r'(?!\d)',sub) else refs[t]['artifacts-foreign']).add(p)
            elif m.group(1): refs[t][top].add(p)
summ=collections.Counter()
for t in res:
    if t=='NOTASK': continue
    for k in refs[t]: summ['ref:'+k]+=1
    c=res[t]['cls']
    a=own[t]
    if any(x=='own' for x in a): summ['commit:artifacts-own']+=1
    if any(x.startswith('foreign:') for x in a): summ['commit:artifacts-foreign']+=1
    if any(x.startswith('res:') for x in a): summ['commit:resources']+=1
    if 'foreign-task' in c: summ['commit:foreign-task']+=1
    # needs anything outside own cone
    summ['has-report']+= 1 if refs[t] or True else 0
print(repo, 'tasks',len(res)-1); [print(' ',k,v) for k,v in sorted(summ.items())]
json.dump({t:{k:sorted(v) for k,v in d.items()} for t,d in refs.items()},open(os.path.basename(repo)+'-refs.json','w'),indent=1,ensure_ascii=False)
json.dump({t:sorted(v) for t,v in own.items()},open(os.path.basename(repo)+'-own.json','w'),indent=1,ensure_ascii=False)
