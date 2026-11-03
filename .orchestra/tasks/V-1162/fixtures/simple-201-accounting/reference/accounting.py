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
        raise ValueError("no published rate for model")
    return (
        usage["fresh_input_tokens"] * prices["fresh"]
        + usage["cache_read_tokens"] * prices["cached"]
        + usage["cache_write_tokens"] * prices["write"]
        + usage["output_tokens"] * prices["output"]
    )
