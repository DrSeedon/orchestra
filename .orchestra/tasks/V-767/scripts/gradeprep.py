import json,os,random,shutil,sys
R='/home/kesha/orchestra/data/v767'; V='/home/kesha/orchestra/data/v758'
cells=sys.argv[1:]  # labels in v767/runs ; anchors from v758/runs prefixed with "A:"
random.seed(7); random.shuffle(cells); mp={}
os.makedirs(R+'/grade',exist_ok=True)
for i,c in enumerate(cells):
    src=(V if c.startswith('A:') else R)+'/runs/'+c.replace('A:','')
    g=f'{R}/grade/g{i:02d}'; os.makedirs(g,exist_ok=True)
    for f in ('diff.patch','diffstat.txt','own_tests.txt','oracle_tests.txt'): shutil.copy(f'{src}/{f}',g)
    try:
        j=json.load(open(src+'/result.json')); open(g+'/final_message.txt','w').write(j.get('result') or '')
    except Exception: open(g+'/final_message.txt','w').write('(итогового сообщения нет: прогон оборван)')
    mp[f'g{i:02d}']=c
json.dump(mp,open(R+'/grade_map.json','w'),indent=1)
brief=open(V+'/grade/brief.md').read().replace('/home/kesha/orchestra/data/v758/grade/','/home/kesha/orchestra/data/v767/grade/').replace('/home/kesha/orchestra/data/v758/task-','/home/kesha/orchestra/data/v767/task-')
open(R+'/grade/brief.md','w').write(brief); shutil.copy(V+'/grade/criteria.json',R+'/grade/')
print(len(mp))
