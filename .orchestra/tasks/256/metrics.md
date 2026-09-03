# #256 — metrics, fresh holdout and current baseline

## 1. Frozen holdout

The retrieval holdout was written before its first execution and then hashed:

```text
file: docs/tasks/256/eval/holdout.jsonl
sha256: 9e7c737dd5f58a91572e49a25cb80861b13b28fee12a3bbd392fd1c0579e466b
n: 18 = 6 exact + 6 current + 6 rejected
top-k: production-shaped k=5
```

Each row contains an unseen query relative to #133/#135/#138, a canonical source path, one literal
gold anchor and (for current-state cases) literal stale anchors. The runner records only result metadata,
ranks and content hashes; retrieved log text is not persisted.

This is **fresh but not independently blind**: the researcher authored queries after reading the
knowledge base, and n=6 per class is a diagnostic, not a population estimate. The holdout is suitable
for regression and mechanism checks, not a leaderboard claim. It must remain immutable after this run;
future changes create `holdout-v2`, never rewrite v1.

## 2. Exact metric definitions

| Metric | Unit / denominator | Mechanical definition | Why primary or diagnostic |
|---|---|---|---|
| exact recall | exact rows | Fraction where any top-5 chunk contains the frozen literal anchor. | Primary retrieval capability for paths, commands, symbols and exact values. |
| current-state recall | current rows | Fraction where current anchor appears in top-5. | Primary, but incomplete without contradiction rate. |
| rejected-approach recall | rejected rows | Fraction where the rejected finding appears in top-5. | Primary for avoiding already-closed roads. |
| stale contradiction rate | current rows | Fraction where any top-5 chunk contains a frozen stale anchor. | Primary; lower is better. A current hit plus stale hit is not success. |
| provenance accuracy | rows with fact hit | Fraction whose matching fact comes from the frozen canonical path. Result source ID must also be present for every returned item. | Primary audit property. This is stricter than “some source exists”. |
| time to first useful fact | per query | Wall time of the read-only `/api/memory/search` call; report median/p95/max. | Operational primary, but machine-load sensitive. Future A/B must alternate arms and print loadavg. |
| tool calls to first useful fact | protocol count | Retrieval-only = 1. Current cold gate = README read + retrieval = 2; `pwd` is setup, not knowledge lookup. | Primary agent-cost metric; #345 measured marginal tool calls as expensive. |
| tokens to first useful fact | per successful query | Exact tokenizer was unavailable. Raw artifact records characters before first anchor and an explicitly labelled `ceil(chars/3)` Russian/mixed-text proxy. | Diagnostic only until runtime tokenizer counting exists. |
| top-k recall / MRR | all/class rows | R@1/R@3/R@5 and mean reciprocal rank of first anchor. | Retrieval diagnostics only; they cannot detect a fluent but stale answer or task success. |
| answer utility / task success | end-to-end cold tasks | Primary future measure: frozen task AC completed by a blank agent using the returned evidence. Current local run uses only `anchor present AND, for current, no stale anchor` as a mechanical proxy. | Headline outcome once an external-model eval is explicitly authorized. Proxy is not a substitute. |
| duplicate-topic rate | topic registry | Duplicate README targets plus cross-topic exact duplicate claim lower bound; semantic duplicates need manual adjudication. | Structural diagnostic. Exact strings undercount paraphrases. |
| orphan rate | topic/research rows | (a) topic files absent from README / all topic files; (b) changed research paths since KB-contract commit absent from every KB source section / denominator. | Primary write-path outcome. |
| source-link coverage | changed research rows since contract | Fraction whose exact `docs/tasks/.../research.md` path appears anywhere in `docs/kb/*.md`, including `## Источники`. | Current structural proxy only. Presence does not prove an atomic conclusion was integrated. |
| promotion recall | frozen atomic conclusions | Fraction whose expected `fact_id`/anchor is integrated into the expected canonical topic with evidence and is retrievable in the required mode. | Primary write-path metric. Historical facts lack IDs/anchors, so the current value is **UNMEASURED**. |
| integration/freshness lag | revisions + time | Target Git HEAD/knowledge generation minus structured/FTS/vector projection generation, plus wall time until catch-up. | Primary. Current system lacks generation/timestamps, so only debt count/coverage is measurable. |
| false supersession | promotion scenarios | Fraction of still-valid facts retired by an unrelated/additive finding. | Zero-tolerance primary safety metric. Graphiti issue #1728 shows why semantic invalidation is unsafe. |
| prompt footprint | bytes and runtime tokens | Bytes always injected for the memory module/topic registry; report full prompt tokens separately when runtime usage is available. | Primary cost guard. Do not trade one saved lookup for an unbounded biography. |

## 3. Current baseline (direct measurement)

Commands:

```bash
python3 docs/tasks/256/eval/audit_structure.py \
  --worktree "$PWD" \
  --scope-root /mnt/data/Projects/Python/orchestra \
  --vec-db /mnt/data/Projects/Python/orchestra/data/vec.db \
  --output docs/tasks/256/eval/structure.raw.json

python3 docs/tasks/256/eval/run_baseline.py \
  --holdout docs/tasks/256/eval/holdout.jsonl \
  --output docs/tasks/256/eval/baseline.raw.json \
  --scope /mnt/data/Projects/Python/orchestra \
  --limit 5
```

### Retrieval results

| Metric | All | Exact | Current | Rejected |
|---|---:|---:|---:|---:|
| n | 18 | 6 | 6 | 6 |
| fact recall@5 | **38.9%** | 33.3% | 33.3% | 50.0% |
| canonical path recall@5 | **33.3%** | 16.7% | 16.7% | 66.7% |
| task-success proxy | **33.3%** | 33.3% | **16.7%** | 50.0% |
| MRR@5 | **0.2287** | 0.2222 | 0.2000 | 0.2639 |
| recall@1 | 16.7% | 16.7% | 16.7% | 16.7% |
| recall@3 | 27.8% | 33.3% | 16.7% | 33.3% |

Additional measurements:

- stale contradiction rate on current queries: **1/6 = 16.7%**;
- canonical provenance accuracy conditional on a fact hit: **5/7 = 71.4%**;
- cross-project result leakage with `cross_project=false`: **0/18**;
- latency: median **335.6 ms**, nearest-rank p95/max **682.8 ms**;
- median content before first matching fact: **1,209 characters**, token proxy **403**;
- all calls reported `pending_files=545`; the baseline observed `indexing=true`, so the raw artifact
  identifies the actual live state rather than pretending the corpus was frozen.

### Structure, promotion and freshness

| Metric | Current value | Counting rule |
|---|---:|---|
| topic registry coverage | 11/12 = **91.7%** | One topic file, `dashboard-quota-map.md`, is absent from README. |
| orphan topic-file rate | 1/12 = **8.3%** | Unlisted topic files / all non-README topic files. |
| source-link coverage since KB contract | 7/12 = **58.3%** | Research paths changed from README creation commit `937b513e…` (inclusive) through HEAD; linked iff exact path appears anywhere in a KB file. |
| unlinked research rate | 5/12 = **41.7%** | Complement of source-link coverage; paths are retained in raw JSON. This is not semantic orphan adjudication. |
| semantic promotion recall | **UNMEASURED** | A path in `## Источники` does not prove a particular conclusion was integrated; historical atomic fact IDs/anchors do not exist. Valid-promotion recall can be no higher than the 58.3% source-link proxy if a source link is mandatory. |
| current index coverage | 547/1,092 = **50.1%** | Current sha256 in `vec.db` / indexable non-ignored Markdown at the same scope. |
| integration debt | **545 files** | 516 missing + 29 stale; exactly matches the service's reported debt. |
| orphaned index paths | **0** | Indexed path missing from current corpus. |
| knowledge prompt footprint | **7,872 bytes** | `memory-search.md` 2,909 + README 4,963. |
| full AGENTS/CLAUDE footprint | **104,695 bytes** | Context only; not all of it belongs to memory discovery. |

Exact cross-topic duplicate-claim lower bound found only the same placeholder “empty rejected section”
in four migrated files. This does **not** establish a low semantic duplicate rate; paraphrases require a
separately blinded audit. The structural baseline proves the orphan mechanism without that subjective step.

## 4. Candidate holdout for the write/promotion seam

The current corpus cannot test a mechanism that does not exist. Before Phase 3, create a read-only fixture
clone and freeze **12 write scenarios**, never production:

| Class | n | Required behavior |
|---|---:|---|
| update existing topic | 3 | Registry routes to exactly one existing topic; no new file; task evidence retained. |
| explicit supersession | 2 | Same `fact_key`, later valid-time and explicit `supersedes`; old row closes and remains historically queryable. |
| rejected approach | 2 | Status becomes `rejected`; default current query suppresses it, rejected-mode query returns it with reason/evidence. |
| additive near-duplicate | 1 | Similar wording but different fact key remains current; false supersession must be zero. |
| disputed values | 1 | Both supported values remain, status `disputed`; no silent winner. |
| refresh-after / TTL | 1 | Expiry produces `stale-needs-validation`, never deletion or automatic rejection. |
| genuine new topic | 1 | New topic and registry/README entry created in one validated commit. |
| orphan trap | 1 | Attempted standalone topic file without registry/evidence is rejected before merge. |

For each scenario record: source/task SHA, expected topic, fact key/status/time, expected current and
historical rows, expected search result, target/projector generation, wall lag and every changed artifact.
Run mutations that remove topic registration, evidence FK, supersedes guard and projection watermark;
each must make the check fail.

## 5. Pre-registered candidate gate

No aggregate may hide a safety failure. A candidate proceeds only if:

1. all 18 frozen retrieval cases satisfy their per-row rule; current rows also have no stale anchor;
2. all 12 promotion scenarios pass; promotion recall 12/12, orphan rate 0/12, false supersession 0/12;
3. every returned fact carries canonical path, fact ID, source commit/blob and status/time;
4. structured read-after-write reaches the merge commit generation in the same operation; vector lag may
   remain asynchronous only if `target_head/indexed_head` is returned and search falls back to canonical facts;
5. project isolation rejects an unauthorized cross-project request; it is not enough to run with
   `cross_project=false`;
6. the compact hot registry plus memory procedure does not exceed the current **7,872-byte** footprint
   except by the literal one-line entries for genuinely new topics;
7. latency/tool/tokens are reported A/B/A/B against the frozen baseline. They are diagnostics, not grounds
   to waive correctness;
8. end-to-end answer utility/task success remains **unmeasured** until a cold-agent run is separately
   authorized. No local anchor proxy may be relabelled as model task success.

## 6. Raw artifacts and limitations

- [`holdout.jsonl`](./eval/holdout.jsonl) — frozen questions and gold metadata.
- [`run_baseline.py`](./eval/run_baseline.py) — read-only runner; stores no retrieved text.
- [`baseline.raw.json`](./eval/baseline.raw.json) — per-query result metadata and hashes.
- [`verify_receipts.py`](./eval/verify_receipts.py) and [`receipts.raw.json`](./eval/receipts.raw.json) — read-only recomputation of all 90 result hashes/anchor flags against the live index; 90/90 resolved and matched.
- [`audit_structure.py`](./eval/audit_structure.py) — reproducible topic/promotion/index audit.
- [`structure.raw.json`](./eval/structure.raw.json) — exact inventories, including all debt/orphan paths.

Limitations: same-author gold, n=6/class, live index rather than frozen DB, approximate token count,
and non-self-contained retrieval receipts. `receipts.raw.json` proves that all 90 result hashes and flags
recomputed against the live DB after the run, but the 610 MiB DB snapshot is not committed and later updates
can remove those chunks. These limits lower confidence in absolute retrieval quality but do not weaken the
directly counted 545-file debt, 1 unlisted topic, or 5 unlinked research paths.
