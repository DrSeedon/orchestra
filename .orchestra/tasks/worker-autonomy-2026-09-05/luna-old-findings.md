# Strategy A vs. B: local experiment findings

## Conclusion

In the supplied observations, A was faster: its mean wall-clock time was **5.0 s** across three trials, versus **10.0 s** for B. That is an observed difference of **5.0 s** and an observed 50% lower mean time for A (A/B = 0.50, or B took 2× A's mean time).

The experiment does **not** establish that strategy A causes the speedup. B was run first while another CPU-heavy job was active, and A was run later after that job ended. The strategy and CPU-load conditions therefore changed together, so the timing difference is confounded by system load.

## Supporting observations

The supplied `measurements.csv` contains three trials per strategy:

| Strategy | Times (s) | Mean (s) | Median (s) | Range (s) | Sample SD (s) | Mean load average |
|---|---:|---:|---:|---:|---:|---:|
| B | 9.8, 10.2, 10.0 | 10.0 | 10.0 | 9.8–10.2 | 0.2 | 8.233 |
| A | 5.0, 5.2, 4.8 | 5.0 | 5.0 | 4.8–5.2 | 0.2 | 1.033 |

The mean load average was **7.2 higher for B** (8.233 vs. 1.033). Both strategies returned the same output on the supplied tiny input, according to `experiment.md`; `strategy.py` shows `sorted(items)`, but the local evidence does not identify distinct A and B implementations.

## What the observations show vs. causal claim

- **Observed:** The recorded A trials are all about five seconds; the recorded B trials are all about ten seconds. The three-trial ranges do not overlap.
- **Observed:** The B trials occurred under materially higher recorded load and before the A trials.
- **Not shown:** Whether A is intrinsically faster than B under equal CPU-load, order, warm-up, and input conditions.
- **Causal claim:** “A is faster because of its strategy” is unsupported by this experiment. The load/order explanation remains viable, as does an interaction between load and strategy.

## Limitations

- Only three trials per strategy were supplied; there is no uncertainty estimate robust enough for general performance claims.
- The input was one tiny input, so scaling with input size or shape is unknown.
- Execution order was not randomized or counterbalanced.
- The CPU-heavy job was present for B and absent for A; this is a direct confound.
- No per-trial CPU time, processor affinity, warm-up state, cache state, background-process details, or measurement harness details were supplied.
- Equal output does not prove equal behavior or comparable work on other inputs.

## What should be measured next

1. Run A and B in the same controlled environment with the CPU-heavy job absent; record background load and CPU utilization for every trial.
2. Randomize or alternate strategy order (for example, ABBA/BABA blocks) so elapsed time is not coupled to experiment phase; include warm-up runs and analyze only steady-state trials.
3. Test representative input sizes and shapes, including edge cases, with enough repeated trials to report distributions (median and percentiles, not only means).
4. Record wall-clock time and process CPU time per trial, plus environment/hardware and implementation identifiers.
5. Define the primary comparison before rerunning: difference in median steady-state time at each input size, with a predeclared tolerance and uncertainty method.
