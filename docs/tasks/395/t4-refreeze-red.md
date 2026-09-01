# T4 oracle refreeze

The old fixture premise that an ordinary joined-current query creates a healthy projection is
cancelled: that behavior is the inline repair T4 removes. The fixture now builds the healthy
projection explicitly before corrupting it.

Both corruption arms are non-vacuous: the committed assertions observed exactly one affected row
for `payload` and exactly one affected row for `fts` before the production call.

Command:

```text
/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest -q tests/test_tm_projection_hotpath_395.py::test_t4_stale_current_read_falls_back_without_projection_repair tests/test_tm_projection_hotpath_395.py::test_t4_corrupt_current_data_is_never_served_before_background_validation --timeout=30
```

Output:

```text
FFF                                                                      [100%]
E   Failed: ordinary read attempted O(N) projection repair
E   Failed: corrupt ordinary read attempted inline projection repair
E   Failed: corrupt ordinary read attempted inline projection repair
=========================== short test summary info ============================
FAILED tests/test_tm_projection_hotpath_395.py::test_t4_stale_current_read_falls_back_without_projection_repair
FAILED tests/test_tm_projection_hotpath_395.py::test_t4_corrupt_current_data_is_never_served_before_background_validation[payload]
FAILED tests/test_tm_projection_hotpath_395.py::test_t4_corrupt_current_data_is_never_served_before_background_validation[fts]
3 failed in 7.22s
```

RC: `1`
