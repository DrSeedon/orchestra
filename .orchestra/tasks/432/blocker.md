# #432 — Phase 3 blocker: background run invalidated by service restart

Date: 2026-09-01.

## Completed before the blocker

- T1 hidden-oracle controller: 12/12 baseline RED and historical-result GREEN; T1 test green.
- T2 inline accounting, T3 scout+main accounting, T4 analyzer: combined `4 passed`.
- Structural Luna canary after three invalid attempts: shell disabled, rooted MCP works, auth/oracle/
  traversal denied, `command_execution_events=0`, sessions `467→467`, cost `$0.00539916`.
- Full comparable pair #398: A and B both provider-completed and reached the same hidden judge;
  A=`model_failure` `$0.057786`, B=`success` `$0.09404504`; sessions `467→467`. This proves the
  measurement path reaches the subject rather than only measuring availability.
- Additional exploratory full pairs: #416 A/B both model failures; #412 A/B both model failures.
  They are not substituted into the frozen main corpus outcomes.

## Blocking event

The required A0/A0 stage ran through server-side `bg_create(type="run")` (`bg-0cb8101697`). Five
of twelve Luna sessions completed and were checkpointed:

| slot | outcome | cost_usd | cached_input_tokens |
|---|---|---:|---:|
| #401 A01 | success | 0.14317560 | 5,221,120 |
| #401 A02 | success | 0.08801368 | 2,669,824 |
| #416 A01 | success | 0.19116584 | 6,820,352 |
| #418 A01 | model_failure | 0.08686404 | 3,433,472 |
| #418 A02 | model_failure | 0.19136532 | 6,871,296 |

Total completed A/A cost: `$0.70058448` API-equivalent.

During #416 A02 the service restarted. The run root contains the 408,212-byte prompt and DB backup,
but no `A.jsonl` or terminal usage. Platform event, verbatim:

```text
[Background job INTERRUPTED]
Прерван рестартом сервиса, повторный запуск не выполнялся.
```

The same restart path previously interrupted #432 jobs `bg-54ff5827bb` and `bg-74ba2c50f7`.
`app/bg_jobs.py:675` hard-codes this outcome and calls `bg_fail_job`, despite the tool contract
stating that server-side jobs survive restart. Platform bug filed: **bg_create(type=run) is
force-failed on service restart instead of surviving it**.

## Why Phase 3 stops

The frozen contract permits retry only when `provider_started=0` is proven. #416 A02 is ambiguous:
the controller wrote the prompt before launching Codex, but a service restart killed the parent
before any raw/terminal artifact. Retrying could double-charge a provider-started slot; dropping it
changes the six-episode A/A denominator. Either action would move the goalposts after observation.

Therefore the 96-session main A/B was **not started**. A numeric scout-effect verdict would be
invalid until the background runner can preserve/adopt a running command across service restart,
or the owner explicitly authorizes a new frozen run generation that discards all current attempts.

## Production isolation

Every completed canary/pair/noise invocation recorded equal live `sessions` counts within its run.
The latest long noise generation began and ended on the same production table generation until the
restart; no code path imports `app.db` before setting a copied `ORCHESTRA_DB_PATH`. No production
files or rows were intentionally mutated.
