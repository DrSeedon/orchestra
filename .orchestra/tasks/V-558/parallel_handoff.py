"""Start only untouched arms; exclusive output mkdir prevents duplicate dispatch."""
import asyncio,json
from run_arms import execute,HERE
async def main():
    names=['opus','fable']
    assert all(not (HERE/'evidence'/name).exists() for name in names)
    results=await asyncio.gather(*(execute(name,5.0) for name in names),return_exceptions=True)
    rows=[{'name':name,'error':str(row)} if isinstance(row,BaseException) else row for name,row in zip(names,results)]
    (HERE/'evidence/parallel-results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps([{'name':r['name'],'pass':r.get('pass'),'cost_usd':r.get('cost_usd'),'error':r.get('error')} for r in rows],ensure_ascii=False))
asyncio.run(main())
