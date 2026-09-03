# Personal memory

- To distinguish SQL `NULL` (unknown) from numeric `0`, do not use `SUM` alone: both give
  the same mixed-sample sum. Assert `COUNT(nullable_column)` plus an explicit unknown-row
  marker, and prove the oracle with a `NULL -> 0` mutation before freezing it.
