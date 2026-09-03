import pickle, collections, statistics
per_turn=pickle.load(open('/tmp/per_turn.pkl','rb'))
COEF={'claude':dict(own=0.1349, prior=0.00015, inter=0.492, cr_per_call=186746),
      'codex' :dict(own=0.1064, prior=0.00009, inter=0.283, cr_per_call=153843)}
RECON={'claude':0.268,'codex':0.348}   # доля разведки из tool-call-mix.md
print('=== сверка канала контекста с декомпозицией расхода ===')
for rt,c in COEF.items():
    # cache_read токенов на вызов -> $ (opus5: input $5/Mtok, cache_read = 0.1x = $0.5/Mtok)
    d=c['cr_per_call']/1e6*0.5
    print(f'  {rt}: {c["cr_per_call"]:,} cache_read токенов на вызов = ${d:.4f} = {100*d/c["own"]:.0f}% предельной цены вызова ${c["own"]:.4f}')
print('  (независимая сверка: декомпозиция расхода дала cache_read 68.6% — метод другой, порядок тот же)')
print()
print('=== сколько стоит РАЗВЕДКА ===')
tot_cost=0; tot_recon=0; tot_calls=0
for rt in ('claude','codex'):
    rows=[t for t in per_turn if t['rt']==rt]
    calls=sum(t['n_tools'] for t in rows); spend=sum(t['cost'] for t in rows)
    rec=calls*RECON[rt]; rcost=rec*COEF[rt]['own']
    tot_cost+=spend; tot_recon+=rcost; tot_calls+=calls
    print(f'  {rt}: вызовов {calls:,}, из них разведка {RECON[rt]:.1%} = {rec:,.0f}')
    print(f'        расход ${spend:,.0f}; разведка по предельной цене = ${rcost:,.0f} ({100*rcost/spend:.1f}% расхода)')
print(f'  ИТОГО: расход ${tot_cost:,.0f}, разведка ${tot_recon:,.0f} = {100*tot_recon/tot_cost:.1f}%')
print()
print('=== перевод сокращения вызовов в деньги ===')
for rt in ('claude','codex'):
    rows=[t for t in per_turn if t['rt']==rt]
    spend=sum(t['cost'] for t in rows); n=len(rows); calls=sum(t['n_tools'] for t in rows)
    fixed=COEF[rt]['inter']*n
    print(f'  {rt}: расход ${spend:,.0f}; фиксированная часть (интерсепт x ходы) ${fixed:,.0f} = {100*fixed/spend:.0f}%')
    print(f'        -> сокращение вызовов на 20% даёт {20*(1-fixed/spend):.1f}% расхода = ${0.20*calls*COEF[rt]["own"]:,.0f}')
