# T04 — non-vacuous prompt delivery check

Every clause owned by `source_clauses()` must reach the planner prompt and must not leak into the worker prompt. An earlier `all(...)` test passed when extraction returned an empty list, and a hand-picked anchor list missed a newly added clause.

Write the smallest delivery test. Adding another source clause without leaking it is a valid change; adding and leaking it must fail.

