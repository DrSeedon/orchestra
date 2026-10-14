import subprocess,re,sys,json,collections,os
repo,days=sys.argv[1],sys.argv[2]
def g(*a): return subprocess.run(['git','-C',repo,'-c','core.quotepath=false',*a],capture_output=True,text=True,errors='replace').stdout
out=g('log','--since=%s days ago'%days,'--no-merges','--format=@@%H\t%s','--name-only','main')
tasks=collections.defaultdict(lambda:{'files':set(),'commits':0})
notask={'files':set(),'commits':0}
for blk in out.split('@@')[1:]:
    lines=blk.split('\n'); h,s=lines[0].split('\t',1); files=[l for l in lines[1:] if l.strip()]
    m=re.search(r'\bV-(\d+)',s) or re.search(r'#(\d+)',s)
    t=('V-'+m.group(1)) if m else None
    d=tasks[t] if t else notask
    d['commits']+=1; d['files']|=set(files)
def cls(f,t):
    p=f.split('/')
    if p[0]=='artifacts': return 'artifacts'
    if p[0]=='resources': return 'resources'
    if p[0]=='.orchestra':
        if len(p)>2 and p[1]=='tasks':
            return 'own-task' if p[2]==t else 'foreign-task'
        return '.orchestra-other'
    return 'other:'+p[0]
res={}
for t,d in list(tasks.items())+[('NOTASK',notask)]:
    c=collections.Counter(cls(f,t) for f in d['files'])
    res[t]={'commits':d['commits'],'files':len(d['files']),'cls':dict(c)}
json.dump(res,open(os.path.basename(repo)+'-scan.json','w'),indent=1)
cnt=collections.Counter(); n=0
for t,r in res.items():
    if t=='NOTASK': continue
    n+=1
    for k in r['cls']: cnt[k]+=1
print(repo,'tasks',n,'notask commits',notask['commits'],'files',len(notask['files']))
for k,v in cnt.most_common(): print(' ',k,v)
nc=collections.Counter()
for f in notask['files']: nc[cls(f,None)]+=1
print(' NOTASK files:',nc.most_common(8))
