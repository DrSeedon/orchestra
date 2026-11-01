RATES = {
    "fixture-codex": {
        "fresh": 2.0,
        "cached": 0.5,
        "write": 3.0,
        "output": 8.0,
    }
}


def estimate_cost(model, usage):
    prices = RATES.get(model)
    if prices is None:
        return 0.0
    return (
        usage["fresh_input_tokens"] * prices["fresh"]
        + usage["cache_read_tokens"] * prices["cached"]
        + usage["output_tokens"] * prices["output"]
    )
