import sqlite3,pickle,json,re
D='/home/kesha/orchestra/data/orchestra.db'
c=sqlite3.connect(f'file:{D}?mode=ro',uri=True)
MARK='[[ORCHESTRA:SILENT_TURN]]'
sess={r[0]:r[1:] for r in c.execute("select id,name,scope,role,is_orchestrator,parent_name from sessions")}
cur=c.execute("""select session_id,id,ts,type,tool_name,
 case when type='text' and content=? then 1 else 0 end,
 case when type='status' and content like 'turn ended%' then 1 else 0 end,
 case when type='status' and content like 'turn ended (%' then substr(content,13,40) else '' end,
 origin, origin_detail, case when type='user_message' then substr(content,1,200) else '' end
 from logs where type in ('text','tool','status','user_message') order by session_id,id""",(MARK,))
def new(): return dict(send=0,bg=0,tools=0,text=0,sil=False,first=None,trig=None,lasttool=None)
st={};res=[]
for sid,i,ts,typ,tn,issil,isend,endinfo,orig,od,head in cur:
    s=st.setdefault(sid,new())
    if s['first'] is None: s['first']=ts
    if typ=='tool':
        s['tools']+=1
        if tn and tn.endswith('send_message'): s['send']+=1
        if tn and tn.endswith('bg_create'): s['bg']+=1
    elif typ=='text': s['text']+=1; s['sil']=bool(issil)
    elif typ=='user_message':
        if s['trig'] is None:
            try: sub=json.loads(od).get('subtype','')
            except Exception: sub=''
            try: snd=','.join(json.loads(od).get('senders',[]))
            except Exception: snd=''
            s['trig']=(orig,sub,snd,head)
    elif isend:
        res.append(dict(sid=sid,id=i,ts=ts,first=s['first'],send=s['send'],bg=s['bg'],tools=s['tools'],text=s['text'],sil=s['sil'],trig=s['trig'],end=endinfo))
        st[sid]=new()
ars=[]
for sid,i,ts,od,head in c.execute("select session_id,id,ts,origin_detail,substr(content,1,120) from logs where type='user_message' and content like '[from:%] [auto-report]%'"):
    m=re.match(r'\[from:([^\]]+)\] \[auto-report\]',head)
    if m: ars.append((sid,i,ts,m.group(1)))
pickle.dump((res,sess,ars),open('/tmp/an/t2.pkl','wb'))
print(len(res),len(ars))
