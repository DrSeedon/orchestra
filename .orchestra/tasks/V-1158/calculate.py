"""Offline, hypothetical pricing arithmetic; not measurements of Orchestra use."""
from decimal import Decimal as D
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MILLION = D(1_000_000)

# Order is fresh input, cache write (short TTL), cache read, output.
# Wello table prices, not the ambiguous generic cache formula or subscription weights.
RATES = {
    'opus5': {'wello': ('2', '2.50', '.20', '2'),
              'official': ('5', '6.25', '.50', '25')},
    'opus48': {'wello': ('2', '2.50', '.20', '2'),
               'official': ('5', '6.25', '.50', '25')},
    'sonnet5': {'wello': ('1.60', '2', '.16', '1.60'),
                'official': ('2', '2.50', '.20', '10')},
    'haiku55': {'wello': ('.10', '.13', '.01', '.50'),
                'official': ('.10', '.125', '.01', '.50')},
    'astra6': {'wello': ('3.75', '4.69', '.38', '12.50'),
               'official': ('10', '12.50', '1', '50')},
    'luna56': {'wello': ('.25', '.31', '.03', '.60'),
               'official': ('.20', '.25', '.02', '1.20')},
    'terra56': {'wello': ('.45', '.56', '.04', '1.35'),
                'official': ('2', '2.50', '.20', '12')},
    'sol56': {'wello': ('.90', '1.13', '.09', '2.70'),
              'official': ('4', '5', '.40', '20')},
    'glm53flash': {'wello': ('.38', '.47', '.08', '1.25'),
                   # Z.ai currently lists cache storage as temporarily free.
                   'official': ('.15', '0', '.03', '.50')},
}
MIXES = {
    'fresh50_output50': (500_000, 0, 0, 500_000),
    'hypothetical_agent_heavy_cache': (50_000, 50_000, 850_000, 50_000),
    'all_cache_read_boundary_not_a_task': (0, 0, 1_000_000, 0),
    'all_output_boundary_not_a_task': (0, 0, 0, 1_000_000),
}
PLANS = {
    'pro': (399, 5, 40, 330, 1),
    'max5': (1500, 19, 200, 1670, 5),
    'max20': (4800, 59, 800, 6700, 20),
    'max100': (20900, 249, 4000, 33000, 100),
}


def cost(rates, counts):
    if len(rates) != 4 or len(counts) != 4 or any(D(v) < 0 for v in counts):
        raise ValueError('Four nonnegative, disjoint token legs required')
    return sum(D(rate) * D(count) for rate, count in zip(rates, counts)) / MILLION


def savings(ours, baseline):
    if baseline <= 0:
        raise ValueError('Positive baseline required')
    return (D(1) - ours / baseline) * 100


def calculate():
    rows = []
    for model, rates in RATES.items():
        for mix, counts in MIXES.items():
            wello = cost(rates['wello'], counts)
            official = cost(rates['official'], counts)
            rows.append({'model': model, 'mix': mix, 'token_counts_I_W_H_O': list(counts),
                         'wello_usd': str(wello), 'official_usd': str(official),
                         'savings_percent': str(savings(wello, official))})
    plans = []
    for name, (rub, usd_display, million_tokens, steps, multiplier) in PLANS.items():
        plans.append({
            'plan': name, 'display_rub': rub, 'display_usd_separate_locale': usd_display,
            'advertised_up_to_million_tokens': million_tokens, 'approx_steps': steps,
            'advertised_limit_multiplier': multiplier,
            'conditional_rub_per_million_at_full_advertised_volume': str(D(rub)/million_tokens),
            'implied_tokens_per_step_not_observed': str(D(million_tokens)*MILLION/steps),
            'price_ratio_rub_usd_not_an_fx_contract': str(D(rub)/usd_display),
            'hypothetical_opus5_retail_equivalent_usd_if_fresh50_output50':
                str(cost(RATES['opus5']['wello'], MIXES['fresh50_output50'])*million_tokens),
            'hypothetical_opus5_retail_equivalent_usd_if_heavy_cache':
                str(cost(RATES['opus5']['wello'], MIXES['hypothetical_agent_heavy_cache'])*million_tokens),
        })
    return {'as_of_utc_date': '2026-10-31', 'currency': 'USD unless marked RUB',
            'unit': '1,000,000 disjoint tokens per illustrative mix',
            'basis': 'Published price arithmetic, no quality, latency or real workload measurement',
            'cache_basis': 'Wello table; official Anthropic 5m / OpenAI 30m; Z.ai storage temporarily free',
            'coverage': 'Same-version IDs as labelled only; backend authenticity unverified; short prompts',
            'confidence_interval': None, 'subscription_budget_usd': None,
            'source_urls': {
                'wello': 'https://www.wello.dev/docs',
                'plans': 'https://www.wello.dev/',
                'anthropic': 'https://platform.claude.com/docs/en/about-claude/pricing',
                'openai': 'https://developers.openai.com/api/docs/pricing',
                'openai_legacy_models': 'https://developers.openai.com/api/docs/models/gpt-5.6-luna',
                'zai': 'https://docs.z.ai/guides/overview/pricing'},
            'rates_I_W_H_O_usd_per_million': {
                model: {provider: list(values) for provider, values in rates.items()}
                for model, rates in RATES.items()},
            'comparisons': rows, 'plans': plans}


if __name__ == '__main__':
    (ROOT / 'calculations.json').write_text(json.dumps(calculate(), ensure_ascii=False, separators=(',', ':'))+'\n')
