# V-896 — frozen protocol (committed before any model run)

Question: on OPEN tasks without a single correct answer, does rewriting the task with Rieseberg's "deeper version"
prompt (arm B) give a better result than the original task (arm A), and at what paid-token price? Arm C = A + one
sentence requiring an external check (kept for comparison). Same B/C texts and rewrite prompt as V-895 (run.py REWRITE,
tasks.py C_SUFFIX). Models: luna, sonnet (Sonnet 5.5). Subscription billing only. Tools as in V-895 (Claude:
Read/Write/Edit/Glob/Grep, no shell; Codex: shell+network as the adapter requires); fixed across arms within a model.

Tasks (tasks.py):
- Research/thinking with verifiable depth (R1 #52 changelog conflicts, R2 #78 base64 images in the journal,
  R3 V-624 pytest killed/hang). Model gets the question and the pre-answer repo snapshot (no .git, no .orchestra, no
  report). Score = blind checklist coverage (6 key findings from the real report, checklist in tasks.py, committed now).
  Both models grade every answer (0/0.5/1 per finding) not knowing the arm; coverage = mean over graders and findings;
  also reported: cross-only (grader model != author model).
- Creative, no reference (K1 explainer script, K2 dashboard feature concept, K3 names + rule wording, K4 message to
  the owner, K5 analogy explanation, K6 name/tagline/pitch). Score = blind pairwise judging A vs B and A vs C. Both
  models judge every pair (judge sees the brief and two texts only), A/B position random (seeded, stored in the grade
  file). Criteria fixed in tasks.py JUDGE_CRITERIA. Win-rate = share of (pair x judge) decisions won by the arm vs A;
  cross-only subset (judge model != author model) reported too. Judge agreement reported.
- Isolation: fresh copy of the snapshot per run, raw output scanned for report paths/task ids/curl/github.

Runs: 9 tasks x 2 models x 3 arms x REP (rep 1 first; rep 2 if quota allows) ; B = rewrite step + execution of the
rewritten prompt only; B tokens = rewrite + execution. Paid tokens = output + cache_create + fresh input (Claude
input_tokens; Codex input - cached - cache_write); cache read not counted (KB V-660). Turns as in V-895.

Ceiling rule (set before any run): pilot = arm A on R1-R3 for both models. If mean A checklist coverage >= 0.85, the
research tasks are too easy to separate arms; they are hardened (extra sub-question) BEFORE the main run and the
amendment is recorded in this file with the pilot numbers. The same is checked for creative tasks only through the
judge: a task where A wins/loses 100% of decisions is reported as non-informative.

Decision rule: B is judged useful if research coverage(B) - coverage(A) >= +0.10 AND creative win-rate of B over A
>= 0.60 with the bootstrap 95% CI lower bound > 0.5, AND paid tokens(B) <= 1.2 x A. Otherwise "not shown". Cost is
reported regardless. Significance: n of cells, spread, minimum detectable effect are stated in the report; an effect
inside noise is called noise.

Blind set for the owner: 4 creative pairs (A vs B) drawn at random (seed 896) from distinct creative tasks, letters
random, key stored separately (owner_blind/key.json).
