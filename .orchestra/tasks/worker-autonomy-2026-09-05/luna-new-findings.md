# Findings

## Conclusion

In the supplied experiment, A was faster in observed wall-clock time: its mean and
median were 5.0 s versus 10.0 s for B (a 5.0 s, or 50%, lower mean). This is an
observation about these six runs, not evidence that A is intrinsically faster than B.
The experiment cannot separate strategy from the CPU-load and ordering conditions.

## Observations

The raw measurements were:

| Strategy | Trials (s) | Mean (s) | Median (s) | Sample SD (s) | Loadavg mean |
|---|---:|---:|---:|---:|---:|
| B | 9.8, 10.2, 10.0 | 10.0 | 10.0 | 0.2 | 8.23 |
| A | 5.0, 5.2, 4.8 | 5.0 | 5.0 | 0.2 | 1.03 |

The experiment notes that B ran first during another CPU-heavy job, while A ran later
after that job ended. Both strategies produced the same output on the supplied tiny
input; no other inputs were tested.

## Causal interpretation

The measurements support the limited claim “A completed faster under the recorded A
conditions than B under the recorded B conditions.” They do not support the causal
claim “A is faster because of its strategy.” The competing explanation that the
CPU-heavy job and the associated loadavg increased B's elapsed time remains viable;
the run order is perfectly confounded with strategy, so the three trials do not provide
an independent A/B comparison under the same workload conditions.

## Limitations and counter-evidence

- Only three trials per strategy were recorded, all in one order (B then A).
- Loadavg differed substantially: B's values were 8.0, 8.5, and 8.2; A's were 1.0,
  1.2, and 0.9. This is a direct alternative explanation for the 5.0 s gap.
- The input was tiny and identical-output equivalence was checked only there; relative
  performance may change with input size, shape, or output requirements.
- No paired, randomized, or interleaved runs were performed, and no CPU, memory,
  cache, thermal, or background-process controls were recorded.
- The provided `strategy.py` contains one `strategy(items)` implementation returning
  `sorted(items)`; it does not expose separate A/B implementations from which an
  algorithmic cause could be established.

## What to measure next

1. Run A and B in randomized or alternating order, with the competing CPU-heavy job
   removed or held constant; record per-run loadavg and background-process state.
2. Use the same machine state and repeated identical inputs for both strategies,
   including small, medium, and large inputs representative of the intended workload.
3. Increase repetitions enough to estimate run-to-run variance; report median, spread
   (for example, interquartile range), and the per-run paired A-minus-B differences.
4. Confirm that the implementations and output-validation work are identical apart
   from the strategy under test, and record CPU time in addition to wall-clock time.
