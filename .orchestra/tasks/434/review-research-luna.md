# #434 research review — Luna partial recovery

## Attempt log

- Route: one fresh Luna completeness/adversarial pass (`gpt-5.6-luna`), selected because the causal/statistical route would prefer Sol but no auxiliary Sol authorization exists.
- Tool outcome: timeout after 10 minutes; no normal output artifact and no final verdict.
- Recovery source: `/tmp/codex_review_research-fable51_review-research-luna.jsonl`, 141,092 bytes. The source was inspected after timeout; the content below is the model's partial output, not a completed review.
- Round accounting: **1 prose round spent**. The partial stream contained reviewer messages, so `codex-debate` does not classify it as a no-output attempt. No retry is allowed on unchanged prose.

## Recovered evidence

The reviewer read `research.md`, `cache-probe.jsonl`, and `run_cache_probe.py`. Its last model message was:

> Промежуточный результат: probe подтверждает именно узкий факт — Fable-2/3 прочитали полный 86 317-token prefix после Fable-1 write; это не подтверждает общий cache policy для произвольных задач. Арифметика 5m/1h по приведённым агрегатам сходится, поэтому ищу сейчас методологические и доказательные разрывы, а не придумываю арифметическую ошибку.

The independent arithmetic command completed with exit 0:

```text
T=6541187205 shares=0.00092703 97.80622177 2.01410363 0.17874757
f5=3831.46766850 f1=4819.56483600 o5=4314.86685825 o1=4808.91544200 ratios 0.88796892 1.00221451
break S5=4464091305 R-S=1933596759 delta=483.39918975
break S1=6440285640 R-S=-42597576 delta=-10.64939400
```

The reviewer also mechanically printed `research.md:145-178`, including the verdict, scope, candidate KB facts, and sources, and inspected all raw JSONL rows. No blocking finding was emitted before timeout.

## Verdict

**Вердикта нет — reviewer timed out after partial validation.** The partial evidence independently confirms the narrow cache claim and all published arithmetic. It neither approves the whole document nor supplies a blocking finding to resolve.

Review route: Luna

Rounds: 1 partial prose round

Verdict: вердикта нет

Findings: blocking 0 emitted; partial caution accepted — three identical PONG calls do not establish cache behavior for arbitrary tasks

Evidence: recovered model message + exit-0 arithmetic above; raw source path recorded in attempt log
