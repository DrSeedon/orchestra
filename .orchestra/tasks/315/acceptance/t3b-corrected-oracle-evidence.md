# T3b v2 corrected oracle evidence

Date: 2026-08-25. No production, application-test, database, service, provider, model, eval or
review call was made while freezing this oracle.

## Selection

The full gate selects 26 nodes: 17 original T3 nodes, 3 invariant T3b controls and 6 corrected
T3b behavior nodes. Original T3 S11 is the only deselected node. Its structured new-topic behavior
is replaced by the corrected T3b node; its README/topic assertions stay excluded.

## Positive controls

Command:

```text
uv run python -m pytest docs/tasks/315/acceptance/test_t3b_agent_only_knowledge_behavior_v2.py::test_t3b_v2_control_fixture_counts_hashes_and_detectors_are_invariant docs/tasks/315/acceptance/test_t3b_agent_only_knowledge_behavior_v2.py::test_t3b_v2_control_reference_import_preserves_historical_paths_and_bytes docs/tasks/315/acceptance/test_t3b_agent_only_knowledge_behavior_v2.py::test_t3b_v2_control_real_t1_t2_t3_structured_behavior_is_preserved -q
```

Exact output:

```text
...                                                                      [100%]
3 passed in 0.14s
```

## Pre-implementation RED

Command:

```text
uv run python -m pytest docs/tasks/315/acceptance/test_t3_promotion_behavior.py docs/tasks/315/acceptance/test_t3b_agent_only_knowledge_behavior_v2.py --deselect 'docs/tasks/315/acceptance/test_t3_promotion_behavior.py::test_t3_exact_promotion_scenario[S11]' -q
```

Exact summary and exit:

```text
....................FFFFFF                                               [100%]
6 failed, 20 passed, 1 deselected in 0.34s
exit 1
```

The replacement S11 node fails at the behavioral assertion
`{path.suffix.lower() for path in files} <= {".json"}` with observed suffixes
`{'.json', '.md'}`. The other five behavior nodes fail at
`#315 T3b missing behavior: app.ia.knowledge.knowledge_api is not callable`. Collection succeeds;
the selected original T3 nodes and invariant controls are green.

## Frozen hashes

| Artifact | SHA-256 | Git blob before commit |
|---|---|---|
| `test_t3b_agent_only_knowledge_behavior_v2.py` | `131b80464f463662852f4ea56e80c1d5f69a89757011d17e85c9eb5b0e9f4086` | `2cd8d099e461134e6d797f099669960d658e600a` |
| `fixtures/t3b_agent_only_contract_v2.json` | `ca666ca4bf16acf3207d57ddb71784a3aa86791f698573ba625e6fad7221f359` | `7ed1e5722806061d342f0278666f87d7d05540df` |
| `fixtures/t3b_agent_only_records_v2.json` | `e529b731271477abc1899f8c290c6d9d39b4fb580fc1930a3fe675a8343c6746` | `8b44c33ffea6160b88fe08b6d8dcedfc78b10c06` |

`git diff --exit-code HEAD --` against the superseded test and its two fixtures returned exit 0;
the historical oracle at `21e1b071…`/`b693f302` was not modified in place.
