import sqlite3,re,json,collections
c=sqlite3.connect('file:/home/kesha/orchestra/data/orchestra.db?mode=ro',uri=True)
W="l.ts >= datetime('now','-14 days')"
NAME=re.compile(r'^([A-Za-z_][A-Za-z0-9_.]*):\s'); norm=lambda n: re.split(r'[ `]',(n or '').strip(),1)[0]
TARGET='/home/kesha/orchestra/CLAUDE.md'
lines=open(TARGET,'rb').read().split(b'\n')
q=f'''select l.tool_name,l.content from logs l join sessions s on s.id=l.session_id
      where l.type='tool' and {W}'''
tot_b=0; n=0
for tn,content in c.execute(q):
    content=content or ''
    m=NAME.match(content); name=norm(tn or (m.group(1) if m else ''))
    if name not in ('Read','read_file','ReadFile'): continue
    try: b=json.loads(content.split(':',1)[1])
    except Exception: continue
    p=b.get('file_path') or b.get('path')
    if p!=TARGET: continue
    o=b.get('offset') or 1; l=b.get('limit') or len(lines)
    seg=lines[max(0,o-1):max(0,o-1)+l]
    tot_b+=sum(len(x)+1 for x in seg); n+=1
print(f'файл: {TARGET}  {len(lines)} строк, {sum(len(x)+1 for x in lines)} байт')
print(f'чтений: {n}, суммарно прочитано: {tot_b} байт = {100*tot_b/sum(len(x)+1 for x in lines):.1f}% одного полного чтения файла')
# токены: кириллица ~2 байта/символ, ~2.5 символа/токен -> ~5 байт/токен; проверим на реальном тексте
try:
    import tiktoken; enc=tiktoken.get_encoding('cl100k_base')
    whole=open(TARGET,encoding='utf-8').read()
    print(f'tiktoken: весь файл = {len(enc.encode(whole))} токенов ({len(whole)} симв, {sum(len(x)+1 for x in lines)} байт)')
    bpt=sum(len(x)+1 for x in lines)/len(enc.encode(whole))
    print(f'  байт/токен = {bpt:.2f}  ->  прочитано ~{tot_b/bpt:.0f} токенов за 14 дней')
    print(f'  цена как fresh input у opus5 ($5/Mtok): ${tot_b/bpt/1e6*5:.4f}')
except ImportError:
    print('tiktoken нет — оценка: ~5 байт/токен для кириллицы ->', f'{tot_b/5:.0f} токенов, ${tot_b/5/1e6*5:.4f}')
