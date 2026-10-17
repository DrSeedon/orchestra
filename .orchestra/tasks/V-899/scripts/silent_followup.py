import pickle,sqlite3,re,json,datetime,collections
res,sess,ars=pickle.load(open('/tmp/an/t2.pkl','rb'))
W=pickle.load(open('/tmp/an/W.pkl','rb'))
c=sqlite3.connect('file:/home/kesha/orchestra/data/orchestra.db?mode=ro',uri=True)
T=lambda s: datetime.datetime.fromisoformat(s).timestamp()
S=[r for r in W if r['cat']=='silent' and r['send']==0 and not r['bg'] and r['tools'] and not (r['trig'] and r['trig'][1] in ('compact',))]
print('silent-only, with tool work, no bg_create, not compact:',len(S))
pat=re.compile(r'молча|stalled|resume|idle|не отчит|не ответ|ты тут|статус\?|status\?|тихо|silen|не вижу (твоего|отчёт)|жду (от тебя|отчёт|ответ)|завис|встал|продолж(ай|и)\b',re.I)
hits=[];tot=0
for r in S:
    nxt=c.execute("select id,ts,origin,origin_detail,substr(content,1,400) from logs where session_id=? and type='user_message' and id>? order by id limit 1",(r['sid'],r['id'])).fetchone()
    if not nxt: continue
    try: sub=json.loads(nxt[3]).get('subtype','')
    except: sub=''
    if nxt[2]=='agent' and sub in('direct_message','http_send'):
        tot+=1
        g=T(nxt[1])-T(r['ts'])
        if pat.search(nxt[4]): hits.append((r,nxt,g))
print('followed by an agent direct message:',tot,'with re-ping wording:',len(hits))
for r,nxt,g in hits: print(r['ts'][:16],sess[r['sid']][0],'->gap %dmin'%(g/60),'|',nxt[4][:230].replace('\n',' '))
