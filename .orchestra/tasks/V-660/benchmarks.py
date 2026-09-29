"""Recalculate V-656 CLI and V-620 token observations in weekly-pool units."""
import json,pathlib,statistics
ROOT=pathlib.Path(__file__).resolve().parent
REPO=ROOT.parents[2]
RUNS=REPO/'.orchestra/tasks/V-656/runs'
# Current V-660 shared fit across Claude token categories, pp per MTok.
BETA={'input_tokens':642.7303960767324,'cache_create_tokens':0.6038144757855058,'cache_read_tokens':0.006874226105772035,'output_tokens':-0.5986312936677188}
BETA_CI={'cache_create_tokens':(0.19581251305401337,1.2329676677639652)}
OLD={'input_tokens':6.57,'cache_create_tokens':0.811,'cache_read_tokens':0.00352,'output_tokens':1.81}
API_SCALE={'incl_read_1h':0.03513262084895932,'read_zero_1h':0.10648936043297515}
# API USD/MTok, then derive the documented TTL-specific cache-write price.
PRICES={
 'claude-sonnet-5':{'input':2,'read':.20,'write5m':2.5,'write1h':4,'output':10},
 'claude-sonnet-5-5':{'input':2,'read':.20,'write5m':2.5,'write1h':4,'output':10},
 'claude-opus-5[1m]':{'input':5,'read':.50,'write5m':6.25,'write1h':10,'output':25},
 'claude-opus-5-5[1m]':{'input':4,'read':.20,'write5m':5,'write1h':8,'output':20},
}
CODEX_CREDITS={
 'gpt-6-luna':(2.5,.25,12.5), 'gpt-6-sol':(50,5,250), 'gpt-6-astra':(250,25,1250),
 'gpt-5.6-luna':(5,.5,30), 'gpt-5.6-sol':(100,10,500),
}
def result(run):
 p=RUNS/run/'result.json'
 if not p.exists():return None
 x=json.load(open(p))
 model,usage=next(iter(x['modelUsage'].items()))
 return {'run':run,'model':model,**{k:usage.get(k,0) or 0 for k in ('inputTokens','cacheReadInputTokens','cacheCreationInputTokens','outputTokens','thinkingTokens')},'costUSD':usage.get('costUSD')}
def group(runs,label):
 items=[result(r) for r in runs];items=[x for x in items if x]
 if not items:return None
 d={k:sum(x[k] or 0 for x in items) for k in ('inputTokens','cacheReadInputTokens','cacheCreationInputTokens','outputTokens','thinkingTokens')}
 model=items[0]['model']; p=PRICES[model]
 vals={'input_tokens':d['inputTokens'],'cache_read_tokens':d['cacheReadInputTokens'],'cache_create_tokens':d['cacheCreationInputTokens'],'output_tokens':d['outputTokens']}
 v605=sum(vals[k]*OLD[k] for k in OLD)/1e6
 current=sum(vals[k]*BETA[k] for k in BETA)/1e6
 write=d['cacheCreationInputTokens']/1e6
 api1=(d['inputTokens']*p['input']+d['cacheReadInputTokens']*p['read']+d['cacheCreationInputTokens']*p['write1h']+d['outputTokens']*p['output'])/1e6
 api0=(d['inputTokens']*p['input']+d['cacheCreationInputTokens']*p['write1h']+d['outputTokens']*p['output'])/1e6
 return {'label':label,'runs':[x['run'] for x in items],'model':model,'n_runs':len(items),**d,'thinking_is_subset_of_output':d['thinkingTokens']<=d['outputTokens'],'cli_cost_usd':sum(x['costUSD'] or 0 for x in items),'api_cost_5m_usd':(d['inputTokens']*p['input']+d['cacheReadInputTokens']*p['read']+d['cacheCreationInputTokens']*p['write5m']+d['outputTokens']*p['output'])/1e6,'api_cost_1h_usd':api1,'api_cost_1h_without_read_usd':api0,'api_inclusive_read_1h_pp_prediction':api1*API_SCALE['incl_read_1h'],'read_zero_1h_pp_prediction':api0*API_SCALE['read_zero_1h'],'V605_point_pp':v605,'V660_post19_full_point_pp':current,'V660_create_only_point_pp':write*.6038144757855058,'V660_create_only_95pp':[write*BETA_CI['cache_create_tokens'][0],write*BETA_CI['cache_create_tokens'][1]],'V660_model_specific_not_identified':True}

def main():
 rows=[]
 # V-656 first comparison, plus the explicit effort ladder.
 for run in ('trio-s5','quota-s5'):
  rows.append(group([run],run))
 for run in ('trio-s55','quota-s55'):
  rows.append(group([run],run))
 for effort in ('low','medium','high','xhigh','max'):
  runs=[f'trio-55-{effort}',f'quota-55-{effort}']
  if all((RUNS/r/'result.json').exists() for r in runs):rows.append(group(runs,f'Sonnet 5.5 {effort}, both tasks'))
 rows.append(group(['trio-s55','quota-s55'],'Sonnet 5.5 default, both tasks'))
 # Any later V-656 hard-* runs are included automatically when result.json exists.
 hard=[]
 for p in sorted(RUNS.glob('hard-*')):
  if (p/'result.json').exists():hard.append(group([p.name],p.name))
 # V-620 table usage: cache-read / cache-create / output; uncached input was 0 for Opus.
 v620=[
  {'model':'Opus 5.5','key':'claude-opus-5-5[1m]','inputTokens':0,'cacheReadInputTokens':16984093,'cacheCreationInputTokens':222183,'outputTokens':74232,'reported_cli_usd':6.66},
  {'model':'Opus 5','key':'claude-opus-5[1m]','inputTokens':0,'cacheReadInputTokens':9948605,'cacheCreationInputTokens':152175,'outputTokens':45475,'reported_cli_usd':7.64},
 ]
 v620_out=[]
 for d in v620:
  p=PRICES[d['key']]
  d['api_1h_usd']=(d['inputTokens']*p['input']+d['cacheReadInputTokens']*p['read']+d['cacheCreationInputTokens']*p['write1h']+d['outputTokens']*p['output'])/1e6
  d['api_1h_without_read_usd']=(d['inputTokens']*p['input']+d['cacheCreationInputTokens']*p['write1h']+d['outputTokens']*p['output'])/1e6
  d['api_inclusive_read_1h_pp_prediction']=d['api_1h_usd']*API_SCALE['incl_read_1h']
  d['read_zero_1h_pp_prediction']=d['api_1h_without_read_usd']*API_SCALE['read_zero_1h']
  vals={'input_tokens':d['inputTokens'],'cache_read_tokens':d['cacheReadInputTokens'],'cache_create_tokens':d['cacheCreationInputTokens'],'output_tokens':d['outputTokens']}
  d['V605_point_pp']=sum(vals[k]*OLD[k] for k in OLD)/1e6
  d['V660_create_only_point_pp']=d['cacheCreationInputTokens']/1e6*.6038144757855058
  d['V660_create_only_95pp']=[d['cacheCreationInputTokens']/1e6*v for v in BETA_CI['cache_create_tokens']]
  v620_out.append(d)
 # V-620 Codex one-task token totals from bench-models.md. `input` here is uncached.
 v620_codex=[]
 for d in [
  {'model':'GPT-5.6 Sol','key':'gpt-5.6-sol','uncached_input':205665,'cached_input':11995904,'output':41079,'api_usd':6.44},
  {'model':'GPT-6 Sol','key':'gpt-6-sol','uncached_input':203380,'cached_input':17050112,'output':50014,'api_usd':4.32},
  {'model':'GPT-5.6 Luna','key':'gpt-5.6-luna','uncached_input':301654,'cached_input':22564096,'output':47707,'api_usd':.57},
  {'model':'GPT-6 Luna','key':'gpt-6-luna','uncached_input':300225,'cached_input':19858688,'output':72720,'api_usd':.26},
 ]:
  ir,cr,orr=CODEX_CREDITS[d['key']]
  d['credit_units_by_current_standard_rate']=(d['uncached_input']*ir+d['cached_input']*cr+d['output']*orr)/1e6
  d['cache_write_credit_units']=0
  v620_codex.append(d)
 # modelUsage has no observed quota pp; for ranking, leave it blank rather than allocating shared changes.
 hard_found=[p.name for p in RUNS.glob('hard-*') if (p/'result.json').exists()]
 out={'source':'V-656 runs/*/result.json, V-620/bench-models.md; current pool coefficients from analysis_post19.json','formula_note':'V605 is historical aggregate point formula; V660 full point is the unconstrained post-19 aggregate fit (not adopted because input/output/read intervals overlap zero). The only currently supported per-token component is cache creation; its pp range covers that component only and is not a full-run estimate. API-price-trained pp values are model-agnostic hypotheses, not direct turn attribution.','V656':rows,'V656_hard_runs':hard,'V656_hard_dirs_found':hard_found,'V620_Claude':v620_out,'V620_Codex':v620_codex}
 (ROOT/'benchmark_recosts.json').write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n')
 print(json.dumps(out,indent=2,ensure_ascii=False))
if __name__=='__main__':main()
