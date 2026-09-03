import json
from math import ceil, sqrt


z_95 = 1.959963984540054
z_80 = 0.8416212335729143
observed_clusters = 8
effect = 0.08450704225352113
ci_low = -0.03809523809523807
ci_high = 0.2018779342723005
noninferiority_margin = 0.02

sigma = ((ci_high - ci_low) / (2 * z_95)) * sqrt(observed_clusters)
clusters = ceil((sigma * (z_95 + z_80) / (effect + noninferiority_margin)) ** 2)
expected_margin = z_95 * sigma / sqrt(clusters)

current_primary_cost = 4.6141015
hot_primary_cost = 1.510749
outputs_per_variant_q4 = 24
sonnet_judge_cost = 2.8305551
judge_fixture_batches_q4 = 8

primary_cost = clusters * 3 * (
    current_primary_cost / outputs_per_variant_q4
    + hot_primary_cost / outputs_per_variant_q4
)
sonnet_cost = clusters * sonnet_judge_cost / judge_fixture_batches_q4
claude_cost = primary_cost + sonnet_cost

print(
    json.dumps(
        {
            "assumed_power": 0.8,
            "new_fixture_clusters": clusters,
            "new_primary_outputs": clusters * 2 * 3,
            "new_sonnet_judge_batches": clusters,
            "new_sol_judge_batches": clusters,
            "estimated_sigma": sigma,
            "expected_95pct_margin": expected_margin,
            "expected_ci_lower": effect - expected_margin,
            "estimated_primary_cost_usd": primary_cost,
            "estimated_sonnet_judge_cost_usd": sonnet_cost,
            "estimated_claude_cost_usd": claude_cost,
            "budget_with_30pct_contingency_usd": claude_cost * 1.3,
        },
        indent=2,
        sort_keys=True,
    )
)
