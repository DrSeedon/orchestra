# Frontend refactor A/B measurements

Input: local http://127.0.0.1:8888, mocked API, fresh browser context per run.
Order: baseline/current alternating; user-visible endpoint: selectedAgent == fe-orch.

```json
{
  "runs": [
    {
      "run": 1,
      "variant": "baseline",
      "ready_ms": 216.1,
      "loadavg": [
        "2.74",
        "2.60",
        "2.44"
      ],
      "executed_variant": "baseline",
      "page_errors": []
    },
    {
      "run": 2,
      "variant": "current",
      "ready_ms": 136.3,
      "loadavg": [
        "2.74",
        "2.60",
        "2.44"
      ],
      "executed_variant": "current",
      "page_errors": []
    },
    {
      "run": 3,
      "variant": "baseline",
      "ready_ms": 132.5,
      "loadavg": [
        "2.74",
        "2.60",
        "2.44"
      ],
      "executed_variant": "baseline",
      "page_errors": []
    },
    {
      "run": 4,
      "variant": "current",
      "ready_ms": 134.1,
      "loadavg": [
        "2.74",
        "2.60",
        "2.44"
      ],
      "executed_variant": "current",
      "page_errors": []
    },
    {
      "run": 5,
      "variant": "baseline",
      "ready_ms": 148.2,
      "loadavg": [
        "2.74",
        "2.60",
        "2.44"
      ],
      "executed_variant": "baseline",
      "page_errors": []
    },
    {
      "run": 6,
      "variant": "current",
      "ready_ms": 128,
      "loadavg": [
        "2.74",
        "2.60",
        "2.44"
      ],
      "executed_variant": "current",
      "page_errors": []
    },
    {
      "run": 7,
      "variant": "baseline",
      "ready_ms": 105.7,
      "loadavg": [
        "2.74",
        "2.60",
        "2.44"
      ],
      "executed_variant": "baseline",
      "page_errors": []
    },
    {
      "run": 8,
      "variant": "current",
      "ready_ms": 138.2,
      "loadavg": [
        "2.74",
        "2.60",
        "2.44"
      ],
      "executed_variant": "current",
      "page_errors": []
    },
    {
      "run": 9,
      "variant": "baseline",
      "ready_ms": 138,
      "loadavg": [
        "2.74",
        "2.60",
        "2.44"
      ],
      "executed_variant": "baseline",
      "page_errors": []
    },
    {
      "run": 10,
      "variant": "current",
      "ready_ms": 136.3,
      "loadavg": [
        "2.74",
        "2.60",
        "2.44"
      ],
      "executed_variant": "current",
      "page_errors": []
    },
    {
      "run": 11,
      "variant": "baseline",
      "ready_ms": 106.3,
      "loadavg": [
        "2.74",
        "2.60",
        "2.44"
      ],
      "executed_variant": "baseline",
      "page_errors": []
    },
    {
      "run": 12,
      "variant": "current",
      "ready_ms": 174.6,
      "loadavg": [
        "2.74",
        "2.60",
        "2.44"
      ],
      "executed_variant": "current",
      "page_errors": []
    }
  ],
  "summary": {
    "baseline": {
      "n": 6,
      "median_ms": 135.25,
      "min_ms": 105.7,
      "max_ms": 216.1
    },
    "current": {
      "n": 6,
      "median_ms": 136.3,
      "min_ms": 128,
      "max_ms": 174.6
    },
    "delta_median_ms": 1.05,
    "delta_median_pct": 0.78
  }
}
```
