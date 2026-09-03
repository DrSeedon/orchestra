import sqlite3, re, json, collections
c = sqlite3.connect('file:/home/kesha/orchestra/data/orchestra.db?mode=ro', uri=True)
W = "l.ts >= datetime('now','-14 days')"
NAME_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_.]*):\s')
RECON_T = {'Read','read_file','Grep','grep','search_tool','ToolSearch','Glob','LS','list_dir'}
WORK_T  = {'Edit','Write','NotebookEdit','search_replace','MultiEdit','write'}
EXT_T   = {'WebSearch','WebFetch','Skill'}
RECON_V = {'ls','find','tree','findmnt','grep','rg','ag','cat','head','tail','less','wc','sed',
           'stat','file','du','df','pwd','which','ps','env','command','awk','nl'}
WORK_V  = {'python','python3','uv','pytest','node','npm','make','pip','apt','mkdir','cp','mv',
           'trash','chmod','touch','tee','curl','wget','sha256sum','rm','ssh','sqlite3','diff','cat>'}
OVER_V  = {'git','systemctl','journalctl'}
NEUTRAL = {'echo','cd','set','export','source','true','sleep','timeout','for','do','done','if','then','fi','printf'}

def unwrap(cmd):
    """Strip runtime wrappers until the real command surfaces."""
    s = cmd.strip()
    for _ in range(8):
        s = s.strip()
        m = re.match(r'^(?:/usr/bin/env\s+)?(?:\S*/)?(?:bash|sh|zsh)\s+-[a-z]*c\s+(.*)$', s, re.S)
        if m:
            rest = m.group(1).strip()
            if rest and rest[0] in "'\"":
                q = rest[0]; end = rest.rfind(q)
                rest = rest[1:end] if end > 0 else rest[1:]
            s = rest; continue
        m = re.match(r'^timeout\s+\d+\S*\s+(.*)$', s, re.S)
        if m: s = m.group(1); continue
        m = re.match(r'^(?:sudo|nice(?:\s+-n\s*\d+)?)\s+(.*)$', s, re.S)
        if m: s = m.group(1); continue
        m = re.match(r'^env\s+((?:-\S+\s+|[A-Za-z_][A-Za-z0-9_]*=\S*\s+)+)(\S.*)$', s, re.S)
        if m: s = m.group(2); continue
        break
    return s

def segments(cmd):
    s = unwrap(cmd)
    parts = re.split(r'&&|\|\||[;|\n]', s)
    out = []
    for p in parts:
        p = p.strip()
        for _ in range(4):
            p = p.strip()
            m = re.match(r'^[A-Za-z_][A-Za-z0-9_]*=\S*\s+', p)
            if m: p = p[m.end():]; continue
            m = re.match(r'^(?:sudo|time)\s+', p)
            if m: p = p[m.end():]; continue
            break
        p = unwrap(p)
        m = re.match(r'^([A-Za-z0-9_./\-]+)', p)
        if m: out.append((m.group(1).split('/')[-1], p))
    return out

def cat_of_verb(v, seg):
    if v == 'git':
        if re.match(r'^git\s+grep', seg): return 'разведка'
        if re.match(r'^git\s+clone', seg): return 'работа'
        return 'служебное'
    if v in RECON_V: return 'разведка'
    if v in WORK_V:  return 'работа'
    if v in OVER_V:  return 'служебное'
    return None

def norm_name(name):
    return re.split(r'[ `]', name.strip(), 1)[0]

def classify(name, content):
    name = norm_name(name)
    if name in RECON_T: return 'разведка'
    if name in WORK_T:  return 'работа'
    if name in EXT_T:   return 'внешнее'
    if name.startswith('mcp__orchestra__'): return 'служебное'
    if name in ('Bash','run_terminal_command','use_tool'):
        try: cmd = json.loads(content.split(':',1)[1]).get('command') or ''
        except Exception: cmd = ''
        if not cmd: return 'прочее'
        cats = []
        for v, seg in segments(cmd):
            cc = cat_of_verb(v, seg)
            if cc: cats.append(cc)
        if not cats: return 'прочее'
        # priority: a command that changes state is work; else overhead; else recon
        if 'работа' in cats: return 'работа'
        if 'служебное' in cats: return 'служебное'
        return 'разведка'
    return 'прочее'

q = f'''select l.session_id, l.ts, l.tool_name, l.content, s.backend_type
        from logs l join sessions s on s.id=l.session_id
        where l.type='tool' and {W} order by l.session_id, l.ts'''
cat_all=collections.Counter(); cat_rt=collections.defaultdict(collections.Counter)
recon_only=0; bash_tot=0; multi_recon=0
for sid,ts,tn,content,bt in c.execute(q):
    content=content or ''
    m=NAME_RE.match(content); name=tn or (m.group(1) if m else '<UNRESOLVED>')
    if name=='FileChange': continue
    cat=classify(name,content); cat_all[cat]+=1; cat_rt[bt][cat]+=1
    if name in ('Bash','run_terminal_command'):
        bash_tot+=1
        try: cmd=json.loads(content.split(':',1)[1]).get('command') or ''
        except Exception: cmd=''
        vs={v for v,_ in segments(cmd)}
        if len(vs & RECON_V)>=2: multi_recon+=1
tot=sum(cat_all.values())
print(f'=== ИСПРАВЛЕННЫЙ прогон, знаменатель = {tot} обращений агента (FileChange исключён) ===')
for k,v in cat_all.most_common(): print(f'  {k:14} {v:6}  {100*v/tot:5.1f}%')
print()
for rt,cc in sorted(cat_rt.items(),key=lambda x:-sum(x[1].values())):
    s=sum(cc.values()); print(f'  {str(rt):8} n={s:6}  '+'  '.join(f'{k}={100*v/s:.1f}%' for k,v in cc.most_common()))
print()
print(f'  Bash-обращений {bash_tot}; с >=2 глаголами разведки в цепочке: {multi_recon} ({100*multi_recon/bash_tot:.1f}%)')
