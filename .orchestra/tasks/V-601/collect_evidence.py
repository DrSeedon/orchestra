"""Read-only source/live consumer inventory; seven-day usage is reused from V-600."""
import ast,collections,csv,json,re,sqlite3,subprocess
from pathlib import Path
p=Path(__file__).parent
names=[t['name'] for t in json.loads((p/'schemas.json').read_text())]
files=subprocess.check_output(['git','ls-files','app','tests','.orchestra/pipelines/default/prompts'],text=True).splitlines()
refs={n:{'prompts':[],'tests':[],'code':[]} for n in names}
for f in files:
    try: text=Path(f).read_text()
    except (UnicodeError,OSError): continue
    cat='prompts' if f.startswith('.orchestra/') else 'tests' if f.startswith('tests/') else 'code'
    for n in names:
        lines=[i for i,line in enumerate(text.splitlines(),1) if re.search(r'(?<![a-zA-Z0-9_])'+re.escape(n)+r'(?![a-zA-Z0-9_])',line) or 'mcp__orchestra__'+n in line]
        if lines: refs[n][cat].append({'path':f,'lines':lines})
(p/'references.json').write_text(json.dumps(refs,ensure_ascii=False,indent=2)+'\n')
seq=list(csv.DictReader(Path('.orchestra/tasks/V-600/tool-sequence-named.tsv').open(),delimiter='\t'))
chains={n:collections.Counter() for n in names}; consumers={n:set() for n in names}
for row in seq:
    n=row['tool_name']
    if n in chains:
        chains[n][row['prev1']+' → '+n]+=1
        consumers[n].add(row['agent'])
con=sqlite3.connect('file:/home/kesha/orchestra/data/orchestra.db?mode=ro',uri=True)
con.execute('PRAGMA query_only=ON')
# Only names, role/status and references; never dump session prompts or credentials.
sessions=con.execute("SELECT name,scope,status,role,backend_type,system_prompt,disabled_tools FROM sessions WHERE finished_at IS NULL OR finished_at='' ").fetchall()
live=[]
for name,scope,status,role,backend,prompt,disabled in sessions:
    live.append(dict(name=name,scope=scope,status=status,role=role,backend=backend,disabled_tools=disabled,references=[n for n in names if re.search(r'\b'+n+r'\b',prompt or '')]))
out={n:{'top_incoming':chains[n].most_common(3),'historical_agents':sorted(consumers[n]),'live_historical_agents':sorted(consumers[n]&{s['name'] for s in live}),'live_prompt_agents':[s['name'] for s in live if n in s['references']]} for n in names}
(p/'consumers.json').write_text(json.dumps({'tools':out,'live_sessions':live},ensure_ascii=False,indent=2)+'\n')
print('files',len(files),'live sessions',len(live),'sequence rows',len(seq))
print('live',[(s['name'],s['status']) for s in live])
