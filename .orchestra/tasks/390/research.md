# #390 — Turbovec на реальном RAG Orchestra

Дата: 24.08.2026. Исследование + read-only local pilot. Production index, service, dependencies,
configuration and code path не менялись.

## Вердикт

**Turbovec полезен и заслуживает implementation pilot, но только в 4-bit режиме и не раньше
контракта typed knowledge/projection из #388.**

На реальном корпусе Orchestra кандидат:

- уменьшил persisted vector payload проекта с 140,947,456 B FP32 до 20,277,926 B — **6.95×**;
- ускорил hybrid retrieval stage без embedding с paired baseline 360.7 ms до 128.0 ms —
  median paired speedup **2.63×**;
- сохранил exact sqlite-vec top-1 и top-5 внутри candidate top-20 на 18/18 queries для файлов
  и логов;
- сохранил текущие fact recall@5, canonical path recall@5 и task-success proxy на frozen
  18-query holdout;
- построил и записал два project indexes примерно за 3.0 s.

2-bit ещё меньше (10,399,206 B, 13.55×), но даёт только 12 ms дополнительного retrieval gain
и снижает top-20 overlap с exact ranking с 94–96% до 80.6%. Для production knowledge search
этот trade-off не оправдан.

## Что за проект

[RyanCodrai/turbovec](https://github.com/RyanCodrai/turbovec) — независимая MIT-реализация
Google Research TurboQuant с Rust core и Python bindings. Google создала алгоритм, но не библиотеку.

Проверена current main revision ccab9f325e6ce2a270a87daf01ae4e443bcf2d49, релиз 1.0.0
от 18.08.2026. Присланный screenshot с PyPI 0.7.0 / crate 0.8.0 уже устарел.

Первый stable release закрепляет on-disk v7 и incremental sync. Changelog показывает серьёзный
correctness audit, но одновременно перечисляет много долгоживущих исправленных дефектов:
concurrent search/delete stalls, memory doubling after load+small add, corrupt warm save,
batch-query drops, fork deadlocks and integration-store races. Это аргумент за shadow rollout,
не против проекта.

Алгоритм основан на [TurboQuant paper](https://openreview.net/attachment?id=tO3ASKZlok&name=pdf),
принятом на ICLR 2026. Библиотечные FAISS claims принадлежат автору Turbovec; они не являются
benchmark Google.

## Поправки к пересказу

1. **Compression не ровно 8×/16×.** На наших 1024d и IdMap overhead получено 6.95× в 4-bit
   и 13.55× в 2-bit.
2. **3.4–3.5× относится к ANN kernel benchmark на AVX-512/ARM.** Наш VPS — AMD EPYC AVX2,
   без AVX-512. Прямой перенос screenshot некорректен.
3. **На нашей машине всё равно есть выигрыш:** полный vector+FTS+RRF stage без embedding
   ускорился медианно 2.63×.
4. **No train step — да, но TQ+ calibration есть.** Для лучшего recall вызван calibrate на
   representative 1,024-vector sample. Это не k-means/codebook training и занимает доли секунды.
5. **Incremental save действительно есть только в v7/1.0.** Первый sync claims/rebuilds файл,
   последующие пишут redo delta.
6. **Stable IDs — отдельный IdMapIndex.** Positional TurboQuantIndex swap-remove меняет slots.

## Current Orchestra baseline

### Corpus

Текущий data/vec.db:

- file vectors: 35,934, из них project Orchestra 19,123;
- log vectors: 27,788, из них project Orchestra 15,288;
- dimension: 1,024, normalized bge-m3 embeddings;
- all-project vector chunks on disk: about 360 MB;
- full vec.db: 519 MB + 7.6 MB WAL;
- project Orchestra raw FP32 vectors loaded for pilot: 140,947,456 B.

VPS: 8-vCPU AMD EPYC virtual CPU, AVX2 yes, AVX-512 no. Main service RSS at observation was
2.76 GB, but MemAvailable was 17.0 GB; memory pressure is not currently a blocker.

### Current latency

Five live API searches measured 357–606 ms total.

A separate alternating sqlite-vec scan over the project partition measured medians:

- files: 99.7 ms;
- logs: 49.0 ms;
- vector legs combined: 148.7 ms.

The final frozen pilot measures the whole hybrid stage (two vector scans + two FTS scans + RRF +
row fetch), while replacing only the vector scans. Query embedding is precomputed and excluded so
the candidate cannot claim improvement from ONNX noise.

## Method

Artifacts:

- bench.py — read-only runner;
- evidence/results.json — hashes/ids/ranks/timings, no retrieved text;
- frozen holdout: docs/tasks/256/eval/holdout.jsonl, 18 queries;
- Turbovec package 1.0.0 installed only under a /tmp target.

For each 4-bit/2-bit candidate:

1. Read exact current vectors from sqlite-vec in readonly mode.
2. Split files/logs exactly like production RRF.
3. Build one IdMapIndex per source kind for project Orchestra only.
4. TQ+ calibrate on deterministic random 1,024-vector sample.
5. Persist both indexes.
6. Precompute 18 bge-m3 query embeddings once.
7. For each query rotate baseline/candidate/baseline-control order.
8. Keep current FTS, RRF, metadata lookup and result shaping unchanged.
9. Compare exact vector top-20 agreement and final retrieval anchors.

The paired baseline control is necessary: page-cache/runtime noise is material. Treatment gain is
reported beside median absolute A/A difference, not as an unqualified benchmark.

## Results

### Size/build/startup

| Measure | 4-bit | 2-bit |
|---|---:|---:|
| persisted files+logs | 20,277,926 B | 10,399,206 B |
| compression vs 140,947,456 B FP32 | 6.95× | 13.55× |
| calibration | 0.380 s | 0.100 s |
| add all 34,411 vectors | 1.715 s | 0.859 s |
| durable write | 0.944 s | 0.156 s |
| load medians, file/log | 30.7 / 15.7 ms | 7.7 / 12.7 ms |
| first search medians, file/log | 4.0 / 3.6 ms | 2.1 / 1.8 ms |

One extra 4-bit vector after the initial sync persisted in 22.7 ms on the temp index. This is a
single warm measurement, not a general incremental-save distribution.

### Hybrid latency excluding embedding

| Measure | 4-bit | 2-bit |
|---|---:|---:|
| paired baseline median | 360.7 ms | 307.1 ms |
| candidate median | 128.0 ms | 115.9 ms |
| median paired gain | 213.5 ms | 173.1 ms |
| median speedup | 2.63× | 2.60× |
| median absolute A/A delta | 77.6 ms | 27.7 ms |

In both arms the measured gain is larger than local A/A noise. End-to-end production gain remains
unmeasured: live total also includes query embedding, executor scheduling and HTTP. Directional
expectation is roughly 170–214 ms saved per search, not a guaranteed 3.5× API speedup.

### Vector agreement with exact sqlite-vec

| Layer | 4-bit | 2-bit |
|---|---:|---:|
| file exact top-1 inside candidate top-20 | 18/18 | 18/18 |
| file exact top-5 coverage inside candidate top-20 | 100% | 100% |
| file mean overlap@20 | 94.2% | 80.6% |
| log exact top-1 inside candidate top-20 | 18/18 | 18/18 |
| log exact top-5 coverage inside candidate top-20 | 100% | 100% |
| log mean overlap@20 | 95.6% | 80.6% |

### Final hybrid retrieval

Current live-corpus baseline in this run:

- fact recall@5: 10/18 = 55.6%;
- canonical path recall@5: 9/18 = 50.0%;
- task-success proxy: 10/18 = 55.6%;
- MRR@5: 0.3120;
- stale contradiction: 0/6.

Both 4-bit and 2-bit preserved the first three metrics and zero stale contradictions. MRR moved to
0.3398 (4-bit) and 0.3370 (2-bit), but n=18 and rank changes are too small to claim quality gain.
The correct claim is **no observed regression on this holdout**.

## Integration fit

Turbovec should replace only vec_files/vec_logs ANN storage/search. Keep:

- SQLite files/file_chunks/logs_indexed/log_chunks as metadata and rebuild source;
- FTS5;
- current RRF;
- project authorization;
- canonical Git/typed projection design from #388.

Recommended layout:

- one 4-bit .tvim per (project, files/logs);
- chunk_id as stable u64 IdMap ID;
- log kind filtering via SQL-produced allowlist or per-kind subindexes;
- one writer executor/lock; concurrent reads;
- manifest with schema/model/dim/bit-width/project/source-kind/generation;
- target_head/indexed_head and rebuild-from-text on mismatch;
- candidate index written/synced first, generation manifest committed last.

The index is derived. If sync fails, search must either use the last proven generation or fall back
to exact/FTS; it must never claim the missing generation is current. Keeping raw FP32 vectors would
erase the compression win, so rebuild should re-embed canonical chunks when necessary.

## Risks

- 1.0.0 is only six days old at the observation date.
- Separate .tvim files remove SQLite's current single-transaction vector+metadata update.
- Approximate ranking can affect RRF on unseen queries; n=18 is not a population proof.
- Per-project files simplify isolation but add lifecycle/reconciliation work.
- Current tests use a same-author holdout and mechanical task proxy, not cold-agent task success.
- Fork/thread/restart behavior needs an Orchestra-specific mutation suite.
- Full vec.db size will not fall by 6.95× because FTS, text and metadata remain.

## Decision

**Keep as an approved backend candidate; do not deploy immediately.**

When #388 reaches a plan, include Turbovec 4-bit as the proposed vector projection backend and
freeze an exact sqlite-vec fallback. Required implementation gates:

1. current 18 cases + a larger blinded retrieval set: no per-row regression;
2. zero cross-project leakage;
3. add/update/delete/restart/crash/generation mutations;
4. A/A + interleaved live API latency;
5. memory/RSS/page-cache measurements, not disk only;
6. clean rollback to sqlite-vec;
7. current index remains production until the candidate generation proves complete.

2-bit is rejected for the first rollout: it buys only 9.9 MB more on this project and about 12 ms
more candidate speed while losing roughly 14 percentage points of top-20 overlap.

## Confidence

- Library identity/version/license/API: confirmed.
- Current corpus/size and exact sqlite-vec latency: confirmed local measurements.
- 4-bit candidate size/build/paired retrieval latency: confirmed on one VPS run with A/A controls.
- No observed holdout regression: confirmed for n=18 only.
- Production task success/RSS/end-to-end gain: uncertain until integrated shadow mode.
