"""Keep operational counts separate from blind semantic acceptance."""
import collections,hashlib,json,pathlib,re,random,sys
HERE=pathlib.Path(__file__).resolve().parent
DOCS=HERE/'package/fixture/docs'
IRRELEVANT={'cafeteria.md','mobile-icon.md','office-move.md','translation.md'}
EXPECTED={'capacity':(720,480),'budget':(800,900),'rollback':(10,35)}


def clean_response(text):
    text=text.strip()
    return json.loads(text)


def structural(text):
    reasons=[]
    try:
        root=clean_response(text);questions=root['questions']
        if not isinstance(questions,list) or len(questions)!=3:raise ValueError('questions cardinality')
        if {q['area'] for q in questions}!=set(EXPECTED):raise ValueError('areas')
        for q in questions:
            for key in ['area','promised','observed','unit','source','question']:
                if key not in q:reasons.append('missing '+key)
            if any(isinstance(q.get(k),bool) or not isinstance(q.get(k),(int,float)) for k in ['promised','observed']):reasons.append(q['area']+': nonnumeric')
            if (q.get('promised'),q.get('observed'))!=EXPECTED[q['area']]:reasons.append(q['area']+': numbers')
            if 'docs/export-checks.md' not in str(q.get('source','')):reasons.append(q['area']+': source')
            if not isinstance(q.get('question'),str) or not q['question'].strip():reasons.append(q['area']+': empty question')
            unit=str(q.get('unit','')).lower()
            if q['area']=='capacity':valid=bool(re.search('export|экспорт',unit) and re.search('day|день|сут|дн',unit))
            elif q['area']=='budget':valid=bool(re.search('eur|евро|€',unit) and re.search('month|месяц|мес',unit))
            else:valid=bool(re.search('min|мин',unit))
            if not valid:reasons.append(q['area']+': unit needs review')
        return {'pass':not reasons,'reasons':reasons,'parsed':root,'semantic_acceptance':'pending blind annotation'}
    except Exception as error:return {'pass':False,'reasons':[str(error)],'semantic_acceptance':'pending blind annotation'}


def text_of(content):
    if isinstance(content,str):return content
    if isinstance(content,list):return '\n'.join(str(b.get('text',b.get('content',''))) for b in content if isinstance(b,dict))
    return str(content)


def calls(events,runtime):
    result=[];unknown=[]
    if runtime=='codex':
        seen=set()
        for event in events:
            if event.get('type')!='item.completed':continue
            item=event.get('item',{});kind=item.get('type');identity=item.get('id')
            if kind in ['agent_message','reasoning']:continue
            if identity in seen:continue
            seen.add(identity)
            if kind not in ['command_execution','file_change','mcp_tool_call','web_search','todo_list']:unknown.append(kind)
            result.append({'id':identity,'tool':kind,'arguments':item.get('command',item.get('arguments',item.get('changes'))),'outcome':item.get('exit_code',item.get('status')),'output':item.get('aggregated_output',text_of(item.get('result','')))})
    else:
        uses={};completed={}
        for event in events:
            if event.get('type') not in ['assistant','user']:continue
            for block in event.get('message',{}).get('content',[]):
                if not isinstance(block,dict):continue
                if block.get('type')=='tool_use':uses[block['id']]=block
                if block.get('type')=='tool_result':completed[block['tool_use_id']]=block
        for identity,block in completed.items():
            use=uses.get(identity,{})
            if not use:unknown.append('unmatched tool_result')
            result.append({'id':identity,'tool':use.get('name'),'arguments':use.get('input'),'outcome':'error' if block.get('is_error') else 'success','output':text_of(block.get('content',''))})
    return result,unknown


def normalize(output):
    output=re.sub(r'\x1b\[[0-9;]*m','',output).replace('\r\n','\n')
    lines=[]
    for line in output.splitlines():
        line=re.sub(r'^\s*\d+\s*[→\t]\s?','',line)
        line=re.sub(r'^(?:[^:\n]*/)?docs/[^:\n]+:\d+:','',line)
        lines.append(line.strip())
    return lines


def readings(toolcalls):
    docs={p.name:[line.strip() for line in p.read_text().splitlines() if line.strip()] for p in DOCS.glob('*.md')}
    seen={name:set() for name in docs};rows=[]
    for call in toolcalls:
        delivered=normalize(call['output']);frequency=collections.Counter(delivered)
        for name,source in docs.items():
            matched={i for i,line in enumerate(source) if line in delivered}
            if not matched:continue
            body=matched-{0}
            prior_full=len(seen[name])==len(source)
            rows.append({'call_id':call['id'],'document':name,'irrelevant':name in IRRELEVANT,'body_delivered':bool(body),'full_in_call':len(matched)==len(source),'header_only':not body,'repeat_after_complete':prior_full,'matched_lines':sorted(matched),'duplicate_line_occurrences_in_call':sum(max(0,frequency[source[i]]-1) for i in matched),'matched_source_utf8_bytes':sum(len(source[i].encode())*frequency[source[i]] for i in matched)})
            seen[name]|=matched
    names={r['document'] for r in rows if r['body_delivered']}
    return {'distinct_body_documents':len(names),'irrelevant_body_documents':len(names & IRRELEVANT),'body_exposures':sum(r['body_delivered'] for r in rows),'repeats_after_complete':sum(r['repeat_after_complete'] for r in rows),'matched_source_utf8_bytes':sum(r['matched_source_utf8_bytes'] for r in rows),'evidence':rows,'interpretation':'Matched delivered source-line occurrences (without prefixes/newlines); repeats_after_complete counts cross-invocation repeats; duplicate fragments within one invocation are separate. Unfamiliar paraphrases/truncation are not inferred as full reads.'}


def main(batch="initial"):
    rows=[];blind=[]
    for out in sorted((HERE/'arms').iterdir()):
        if not (out/'execution/process.json').exists():continue
        meta=json.loads((out/'invocation.json').read_text());process=json.loads((out/'execution/process.json').read_text())
        raw=(out/'execution/stdout.jsonl').read_text();events=[];invalid_lines=0
        for line in raw.splitlines():
            try:events.append(json.loads(line))
            except ValueError:invalid_lines+=1
        toolcalls,unknown=calls(events,meta['runtime'])
        (out/'tool-calls.json').write_text(json.dumps(toolcalls,ensure_ascii=False,indent=2)+'\n')
        read=readings(toolcalls)
        (out/'readings.json').write_text(json.dumps(read,ensure_ascii=False,indent=2)+'\n')
        response=(out/'execution/response.txt').read_text();check=structural(response)
        (out/'structural.json').write_text(json.dumps(check,ensure_ascii=False,indent=2)+'\n')
        account=process['accounting'];usage=account['usage'];total=None
        finals=[e for e in events if e.get('type') in ['turn.completed','result']]
        native_usage=finals[-1].get('usage',{}) if finals else {}
        reasoning=native_usage.get('reasoning_output_tokens') if meta['runtime']=='codex' else native_usage.get('output_tokens_details',{}).get('thinking_tokens')
        native_error=any((e.get('type')=='result' and e.get('is_error')) or e.get('type') in ['error','turn.failed'] for e in events)
        if account['final_received'] and account['status']=='complete' and not native_error:
            total=usage.get('input_tokens',0)+usage.get('output_tokens',0)
            if meta['runtime']=='claude':total+=usage.get('cache_read_input_tokens',0)+usage.get('cache_creation_input_tokens',0)
        row={'name':meta['name'],'model':meta['model'],'runtime':meta['runtime'],'variant':meta['variant'],'repeat':meta['repeat'],'effort':meta['effort'],'runtime_version':meta['runtime_version'],'input_sha256':meta['explicit_input_sha256'],'completion':process['completion'],'returncode':process['returncode'],'wall_seconds':process['wall_seconds'],'usage':usage,'total_tokens':total,'reasoning_tokens':reasoning,'native_usage':native_usage,'cost_usd':account['cost_usd'] if not native_error else None,'raw_reported_cost_usd':account['cost_usd'],'native_error':native_error,'accounting_status':account['status'],'completed_actions':len(toolcalls) if not unknown and not invalid_lines else None,'unknown_action_types':unknown,'invalid_jsonl_lines':invalid_lines,'distinct_body_documents':read['distinct_body_documents'],'irrelevant_body_documents':read['irrelevant_body_documents'],'repeats_after_complete':read['repeats_after_complete'],'delivered_source_bytes_lower_bound':read['matched_source_utf8_bytes'],'structural_pass':check['pass'],'semantic_pass':None,'boundaries_pass':None}
        rows.append(row)
        select=(meta['repeat']==2) if batch=='repeat' else (meta['alias'] in ['sol','fable']) if batch=='extend' else (meta['repeat']==1 and meta['alias'] in ['astra','luna','opus'])
        if select:blind.append({'original_name':meta['name'],'response':response})
    (HERE/'measurements.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
    random.Random(566).shuffle(blind)
    prefix={'initial':'Q','repeat':'R','extend':'E'}[batch]
    key={f'{prefix}{i+1:02}':v['original_name'] for i,v in enumerate(blind)}
    (HERE/f'blind-key-{batch}.json').write_text(json.dumps(key,indent=2)+'\n')
    (HERE/f'blind-answers-{batch}.json').write_text(json.dumps([{'id':f'{prefix}{i+1:02}','response':v['response']} for i,v in enumerate(blind)],ensure_ascii=False,indent=2)+'\n')
    print(json.dumps([{k:r[k] for k in ['name','completion','total_tokens','cost_usd','completed_actions','distinct_body_documents','irrelevant_body_documents','structural_pass']} for r in rows],ensure_ascii=False,indent=2))

if __name__=='__main__':main(sys.argv[1] if len(sys.argv)>1 else 'initial')
