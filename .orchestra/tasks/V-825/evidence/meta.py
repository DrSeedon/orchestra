import os,subprocess,sys,time,re,json
H='/home/kesha'
C=[f'{H}/.cache/ms-playwright','/root/.cache/ms-playwright',f'{H}/.claude/projects',f'{H}/.codex/sessions',f'{H}/.orchestra/codex-home',
f'{H}/archive/comfy-monorepo.git',f'{H}/research-archive',f'{H}/orchestra-archive',f'{H}/projects/dnd-game-master.rsync-old',f'{H}/festival-assets',
f'{H}/festival-2026-results',f'{H}/komandor-data/raw',f'{H}/komandor-data/duckdb_tmp',f'{H}/readme-stand-V690',f'{H}/readme-stand-V686',f'{H}/.rembg',
f'{H}/orchestra/worktrees/bash-latency-20260905',f'{H}/orchestra/data/uploads',f'{H}/orchestra/data/models',f'{H}/orchestra/data/bench134',f'{H}/orchestra/data/backups',
f'{H}/apps/mirofish/backend/.venv',f'{H}/apps/mirofish/backend/.venv312',f'{H}/work/enisei-kiosk-build','/root/.local/share/Trash','/root/.npm/_cacache','/root/.cache/uv',
f'{H}/.local/state/orchestra/knowledge-v1',f'{H}/projects/seedon/.orchestra/tasks',f'{H}/projects/comfy-image-pipeline/.orchestra/tasks',f'{H}/.local/share/seedon/v111',
f'{H}/.local/share/orchestra-tts',f'{H}/.local/share/orchestra-manim',f'{H}/.local/share/Trash',f'{H}/.local/share/orchestra-pw-browsers',f'{H}/split',f'{H}/handoff-2026-09-21',
f'{H}/venvs/sentiment',f'{H}/deliverables',f'{H}/maxim-drive/backup-2026-09-24',f'{H}/bench219',f'{H}/bench-v637',f'{H}/salvage-tmp-20260906',f'{H}/ai-table-evidence',
f'{H}/katya-drive',f'{H}/.cache/huggingface',f'{H}/.cache/uv',f'{H}/.npm','/var/log/journal','/var/www/cog-balatro','/var/www/wall','/var/www/dl','/var/www/cog-slipways','/var/lib/photoserver/photos',
'/var/cache/orchestra-uv','/opt/orchestra/runtimes','/opt/kesha-bot/storage','/opt/ai-table-staging','/root/sensar-build-env-backup',f'{H}/projects/seedon/site',f'{H}/orchestra-scratch',f'{H}/design-refs',f'{H}/avito-research-data',f'{H}/v112-data',f'{H}/v111-data',f'{H}/jev-research',f'{H}/projects/comfy-image-pipeline/projects',f'{H}/katya-work',f'{H}/orchestra/.git',f'{H}/projects/seedon/.git',f'{H}/projects/comfy-image-pipeline/.git']
# open files snapshot
op=subprocess.run(['lsof','-w','-n','-F','n'],capture_output=True,text=True).stdout
openf=set(l[1:] for l in op.splitlines() if l.startswith('n/'))
cwds=set()
for p in os.listdir('/proc'):
    if p.isdigit():
        for k in('cwd',):
            try: cwds.add(os.readlink(f'/proc/{p}/{k}'))
            except: pass
cmd=''
for p in os.listdir('/proc'):
    if p.isdigit():
        try: cmd+=open(f'/proc/{p}/cmdline','rb').read().replace(b'\0',b' ').decode('utf8','replace')+'\n'
        except: pass
cfg=''
for d in ['/etc/systemd/system','/etc/cron.d','/var/spool/cron/crontabs',f'{H}/orchestra/.env','/etc/nginx']:
    r=subprocess.run(['grep','-rIl','--','X',d],capture_output=True,text=True) if False else None
def refs(path):
    out=[]
    for d in ['/etc/systemd/system','/etc/cron.d','/var/spool/cron/crontabs','/etc/nginx/sites-enabled','/etc/nginx/conf.d',f'{H}/orchestra/.env','/opt/kesha-bot/.env']:
        if os.path.exists(d):
            r=subprocess.run(['grep','-rIlF','--',path,d],capture_output=True,text=True)
            if r.stdout.strip(): out.append(r.stdout.strip().replace('\n',','))
    return out
res=[]
for p in C:
    if not os.path.exists(p): res.append((p,'MISSING'));continue
    sz=int(subprocess.run(['du','-sxB1',p],capture_output=True,text=True).stdout.split()[0])
    mm=0;am=0;n=0
    for dp,dn,fn in os.walk(p):
        for f in fn:
            try:
                st=os.lstat(os.path.join(dp,f)); n+=1
                mm=max(mm,st.st_mtime); am=max(am,st.st_atime)
            except: pass
    pre=p.rstrip('/')+'/'
    isopen=sum(1 for f in openf if f.startswith(pre))
    cw=sum(1 for c in cwds if c==p or c.startswith(pre))
    cm=cmd.count(p)
    res.append(dict(path=p,gb=round(sz/1e9,2),files=n,mtime=time.strftime('%F',time.localtime(mm)) if mm else '-',atime=time.strftime('%F',time.localtime(am)) if am else '-',open_files=isopen,cwd=cw,cmdline_refs=cm,cfg_refs=refs(p)))
json.dump(res,open('/tmp/v825-meta.json','w'),ensure_ascii=False,indent=0)
for r in sorted([x for x in res if isinstance(x,dict)],key=lambda x:-x['gb']): print(r['gb'],r['path'],'files',r['files'],'m',r['mtime'],'a',r['atime'],'open',r['open_files'],'cwd',r['cwd'],'cmd',r['cmdline_refs'],'cfg',r['cfg_refs'])
for r in res:
    if not isinstance(r,dict): print(r)
