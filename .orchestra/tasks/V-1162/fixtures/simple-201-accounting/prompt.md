# Task S2 — account for cache writes

Update only `src/accounting.py`. The four usage fields in this fixture are disjoint token classes: fresh input, cached input, cache-write input, and output. Calculate total cost using the frozen synthetic rate table already in the file. Do not change those rates or fetch real provider prices. Reject a model with no rate instead of returning a plausible zero. The acceptance validator checks the formula by behavior, including mixed usage and no-write usage.
