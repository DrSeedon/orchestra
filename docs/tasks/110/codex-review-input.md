# Bounded adversarial review input for #110

Do not browse, run tools, or inspect other files. Review only the reasoning and
arithmetic below. The main researcher opened the primary artifacts; source
verification is recorded separately in `research.md`.

Return a concise verdict with findings classified BLOCKING/HIGH/MEDIUM/LOW. In
particular, try to falsify the conclusion rather than restate it.

## Claim under review

Ouroboros publishes real benchmark runs and traces, but its 2026-07-31 headline
“SOTA on Terminal-Bench, OSWorld and CL-Bench; beats Codex CLI, Claude Code,
Cursor, Hermes” is not established on 2026-08-01. None of the three official
boards independently lists Ouroboros; TB and CL submissions are open, OSWorld is
absent. The best interpretation is “public author-run candidate”, not “official
SOTA”. Useful Orchestra borrowings are narrow mechanisms, not migration.

## Evidence facts already checked against primary sources

- Terminal-Bench 2.1 has 89 tasks, k=5 = 445 trials.
- Official TB metric code computes accuracy across trials and
  `SE=sqrt((1/n_tasks^2)*sum_i[p_i(1-p_i)/(k_i-1)])`.
- Published graph pairs (`score ± labelled SE`):
  - 86.97±1.6 vs 83.80±1.2
  - 80.22±1.0 vs 78.90±1.3
  - 84.30±1.2 vs 83.10±1.1
  - 84.94±1.1 vs 79.30±1.5
- Public Opus-5 run has 387/445 successes, task distribution
  66×5/5, 11×4/5, 3×3/5, 1×2/5, 2×1/5, 6×0/5.
- From that distribution: official fixed-task SE=0.9795 pp; sample SE of the 89
  task pass-fractions=3.000 pp. Naive Bernoulli treating 445 trials independent
  gives 1.596 pp, matching the graph's 1.6 rather than official formula.
- Baselines Fable/Claude Code, Opus4.8/Claude Code, GPT5.5/Codex and Grok/Cursor
  are official team runs. Ouroboros runs are author runs.
- Config mismatch: Opus5 compares against a different model (Fable5); Ouro
  Opus4.8/GPT5.5 public jobs do not expose exact reasoning effort while official
  baselines are high/xhigh; Ouro Grok is medium while Cursor Grok is high.
- Reward-hack audit mismatch: official Cursor score was independently reduced by
  40 zeroed successes; Ouro Grok author self-zeroed one task×5 after 19 cases were
  flagged; PR remains open.
- Real success, failure and runtime-error trajectories were inspected.
- OSWorld author score is 90.69% vs current official top 90.19%, 361 tasks, one
  rollout; Ouro absent from official workbook.
- CL author score .2301 vs current board top .223, only six task families and five
  rollouts; submission PR open, no uncertainty published.
- Architecture code shows patch artifact SHA/base manifest, parent selection and
  `git apply --3way --index`; compare only previews candidates, does not merge
  semantically; conflict is returned to parent/model.
- Ouro defaults: workers 10, active children/root 6, depth2, model concurrency3;
  hard active cap500, hard depth10; deeper than capability depth1 forced Light.
- Skills are canonical outside worktrees, content-hashed/provenance-bound, staged
  and atomically swapped; official hub update rolls back non-executable update.
  Orchestra currently copies Claude skills at spawn without hash/ownership sync.

## Calculations

Using the graph-labelled errors as independent normal SEs:

| Pair | delta | SEdiff | z | two-sided p | 95% CI delta | power at observed delta, alpha=.05 | 80%-power MDE |
|---|---:|---:|---:|---:|---|---:|---:|
| Opus5/Fable5 | 3.17 | 2.000 | 1.585 | .1130 | [-.75,7.09] | 35.4% | 5.60 |
| Opus4.8 | 1.32 | 1.640 | .805 | .4209 | [-1.89,4.53] | 12.7% | 4.59 |
| GPT5.5 | 1.20 | 1.628 | .737 | .4610 | [-1.99,4.39] | 11.4% | 4.56 |
| Grok4.5 | 5.64 | 1.860 | 3.032 | .0024 | [1.99,9.29] | 85.8% | 5.21 |

At ±1 graph SE, only pairs 1 and 4 do not overlap. At approximate ±1.96 SE,
only pair 4 does not overlap. Bonferroni alpha=.0125 keeps only pair 4. Replacing
Opus5's graph SE1.6 with official .9795 yields z2.046, p.0407, CI [.13,6.21],
power53.4%; it does not survive four-comparison correction.

The exact paired generalization test cannot be calculated because official
baseline per-task outcomes/covariance are inaccessible. As a deliberately rough
independent task-binomial sensitivity check with n=89, powers for observed deltas
are 9.2%,5.5%,5.5%,16.6%, but this is not presented as the primary test.

OSWorld independent-binomial sanity check: p1=.9069,p2=.9019,n1=n2=361;
SE1=1.529pp, SE2=1.566pp, SEdiff=2.189pp, z=.228,p=.819,
95% delta CI[-3.79,4.79]pp.

## Proposed borrowings, ranked

1. Content-hash skill sync + ownership manifest + atomic replace/rollback.
   Effort 1–2d, benefit high, risk low-medium.
2. Typed MCP error envelope `{code,message,http_status,retryable,details,request_id}`
   and true isError. Effort 2–4d, benefit high, risk medium.
3. RAG `indexed_head/generation` freshness status, applying Ouroboros's principle
   that derived state is bound to content hash. Effort 1–2d, benefit high, risk
   low-medium. This is an adaptation, not a literal Ouroboros RAG mechanism.
4. Keep Orchestra branch/squash merge, optionally add immutable merge manifest and
   caller==child.parent authorization. Do not replace it with raw patches.

Explicitly rejected: 500/depth5, always-injected full memory, raw patch transport,
full loop/evolution/review stack, marketplace/executable extension surface.

## Questions

1. Do the statistical conclusions follow, with the limitations stated?
2. Is any confidence label stronger than the evidence permits?
3. Does “no official-board entry” support “not independently confirmed now”
   without implying the result is false?
4. Is RAG freshness incorrectly called a borrowing when it is only a transfer of
   the content-bound-state principle?
5. Is any proposed ranking contradicted by its stated cost/risk?
