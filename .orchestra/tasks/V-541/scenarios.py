"""Conditional arithmetic, not measured subscription tariffs or a deployment recommendation."""
import gzip,json,pathlib
P=pathlib.Path(__file__).resolve().parent
D=json.load(gzip.open(P/'telemetry.json.gz'));R=json.loads((P/'regression.json').read_text())['3h_shift0'];K=['input_tokens','cache_read_tokens','cache_create_tokens','output_tokens']
a=R['free_cache_equal_write_input_output5']['coef'][0];c=R['api_1h_recomputed']['coef'][0]
models={'unrestricted_OLS':R['ols']['coef'],'free_read_equal_input_write_output5':[a,0,a,5*a],'quota_proportional_API_1h':[5*c,.5*c,10*c,25*c]}
rows={r['id']:r for r in D['turns']};out={}
for name,b in models.items():
 h=sum(rows[9920][k]*v/1e6 for k,v in zip(K,b));cold=sum(rows[9915][k]*v/1e6 for k,v in zip(K,b));saving=(b[2]-b[1])*.1
 out[name]={'coef_pp_per_M':b,'warm_9920_pp':h,'cold_9915_pp':cold,'assumed_reclassified_tokens':100000,'saving_100k_pp':saving,'max_pings_continuous':saving/h,'approx_hours_within_work_window':55/60*saving/h,'six_pings_pp':6*h,'six_pings_one_return_probability_threshold':6*h/saving}
(P/'scenarios.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
