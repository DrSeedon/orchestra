# T3b pre-change evidence — excluded from final acceptance

This artifact preserves the evidence that motivated the first T3b correction without making
pre-change implementation details executable acceptance requirements.

The oracle frozen as worker commit
`21e1b0718f8e8c3d30a06c2762b9d8257c815df4` (squashed main equivalent `b693f302`) is
permanently superseded and excluded. Its test and fixtures remain unchanged for audit history:

- `test_t3b_agent_only_knowledge_behavior.py` Git blob
  `6dc53cae01561cb5c0abfbafc44d43c6116cb2ab`;
- `t3b_agent_only_contract.json` Git blob
  `a2ba57700070bb74b73923f9c476f5ad469dba71`;
- `t3b_agent_only_records.json` Git blob
  `2eecda71ffe9b1b77aa9bf39a2fa6e9521ac69e0`;
- records fixture SHA-256
  `6a66d6352c2e0105f2bbb50426838e87e8c1834a0643c196996531d16c6ab5a7`.

On the pre-change implementation, the original T3 command returned `18 passed in 0.31s`.
`KnowledgeService._write_topic_documents()` had two production call sites; constructing the
two-topic registry produced three Markdown files and promoting the new-topic scenario produced
four. The then-current implementation SHA-256 values were:

- `app/ia/knowledge.py`:
  `d2be14f9730df77e0d80881bae4af3df4b999ad3c432d1211c1a8c815459f72a`;
- `app/ia/evidence.py`:
  `5f3c953a982472c65a9295c0e2119222dadb6ecb5eb3c3f8ec2999d4d54f6aa4`;
- `app/ia/events.py`:
  `5914cd5c6e0816a035c2f21f61024c089b8c20fb62f0f0be809e3746fbc352d0`.

The first oracle's controls returned `3 passed in 0.13s`; its full command returned
`6 failed, 3 passed in 0.24s`, first failing because
`app.ia.knowledge.knowledge_api is not callable`.

These values prove the old conflict and are not selected by the corrected T3b command. A correct
implementation necessarily changes `app/ia/knowledge.py` and changes the generated Markdown count
from `3 → 4` to `0 → 0`; therefore neither the old file SHA nor the old generated-output count can
be a final invariant.
