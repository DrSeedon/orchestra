> **RETRACTED как описание текущего main (08.09.2026, #530).** Ниже — историческое доказательство ветки #504, а не действующий контракт. Утверждения о живых площадках A, необходимости внедрить T1/T2/T3/T5, ожидании T4 и текущей пригодности прежних оракулов отменены коммитом `264daeb75484bbe9f97e53c654180fca11c8a12a`: main уже отделяет управление от прозы, удаляет T4-классификатор и safeguard-fork, использует `provider_limit`, завершение CLI и временный round hint. Исторические результаты тестов остаются результатами своих снимков, не текущего main. Адресная развязка всех десяти площадок и тестов: [дифференциал #530](../530/diff-main-vs-504.md). Исходные байты: `git show bf496f8828e4ae5859ac09fd1a20a864ac9e895b:.orchestra/tasks/504/full-suite-verdict.md`.

# #504 full-suite classification

## Branch run

- Protocol: `pytest --collect-only` → balance whole test files into six shards → six separate `pytest -vv --tb=short --timeout=120 -m 'not live_probe'` processes → validate every collected node has exactly one terminal status.
- Collection: 3,958 nodes in 248 files; shard weights 659-660 nodes.
- Coverage: 3,958 observed, `coverage_equal=true`; stable identities equal despite four raw parametrized-id spellings.
- Outcomes: 3,825 passed, 88 skipped, 3 xfailed, 42 failed; every shard ended RC 0/1 with a terminal summary.
- `uv.lock` was not modified.

## Failure attribution

- 35 of the 40 non-T4 failure nodes reproduced on current `main` when rerun with the same node ids in an isolated `--no-local` clone (`main-failing-nodes.log`: `35 failed, 5 passed`).
- Four of the five branch-only non-T4 nodes passed when rerun isolated on this branch **and** on merge-base `1b795300`: three Claude environment-hook tests and `test_line_point_is_computed_server_side_for_every_pool`. Their shard failures are order/shared-environment pollution, not #504 behavior.
- The fifth branch-only non-T4 node, `test_installed_codex_history_version_matches_pin`, failed on both this branch and merge-base: installed `codex-cli 0.153.4` versus old pin `0.150.1`. Current `main` already updates the pin and passes it.
- The remaining two failures are exactly the intentionally held T4 REDs: `test_t4_model_xml_prose_is_not_classified_as_unexecuted_tool_call` and `test_t4_model_text_classifier_has_no_python_or_browser_owner`.

Conclusion: the six-shard run found **zero unexplained failure nodes attributable to implemented T1/T2/T3/T5**. T4 remains red by owner hold, not by incomplete implementation.

## Retained evidence

- `full-suite/manifest.json`, `full-suite/summary.json`, `full-suite/failures-raw.txt` — frozen collection/shard result and exact branch failure set.
- `full-suite/main-failing-nodes.log` — current-main reproduction of the 40 non-T4 nodes.
- `full-suite/mergebase-five.log` — third-arm run for the five nodes that passed current main.
