# #214 — Codex review, раунд 3 (свежая сессия)

> ⚠️ **Восстановлено из транскрипта джоба `bg-60d79b6cfb`, а не записано штатно** — тот же сбой
> `codex_review_artifact.py` (#217). Ревью отработало: 180 976 input / 1 793 output токенов.
> Ниже — полный `agent_message` из
> `/tmp/codex_review_impl-effort-model_codex-review-impl-r3.jsonl`, дословно.
>
> Раунд пущен СВЕЖЕЙ сессией, не `resume`: на тот момент я считал сломанным именно resume-путь.
> Контекст раундов 1-2 пересказан ревьюеру в запросе. Это 3-й и последний раунд по потолку
> `codex-debate` для исполняемого артефакта.

## Summary

The disconnect-order fix is complete for the reviewed lifecycle cases, and all four default roles resolve the same effort map. The focused suite passes: 37 tests.

## Findings (suggestion)

- `app/session.py:1166` — **FIXED (item 1).** Disconnect now precedes the in-memory and persisted effort update. A failed or partially completed disconnect leaves the manifest change pending, so the next turn retries it. A process crash between disconnect and persistence also self-recovers: the backend is rebuilt from the persisted old value, then the manifest is reapplied at the next boundary. Hibernate does not create a permanent disagreement because rebuilding ultimately uses `self.effort`.

- `app/pipeline.py:334` — **STILL BROKEN (item 2).** The reader still performs `stat()` and `read_text()` without checking that the file stayed stable. The absence of an in-process writer does not eliminate non-atomic writes by an administrator, deployment command, or editor. More importantly, partially written YAML can be syntactically valid, so `_apply_manifest_effort()` may accept an intermediate map and rebuild a live backend at the wrong effort. A post-read `stat()` comparison with a bounded retry would close this race.

- `app/pipeline.py:267` — **STILL BROKEN (item 3).** Dropping only an invalid level is inconsistent with the stated last-good policy. For example, a typo in Sol’s exact entry leaves `default: high`, actively changing Sol from `xhigh` to `high`; it does not merely retain stale configuration. Rejecting the manifest makes `_apply_manifest_effort()` keep the already active value, matching its documented handling of other invalid YAML. The warning helps diagnosis but does not prevent the unintended fallback.

- The new YAML is well-formed. `orchestrator`, `sub-orchestrator`, `worker`, and `full-cycle` resolve identically for all tested model/default cases. Scalar compatibility remains directly covered by `TestEffortByModel::test_scalar_applies_to_every_model`.

## Verdict

Changes requested: item 1 is fixed, but items 2 and 3 remain real configuration-safety issues on a hot path. No new blocking bug found.
