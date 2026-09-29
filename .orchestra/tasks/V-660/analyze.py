"""Reproduce V-660 subscription-window analysis from an SQLite backup."""
import argparse, bisect, csv, datetime as dt, json, math, pathlib, random, sqlite3, statistics

ROOT = pathlib.Path(__file__).resolve().parent
MODELS = ['claude-opus-5[1m]', 'claude-opus-5-5[1m]', 'claude-sonnet-5[1m]', 'claude-sonnet-5-5', 'claude-fable-5-1[1m]', 'claude-haiku-4-5']
TOKENS = ['input_tokens', 'cache_create_tokens', 'cache_read_tokens', 'output_tokens']
START = '2026-09-19T00:00:00+00:00'
MODEL_KEYS = ('opus5','opus55','sonnet5','sonnet55','fable','haiku')
# USD per million tokens; rows come from the cited Anthropic API price card.
API = {
    'opus5': {'input':5.0,'read':0.5,'write5m':6.25,'write1h':10.0,'output':25.0},
    'opus55': {'input':4.0,'read':0.2,'write5m':5.0,'write1h':8.0,'output':20.0},
    'sonnet5': {'input':2.0,'read':0.2,'write5m':2.5,'write1h':4.0,'output':10.0},
    'sonnet55': {'input':2.0,'read':0.2,'write5m':2.5,'write1h':4.0,'output':10.0},
    'fable': {'input':10.0,'read':0.25,'write5m':12.5,'write1h':20.0,'output':50.0},
    'haiku': {'input':1.0,'read':0.1,'write5m':1.25,'write1h':2.0,'output':5.0},
}


def stamp(s):
    return dt.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()


def solve(a, b):
    n = len(b)
    a = [list(row) + [v] for row, v in zip(a, b)]
    for i in range(n):
        k = max(range(i, n), key=lambda z: abs(a[z][i]))
        if abs(a[k][i]) < 1e-13:
            raise ValueError('singular design')
        a[i], a[k] = a[k], a[i]
        d = a[i][i]
        a[i] = [v / d for v in a[i]]
        for j in range(n):
            if j == i:
                continue
            d = a[j][i]
            a[j] = [x - d * y for x, y in zip(a[j], a[i])]
    return [row[-1] for row in a]


def ols(rows, y, cols):
    if len(rows) <= len(cols):
        raise ValueError('too few rows')
    scales = [math.sqrt(sum(r[j] ** 2 for r in rows)) for j in cols]
    if any(v == 0 for v in scales):
        raise ValueError('unsupported column')
    z = [[r[j] / s for j, s in zip(cols, scales)] for r in rows]
    gram = [[sum(r[i] * r[j] for r in z) for j in range(len(cols))] for i in range(len(cols))]
    rhs = [sum(r[i] * v for r, v in zip(z, y)) for i in range(len(cols))]
    beta = solve(gram, rhs)
    return [v / s for v, s in zip(beta, scales)]


def fit(rows, y, names):
    candidates = [i for i in range(len(names)) if any(r[i] != 0 for r in rows)]
    basis, cols = [], []
    for j in candidates:
        v = [r[j] for r in rows]
        norm = math.sqrt(sum(x*x for x in v)) or 1
        v = [x / norm for x in v]
        for q in basis:
            dot = sum(x*z for x,z in zip(v,q))
            v = [x-dot*z for x,z in zip(v,q)]
        residual = math.sqrt(sum(x*x for x in v))
        if residual > 1e-9:
            basis.append([x/residual for x in v]); cols.append(j)
    b = ols(rows, y, cols)
    pred = [sum(r[j] * v for j, v in zip(cols, b)) for r in rows]
    sse = sum((v - p) ** 2 for v, p in zip(y, pred))
    mean = statistics.mean(y)
    sst = sum((v - mean) ** 2 for v in y)
    coefs = {names[j]: v for j, v in zip(cols, b)}
    return {'coef': coefs, 'aliased': [names[j] for j in candidates if j not in cols], 'rmse': math.sqrt(sse / len(y)), 'r2': 1 - sse / sst if sst else None, 'n': len(y), 'rank': len(cols)}


def one_weight(x, y):
    denom = sum(v*v for v in x)
    b = sum(a*v for a,v in zip(y,x)) / denom if denom else 0
    pred = [b*v for v in x]
    return {'scale_pp_per_api_usd': b, 'rmse': math.sqrt(statistics.mean((a-p)**2 for a,p in zip(y,pred))), 'actual_sum_pp':sum(y), 'predicted_sum_pp':sum(pred)}


def model_key(s):
    if 'opus-5-5' in s: return 'opus55'
    if 'opus-5[' in s: return 'opus5'
    if 'sonnet-5-5' in s: return 'sonnet55'
    if 'sonnet-5[' in s: return 'sonnet5'
    if 'fable' in s: return 'fable'
    if 'haiku' in s: return 'haiku'
    return 'other'


def extract(dbpath, start_iso):
    c = sqlite3.connect(f'file:{dbpath}?mode=ro', uri=True)
    c.row_factory = sqlite3.Row
    turns = [dict(r) for r in c.execute("SELECT ts,runtime,model,input_tokens,cache_create_tokens,cache_read_tokens,output_tokens,cost_usd FROM turn_usage WHERE runtime='claude' AND ts >= ? ORDER BY ts", (start_iso,))]
    snaps = []
    for r in c.execute("SELECT ts,seven_day_pct,seven_day_resets_at,provider_usage FROM usage_snapshots WHERE ts >= ? ORDER BY ts", (start_iso,)):
        q, reset = r['seven_day_pct'], r['seven_day_resets_at']
        if r['provider_usage']:
            try:
                anthropic = json.loads(r['provider_usage']).get('anthropic', {})
                win = next((w for w in anthropic.get('windows', []) if w.get('id') == 'seven_day'), None)
                if win:
                    q, reset = win.get('utilization'), win.get('resets_at')
            except (ValueError, TypeError):
                pass
        if q is not None:
            snaps.append({'ts': r['ts'], 'time': stamp(r['ts']), 'q': float(q), 'reset': (reset or '')[:10]})
    c.close()
    turns = [r for r in turns if model_key(r['model']) != 'other']
    for r in turns:
        r['time'] = stamp(r['ts'])
    times = [r['time'] for r in turns]
    intervals, start = [], None
    prev = None
    for r in snaps:
        good = 0 <= r['q'] < 100 and r['reset'] and r['time'] >= stamp(start_iso)
        broken = prev is not None and (r['time'] - prev['time'] > 900 or r['reset'] != prev['reset'] or r['q'] < prev['q'])
        if not good:
            start = None; prev = r; continue
        if start is None or broken:
            start = r
        if r['time'] - start['time'] >= 3 * 3600:
            a = bisect.bisect_right(times, start['time'])
            b = bisect.bisect_right(times, r['time'])
            ts = turns[a:b]
            agg = {m: {k: 0 for k in TOKENS} for m in MODEL_KEYS}
            for t in ts:
                bucket = model_key(t['model'])
                for k in TOKENS:
                    agg[bucket][k] += t[k] or 0
            flat = []
            for m in MODEL_KEYS:
                flat.extend(agg[m][k] / 1e6 for k in TOKENS)
            intervals.append({'start': start['ts'], 'end': r['ts'], 'day': start['ts'][:10], 'reset': r['reset'], 'hours': (r['time'] - start['time']) / 3600, 'delta': r['q'] - start['q'], 'n': len(ts), 'by_model': {m: agg[m] for m in agg}, 'x': flat})
            start = r
        prev = r
    c2 = sqlite3.connect(f'file:{dbpath}?mode=ro', uri=True)
    counts = list(c2.execute("SELECT model,count(*),sum(input_tokens),sum(cache_create_tokens),sum(cache_read_tokens),sum(output_tokens),min(ts),max(ts) FROM turn_usage WHERE runtime='claude' AND ts >= ? GROUP BY model ORDER BY count(*) DESC", (start_iso,)))
    c2.close()
    return turns, snaps, intervals, counts


def summarize(path, start, suffix):
    turns, snaps, all_intervals, counts = extract(path, start)
    use = [r for r in all_intervals if r['n'] and sum(sum(v.values()) for v in r['by_model'].values()) > 0]
    names = [f'{m}:{k}' for m in MODEL_KEYS for k in TOKENS]
    X = [r['x'] for r in use]; y = [r['delta'] for r in use]
    full = fit(X, y, names)
    base_names = TOKENS
    base_X = [[sum(r['x'][i*4+j] for i in range(len(MODEL_KEYS))) for j in range(4)] for r in use]
    base = fit(base_X, y, base_names)
    days = sorted({r['day'] for r in use})
    rng = random.Random(660)
    byday = {d: [r for r in use if r['day'] == d] for d in days}
    boot = {n: [] for n in names}; baseboot = {n: [] for n in base_names}
    successful, rank_fail = 0, 0
    joint_draws=[]
    for _ in range(2000):
        sample = [r for d in rng.choices(days, k=len(days)) for r in byday[d]]
        try:
            b = fit([r['x'] for r in sample], [r['delta'] for r in sample], names)['coef']
            bb = fit([[sum(r['x'][i*4+j] for i in range(len(MODEL_KEYS))) for j in range(4)] for r in sample], [r['delta'] for r in sample], base_names)['coef']
            successful += 1
            joint_draws.append(b)
            for n, v in b.items(): boot[n].append(v)
            for n, v in bb.items(): baseboot[n].append(v)
        except ValueError:
            rank_fail += 1
    def q(v, p): return sorted(v)[min(len(v)-1, int(p * len(v)))] if v else None
    intervals = {n: {'lo': q(v,.025), 'hi': q(v,.975), 'bootstrap_n': len(v)} for n,v in boot.items()}
    base_intervals = {n: {'lo': q(v,.025), 'hi': q(v,.975), 'bootstrap_n': len(v)} for n,v in baseboot.items()}
    contrasts={}
    for model in ('opus55','sonnet5','sonnet55','fable','haiku'):
        for token in TOKENS:
            numerator=f'{model}:{token}';denominator=f'opus5:{token}'
            pairs=[(d[numerator],d[denominator]) for d in joint_draws if numerator in d and denominator in d and abs(d[denominator])>1e-12]
            ratios=[a/b for a,b in pairs]; diffs=[a-b for a,b in pairs]
            contrasts[f'{model}_vs_opus5:{token}']={'ratio_point':full['coef'].get(numerator)/full['coef'][denominator] if numerator in full['coef'] and denominator in full['coef'] and abs(full['coef'][denominator])>1e-12 else None,'ratio_95':[q(ratios,.025),q(ratios,.975)],'difference_95':[q(diffs,.025),q(diffs,.975)],'paired_bootstrap_n':len(pairs)}
    # Chronological delayed validation: fit through Sep 26, score Sep 27-29.
    train = [r for r in use if r['day'] <= '2026-09-26']
    test = [r for r in use if r['day'] >= '2026-09-27']
    held = {}
    for label, xx, nn in [('all_model_token', [r['x'] for r in use], names), ('all_token', base_X, base_names)]:
        if label == 'all_model_token': tx = [r['x'] for r in train]; vx = [r['x'] for r in test]
        else:
            tx = [[sum(r['x'][i*4+j] for i in range(len(MODEL_KEYS))) for j in range(4)] for r in train]
            vx = [[sum(r['x'][i*4+j] for i in range(len(MODEL_KEYS))) for j in range(4)] for r in test]
        try:
            b = fit(tx, [r['delta'] for r in train], nn)['coef']
            pred = [sum(row[i] * b.get(nn[i], 0) for i in range(len(nn))) for row in vx]
            held[label] = {'train_n':len(train),'train_days':sorted({r['day'] for r in train}),'test_n':len(test),'test_days':sorted({r['day'] for r in test}),'rmse':math.sqrt(statistics.mean((r['delta']-p)**2 for r,p in zip(test,pred))) if test else None,'actual':sum(r['delta'] for r in test),'predicted':sum(pred)}
        except ValueError as e: held[label]={'error':str(e),'train_n':len(train),'test_n':len(test)}
    # External hypothesis check: proportional to model-specific API worth, with or without cache-read cost.
    def api_value(r, ttl, include_read):
        total = 0.0
        for mi, m in enumerate(MODEL_KEYS):
            a = API[m]
            raw = r['x'][mi*4:mi*4+4]
            total += raw[0]*a['input'] + raw[1]*a['write'+ttl] + raw[3]*a['output']
            if include_read: total += raw[2]*a['read']
        return total
    api_hypotheses = {}
    for ttl in ('5m','1h'):
        for read in (True,False):
            label=f'api_price_{ttl}_'+('with_read' if read else 'read_zero')
            tx=[api_value(r,ttl,read) for r in train]
            vx=[api_value(r,ttl,read) for r in test]
            b=one_weight(tx,[r['delta'] for r in train])
            pred=[b['scale_pp_per_api_usd']*x for x in vx]
            api_hypotheses[label]={'train_scale_pp_per_api_usd':b['scale_pp_per_api_usd'],'train_rmse':b['rmse'],'holdout_n':len(test),'holdout_days':sorted({r['day'] for r in test}),'holdout_actual_sum_pp':sum(r['delta'] for r in test),'holdout_predicted_sum_pp':sum(pred),'holdout_rmse':math.sqrt(statistics.mean((r['delta']-p)**2 for r,p in zip(test,pred))) if test else None,'daily':{d:{'actual':sum(r['delta'] for r in test if r['day']==d),'predicted':sum(p for r,p in zip(test,pred) if r['day']==d)} for d in sorted({r['day'] for r in test})}}
    # Leave-one-day-out folds to compare the four-token aggregate with model interactions.
    cv = {'all_model_token': [], 'all_token': []}
    for day in days:
        tr=[r for r in use if r['day'] != day]; te=[r for r in use if r['day'] == day]
        for label, nn in [('all_model_token', names), ('all_token', base_names)]:
            tx=[r['x'] for r in tr] if label == 'all_model_token' else [[sum(r['x'][i*4+j] for i in range(len(MODEL_KEYS))) for j in range(4)] for r in tr]
            vx=[r['x'] for r in te] if label == 'all_model_token' else [[sum(r['x'][i*4+j] for i in range(len(MODEL_KEYS))) for j in range(4)] for r in te]
            try:
                b=fit(tx,[r['delta'] for r in tr],nn)['coef']
                for r,row in zip(te,vx): cv[label].append((r['delta']-sum(row[i]*b.get(nn[i],0) for i in range(len(nn))))**2)
            except ValueError: pass
    out = {
        'period': {'start_utc':start,'snapshot_through_utc':snaps[-1]['ts'] if snaps else None,'turn_through_utc':turns[-1]['ts'] if turns else None},
        'counts_by_model': [dict(zip(['model','n','input','cache_create','cache_read','output','first','last'], r)) for r in counts],
        'all_claude_turns':len(turns),'snapshot_count_since_start':len(snaps),'interval_count':len(all_intervals),'fit_intervals':len(use),'fit_days':days,'fit_total_delta_pp':sum(y),
        'models_present_by_day':{d:sorted({model_key(t['model']) for t in turns if t['ts'][:10]==d}) for d in sorted({t['ts'][:10] for t in turns})},
        'aggregate_four_token_fit':base,'aggregate_four_token_day_bootstrap_95':base_intervals,
        'model_by_token_fit':full,'model_by_token_day_bootstrap_95':intervals,'model_vs_opus5_bootstrap_contrasts':contrasts,'bootstrap_successful_draws':successful,'bootstrap_rank_failures':rank_fail,
        'chronological_holdout':held,'leave_one_day_out_rmse':{k:math.sqrt(statistics.mean(v)) if v else None for k,v in cv.items()},
        'api_price_hypothesis_holdout':api_hypotheses,
        'windows':[{k:v for k,v in r.items() if k!='x'} for r in all_intervals],
    }
    (ROOT/f'analysis{suffix}.json').write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n')
    with (ROOT/f'windows{suffix}.csv').open('w') as f:
        fields=['start','end','day','reset','hours','delta','n']+[f'{m}_{k}' for m in MODEL_KEYS for k in TOKENS]
        w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader()
        for r in all_intervals:
            row={k:r[k] for k in fields if k in r}
            for m in MODEL_KEYS:
                for k in TOKENS: row[f'{m}_{k}']=r['by_model'][m][k]/1e6
            w.writerow(row)
    print(json.dumps({k:v for k,v in out.items() if k not in ('windows','models_present_by_day')},ensure_ascii=False,indent=2))

if __name__ == '__main__':
    ap=argparse.ArgumentParser();ap.add_argument('db',help='SQLite backup created by backup_live_db.py');ap.add_argument('--start',default=START);ap.add_argument('--suffix',default='');args=ap.parse_args();summarize(args.db,args.start,args.suffix)
