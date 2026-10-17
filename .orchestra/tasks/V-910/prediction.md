# V-910 prediction (written before any run; author: Sonnet 5.5 worker)

My expectation, to be compared with the result, not a hypothesis I am trying to confirm:

- A (agent + topic index + rg, ≤3 search calls) on the 28 paraphrase questions: strict hit ≈ 60–75%. Reason: the index names the topic files, the 10 KB files are small enough to read after one rg, but the 313 task reports have no index, Russian morphology breaks `rg -F` on inflected words, and 3 search calls cut the retry loop.
- B (bge-m3 + FTS5 + RRF, chunk top-5, file-level hit) on the same questions: ≈ 80–90%.
- Expected difference B − A ≈ +10…+20 pp; I put ~35% on the pre-registered rule (≥ +20 pp and one-sided p < 0.05) being met. The most likely single outcome: a real but sub-threshold gain concentrated on task-report questions, with A already strong on KB questions.
- Direct-wording (D) questions: A ≈ B ≈ 90%+. Replaced-conclusion (S) questions: both retrieve the file, but only A can say which conclusion is in force, B cannot.
- Luna vs Sonnet in A: Luna runs real `rg` in a shell, Sonnet only Grep/Glob/Read tools; no confident prediction on which is better.
