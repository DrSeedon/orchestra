# Frontend refactor baseline/baseline noise control

Input: local http://127.0.0.1:8888, mocked API, fresh browser context per run.
Order: baseline/current alternating; user-visible endpoint: selectedAgent == fe-orch.

```json
{
  "runs": [
    {
      "run": 1,
      "variant": "baseline_a",
      "ready_ms": 277.4,
      "loadavg": [
        "3.13",
        "2.70",
        "2.48"
      ],
      "executed_variant": "baseline",
      "page_errors": []
    },
    {
      "run": 2,
      "variant": "baseline_b",
      "ready_ms": 140.3,
      "loadavg": [
        "3.13",
        "2.70",
        "2.48"
      ],
      "executed_variant": "baseline",
      "page_errors": []
    },
    {
      "run": 3,
      "variant": "baseline_a",
      "ready_ms": 133,
      "loadavg": [
        "3.13",
        "2.70",
        "2.48"
      ],
      "executed_variant": "baseline",
      "page_errors": []
    },
    {
      "run": 4,
      "variant": "baseline_b",
      "ready_ms": 133,
      "loadavg": [
        "3.13",
        "2.70",
        "2.48"
      ],
      "executed_variant": "baseline",
      "page_errors": []
    },
    {
      "run": 5,
      "variant": "baseline_a",
      "ready_ms": 140.4,
      "loadavg": [
        "3.13",
        "2.70",
        "2.48"
      ],
      "executed_variant": "baseline",
      "page_errors": []
    },
    {
      "run": 6,
      "variant": "baseline_b",
      "ready_ms": 99.7,
      "loadavg": [
        "3.13",
        "2.70",
        "2.48"
      ],
      "executed_variant": "baseline",
      "page_errors": []
    },
    {
      "run": 7,
      "variant": "baseline_a",
      "ready_ms": 144.7,
      "loadavg": [
        "3.13",
        "2.70",
        "2.48"
      ],
      "executed_variant": "baseline",
      "page_errors": []
    },
    {
      "run": 8,
      "variant": "baseline_b",
      "ready_ms": 137.4,
      "loadavg": [
        "3.13",
        "2.70",
        "2.48"
      ],
      "executed_variant": "baseline",
      "page_errors": []
    },
    {
      "run": 9,
      "variant": "baseline_a",
      "ready_ms": 100.2,
      "loadavg": [
        "3.13",
        "2.70",
        "2.48"
      ],
      "executed_variant": "baseline",
      "page_errors": []
    },
    {
      "run": 10,
      "variant": "baseline_b",
      "ready_ms": 146.3,
      "loadavg": [
        "3.13",
        "2.70",
        "2.48"
      ],
      "executed_variant": "baseline",
      "page_errors": []
    },
    {
      "run": 11,
      "variant": "baseline_a",
      "ready_ms": 139.2,
      "loadavg": [
        "3.13",
        "2.70",
        "2.48"
      ],
      "executed_variant": "baseline",
      "page_errors": []
    },
    {
      "run": 12,
      "variant": "baseline_b",
      "ready_ms": 130,
      "loadavg": [
        "3.13",
        "2.70",
        "2.48"
      ],
      "executed_variant": "baseline",
      "page_errors": []
    }
  ],
  "summary": {
    "baseline_a": {
      "n": 6,
      "median_ms": 139.8,
      "min_ms": 100.2,
      "max_ms": 277.4
    },
    "baseline_b": {
      "n": 6,
      "median_ms": 135.2,
      "min_ms": 99.7,
      "max_ms": 146.3
    },
    "delta_median_ms": -4.6,
    "delta_median_pct": -3.29
  }
}
```
