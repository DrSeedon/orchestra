"""Replay each real past task commit C (parent P) in a sparse clone as a worker would:
checkout P, write C's file changes, `git add -A`, compare the tree with C's tree.
policy A = base cone; policy B = base cone + own dirs (task id derived at spawn)."""
import subprocess,re,sys,json,os,shutil,time
name,srcrepo,base_extra=sys.argv[1],sys.argv[2],sys.argv[3].split('|') if sys.argv[3] else []
limit=int(sys.argv[4]) if len(sys.argv)>4 else 10**9
S='/tmp/v821/%s-sparse'%name
def run(*a,inp=None,check=False,text=True):
    return subprocess.run(['git','-C',S,'-c','core.quotepath=false',*a],capture_output=True,text=text,errors='replace' if text else None,input=inp)
def src(*a): return subprocess.run(['git','-C',srcrepo,'-c','core.quotepath=false',*a],capture_output=True,text=True,errors='replace').stdout
base=['/*','!/.orchestra/tasks/']+base_extra
pf=S+'/.git/info/sparse-checkout'
def setpat(extra): open(pf,'w').write('\n'.join(base+extra)+'\n')
def reset():
    run('reset','-q','--hard'); run('clean','-fdxq')
log=src('log','--since=30 days ago','--no-merges','--format=%H %P\t%s','main').strip().split('\n')
units=[]
for l in log:
    h,s=l.split('\t',1); hs=h.split(); 
    m=re.search(r'\bV-(\d+)',s) or re.search(r'#(\d+)',s)
    if not m or len(hs)!=2: continue
    units.append((hs[0],hs[1],m.group(1),s[:70]))
units=units[:limit]
def own_patterns(n):
    return ['/.orchestra/tasks/V-%s/'%n,'/artifacts/V-%s/'%n,'/artifacts/task-V-%s/'%n,'/artifacts/V-%s-*/'%n,'/artifacts/task-V-%s-*/'%n]
def topdir(p):
    q=p.split('/')
    if q[0]=='.orchestra' and len(q)>3 and q[1]=='tasks': return '/.orchestra/tasks/%s/'%q[2]
    if q[0] in('artifacts','resources') and len(q)>2: return '/%s/%s/'%(q[0],q[1])
    return None
def replay(P,C,extra):
    reset(); setpat(extra); r=run('checkout','-q','-f','--detach',P)
    if r.returncode: return {'err':'checkout:'+r.stderr[:200]}
    ch=src('diff-tree','-r','--no-renames','--raw',P,C).strip().split('\n')
    outside=set(); nfiles=0
    for l in ch:
        if not l: continue
        meta,p=l.split('\t',1); nfiles+=1; mm=meta.split(); st=mm[4][0]; nm=mm[1]
        full=S+'/'+p
        if st=='D':
            if os.path.exists(full): os.remove(full)
        else:
            os.makedirs(os.path.dirname(full),exist_ok=True)
            b=subprocess.run(['git','-C',srcrepo,'cat-file','blob',C+':'+p],capture_output=True).stdout
            if os.path.lexists(full): os.remove(full)
            if nm=='120000': os.symlink(b.decode(),full)
            else:
                open(full,'wb').write(b)
                if nm=='100755': os.chmod(full,0o755)
    a=run('add','-A')
    paths=[l.split('\t',1)[1] for l in ch if l and l.split()[4][0]!='D']
    if paths: run('add','-f','--pathspec-from-file=-','--pathspec-file-nul',inp='\0'.join(paths)+'\0')
    t=run('write-tree').stdout.strip()
    ct=src('rev-parse',C+'^{tree}').strip()
    return {'rc':a.returncode,'stderr':a.stderr[:300],'eq':t==ct,'files':nfiles,
            'dirs':sorted({topdir(l.split('\t',1)[1]) for l in ch if l and topdir(l.split('\t',1)[1])})}
out=open('sim-%s.jsonl'%name,'w'); t0=time.time()
for i,(C,P,n,subj) in enumerate(units):
    rec={'C':C[:10],'task':'V-'+n,'subj':subj}
    for pol,extra in(('A',[]),('B',own_patterns(n))):
        r=replay(P,C,extra); rec[pol]=r
        if not r.get('err') and not r['eq']:
            # remedy: add the needed dirs, replay
            need=r['dirs']
            r2=replay(P,C,extra+need)
            rec[pol+'_remedy']={'dirs':need,'eq':r2.get('eq'),'rc':r2.get('rc'),'stderr':r2.get('stderr')}
            sizes=0
            for d in need:
                sizes+=sum(int(x.split()[3]) for x in src('ls-tree','-r','-l',P,d.strip('/')+'/').strip().split('\n') if x.strip())
            rec[pol+'_remedy']['MB']=round(sizes/1e6,1)
    out.write(json.dumps(rec,ensure_ascii=False)+'\n'); out.flush()
    if i%20==0: print(i,len(units),round(time.time()-t0),flush=True)
