# test-suite-pruning

## Established

- На `main` SHA `1d9be7ae8511a1c5657362cc56eef395b4585bf2` pytest-инвентарь содержит 153 test-файла, 78,491 физическую LOC, 2,886 source test definitions, 162 локальные fixture и 3,284 collected nodes включая 3 live-probe nodes · `.orchestra/tasks/313/inventory.json` + `collect-default-patched.txt` · 2026-08-24, #313
- Непропатченная коллекция на текущем host собрала `3151/3154` и остановилась на восьми `AttributeError: module 'os' has no attribute 'pidfd_open'`; это collection gap, не silent skip · `.orchestra/tasks/313/evidence/collect-default.txt` · 2026-08-24, #313
- AST-кандидатогенерация дала 0 exact body duplicate clusters и одну near-duplicate lower bound пару (`test_pipeline.py:280`/`:292`, Jaccard 0.9211); separate defaults/role fields remain distinct contracts · `.orchestra/tasks/313/clusters.json`, `candidates.csv` · 2026-08-24, #313
- Удаление одной route из runtime seam краснит snapshot, но compound mutant с одновременным truncation route surface и snapshot оставляет snapshot зелёным и краснит minimum-surface guard; apparent route-test redundancy не доказана · `.orchestra/tasks/313/evidence/mutant-route-snapshot.txt`, `compound-*.txt` · 2026-08-24, #313
- Quota admission E2E targeted run дал 95 passed и 4 failed на live blocked quota несмотря на intended monkeypatch; это deterministic-seam/live-state defect, поэтому verdict REWRITE, not DELETE · `.orchestra/tasks/313/evidence/target-quota-proxy.txt`, `research.md` F4 · 2026-08-24, #313
- Merge-stuck targeted run дал 184 passed и 2 failed из-за stale fake без `expected_target_head`, который уже принимает production `execute_merge_session` · `target-manager-acceptance.txt`, `app/routes/sessions.py:1461`, `app/merge_operations.py:1304` · 2026-08-24, #313
- Proven DELETE/MERGE candidates: zero nodes and zero LOC; static similarity or rarity alone is insufficient under the #250 valid-alternate/mutant rule · `.orchestra/tasks/313/research.md` F10, `candidates.csv` · 2026-08-24, #313

- **Тест, который проверяет ДОСЛОВНУЮ формулировку промпта, правила или документа, удаляется, а не чинится — решение владельца 06.09.2026** («тесты нужны только на кор фичи которые не будут меняться… а не хуйню которую мы хотим поменять»). Замер того же дня: за два прохода удалено 23 таких теста (10 + 5 + 1 в `test_default_pipeline.py`, 3 в `test_orchestra_layout_430.py`, по одному в `test_fan_prompt_407.py`, `test_task_tracker_integration.py`, `test_runtime_registry.py`, `test_project_knowledge_distribution_412.py`); самый крупный держал 14 цитат в одном тесте. НИ ОДИН из них за свою жизнь не поймал дефекта, зато три были красными прямо в момент удаления по законным причинам: владелец сменил маршрут моделей (Sol → Astra) и мы добавили `docs/portfolio/`. Оставлять надо проверки МЕХАНИКИ доставки — что модуль доезжает до каждой роли, что промпт одной роли не течёт в другую, что индекс собирается из единственного источника: именно такая проверка поймала реальную потерю целого слоя правил у роли `reducer` (#490). Правило записано в модуль `code-quality` и доезжает до всех ролей, включая оркестраторов · 2026-09-06

## Rejected

- «`test_route_surface_is_discoverable` дублирует snapshot и можно удалить» · compound truncated-snapshot mutant passes snapshot but fails minimum-surface guard · 2026-08-24, #313
- «Длинные или редкие session/runtime-handoff/merge recovery tests избыточны» · targeted evidence identifies unique authority, recovery, receipt, rollback, and cleanup contracts; runtime-handoff red output is model-registry setup failure, not redundancy · 2026-08-24, #313
- «Static `all/any`, MagicMock, representation, browser, source-shape, or wall-clock signal is a deletion verdict» · static counts include explicit controls and contract-bound checks; `static-signals.json` is candidate generation only · 2026-08-24, #313

## Gaps

- Full default test execution remains unmeasured because host collection has eight pidfd import errors and the protocol forbids service/provider runs; no full-suite runtime or removable-node estimate beyond zero proven candidates · 2026-08-24, #313
- No mutation/selection experiment was run for quota, merge, frontend, prompt, or task candidates because they failed current reachability or require service/live state; future tickets in `research.md` define the repairs · 2026-08-24, #313
- README index entry for this new topic was not added because the user hard write scope excludes `.orchestra/kb/README.md` · 2026-08-24, #313

## Источники

- `.orchestra/tasks/313/research.md` — full current-suite pruning research and decisions
- `.orchestra/tasks/313/metrics.md` — inventory and cost measurements
- `.orchestra/tasks/313/candidates.csv` — exact decision table
- `.orchestra/tasks/250/research.md` — valid-alternate and independent-mutant requirement
- `.orchestra/kb/test-oracles.md` — vacuity, live-state, direct-seam, mock, browser, and runtime oracle rules
