import sqlite3,json,re,collections
db=sqlite3.connect("file:/home/kesha/orchestra/data/orchestra.db?mode=ro",uri=True)
q="""select l.ts,l.session_id,s.name,l.content from logs l left join sessions s on s.id=l.session_id where l.type='tool' and l.tool_name='Bash' and (l.content like '%git checkout --%' or l.content like '%git restore%' or l.content like '%git reset --hard%' or l.content like '%git clean%' or l.content like '%git revert%' or l.content like '%git checkout HEAD%')"""
pat=re.compile(r'git (checkout (-q )?(HEAD )?(--|\S+ --)|restore|reset (-q )?--hard|clean|revert)[^;&|\n"]*')
C=collections.Counter();S=collections.defaultdict(set);ex=collections.defaultdict(list)
for ts,sid,name,c in db.execute(q):
    try: cmd=json.loads(c[c.index('{'):]).get('command','')
    except Exception: cmd=c
    for m in pat.finditer(cmd):
        t=m.group(0)
        if ' ' in cmd and re.search(r"(cat|printf|echo)\s.*<<",cmd[:m.start()]) and False: continue
        if 'reset' in t or 'clean' in t: k='hard-reset/clean'
        elif 'revert' in t: k='revert-commit'
        elif re.search(r'\.(png|jpg|gif|webm|mp4)\b|screenshot',t): k='binary/screenshot'
        elif '.orchestra/' in t: k='.orchestra artifacts'
        elif re.search(r'(app/|tests?/|\.py|\.js|\.css|\.md|\.sql)',t): k='source/doc file'
        elif t.rstrip().endswith('--') or t.strip().endswith('. '): k='whole tree'
        else: k='other'
        C[k]+=1;S[k].add(sid);ex[k].append((ts[:16],name,t[:120]))
        break
for k,v in C.most_common(): print(k,v,len(S[k]))
for k in ('source/doc file','hard-reset/clean','whole tree','revert-commit'):
    print("==",k)
    for e in ex[k][-6:]: print(e)
