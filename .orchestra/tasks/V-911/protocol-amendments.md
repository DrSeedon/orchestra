# V-911 amendments
- Pilot (A, rep 1, 24 runs): mean cross-grader coverage 0.483 (Luna 0.354, Sonnet 0.611) <= 0.6 -> ceiling rule not triggered, tasks NOT hardened, pilot rows kept as A rep 1.
- 3 pilot Sonnet runs (S01-S03) failed at start with an infrastructure stdin error (no model output, 0 tokens); rows moved to raw_failed_infra/ and re-run unchanged.
- Main run: 6 more Sonnet runs failed at start with the same stdin error (0 tokens, no output): C-S01..S03 r1, A-S01 r2, C-S01 r2, A-S02 r2; moved to raw_failed_infra/ and re-run unchanged.
