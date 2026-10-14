"""Merge trial: worker branch B (replayed in sparse clone with own-dir policy + remedy so tree==C's tree)
vs current main. (1) update-branch: `git merge main` into B (as a worker resolving conflicts would);
(2) orchestrator-style `git merge --squash B` onto main. Each done in sparse clone and full clone; compare."""
import subprocess,re,sys,json,os,random
name,srcrepo,base_extra=sys.argv[1],sys.argv[2],sys.argv[3].split('|') if sys.argv[3] else []
N=int(sys.argv[4])
S='/tmp/v821/%s-sparse'%name; F='/tmp/v821/%s-full'%name
def g(d,*a,inp=None):
    return subprocess.run(['git','-C',d,'-c','core.quotepath=false','-c','user.name=t','-c','user.email=t@t',*a],capture_output=True,text=True,errors='replace',input=inp)
def src(*a): return subprocess.run(['git','-C',srcrepo,'-c','core.quotepath=false',*a],capture_output=True,text=True,errors='replace').stdout
base=['/*','!/.orchestra/tasks/']+base_extra
def setpat(extra): open(S+'/.git/info/sparse-checkout','w').write('\n'.join(base+extra)+'\n')
def clean(d): g(d,'reset','-q','--hard'); g(d,'clean','-fdxq')
head=src('rev-parse','main').strip()
log=src('log','--since=30 days ago','--no-merges','--format=%H %P\t%s','main').strip().split('\n')
cands=[]
for l in log:
    h,s=l.split('\t',1); hs=h.split()
    m=re.search(r'\bV-(\d+)',s) or re.search(r'#(\d+)',s)
    if not m or len(hs)!=2: continue
    dist=int(src('rev-list','--count',hs[1]+'..main').strip() or 0)
    if dist>=15: cands.append((hs[0],hs[1],m.group(1),dist))
random.seed(821); random.shuffle(cands)
res=[]
for C,P,n,dist in cands[:N]:
    rec={'C':C[:10],'task':'V-'+n,'behind':dist}
    # replay with B policy + remedy dirs from diff
    ch=src('diff-tree','-r','--no-renames','--raw',P,C).strip().split('\n')
    def top(p):
        q=p.split('/')
        if q[0]=='.orchestra' and len(q)>3 and q[1]=='tasks': return '/.orchestra/tasks/%s/'%q[2]
        if q[0] in('artifacts','resources') and len(q)>2: return '/%s/%s/'%(q[0],q[1])
    need=sorted({top(l.split('\t',1)[1]) for l in ch if l and top(l.split('\t',1)[1])})
    clean(S); setpat(need); g(S,'checkout','-q','-f','--detach',P)
    for l in ch:
        meta,p=l.split('\t',1); mm=meta.split(); st=mm[4][0]; nm=mm[1]; full=S+'/'+p
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
    g(S,'add','-A'); g(S,'add','-f','--pathspec-from-file=-','--pathspec-file-nul',inp='\0'.join(l.split('\t',1)[1] for l in ch if l and l.split()[4][0]!='D')+'\0'); cm=g(S,'commit','-q','-m','B'); B=g(S,'rev-parse','HEAD').stdout.strip()
    rec['B_tree_eq']=g(S,'rev-parse','HEAD^{tree}').stdout.strip()==src('rev-parse',C+'^{tree}').strip()
    # sparse for the merges = BASE cone only (worker's cone w/o remedy dirs) to be harsh? use base + own dirs of task
    g(F,'fetch','-q',S,B)  # same objects into full
    for side,d in(('sparse',S),('full',F)):
        r={}
        # (1) merge main into B
        clean(d)
        if side=='sparse': setpat(need)  # keep remedy dirs
        g(d,'checkout','-q','-f','--detach',B)
        m=g(d,'merge','--no-edit',head)
        un=sorted({x.split('\t')[1] for x in g(d,'ls-files','-u').stdout.strip().split('\n') if x})
        r['update_rc']=m.returncode; r['update_conflicts']=un
        if m.returncode==0: r['update_tree']=g(d,'rev-parse','HEAD^{tree}').stdout.strip()
        else: r['update_err']=(m.stdout+m.stderr)[:300]
        g(d,'merge','--abort')
        # (2) squash B onto main
        clean(d); g(d,'checkout','-q','-f','--detach',head)
        m=g(d,'merge','--squash',B)
        un=sorted({x.split('\t')[1] for x in g(d,'ls-files','-u').stdout.strip().split('\n') if x})
        r['squash_rc']=m.returncode; r['squash_conflicts']=un
        if m.returncode==0:
            r['squash_tree']=g(d,'write-tree').stdout.strip()
        else: r['squash_err']=(m.stdout+m.stderr)[:300]
        rec[side]=r
    s,f=rec['sparse'],rec['full']
    rec['same_update']=(s['update_rc']==f['update_rc'] and s['update_conflicts']==f['update_conflicts'] and s.get('update_tree')==f.get('update_tree'))
    rec['same_squash']=(s['squash_rc']==f['squash_rc'] and s['squash_conflicts']==f['squash_conflicts'] and s.get('squash_tree')==f.get('squash_tree'))
    print(json.dumps(rec,ensure_ascii=False),flush=True)
