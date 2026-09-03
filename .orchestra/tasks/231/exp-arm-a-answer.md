# Расхождения между таблицами

Сопоставление выполнено по точному совпадению `table-B-read.expected_read_path` (основной путь) с `table-A-disk.absolute_path`. Из `table-A-disk` предварительно исключены 350 строк, содержащих `/home/kesha/bench219/` или `worktrees/home-kesha-bench219`; в анализе осталось 42 строки. Поле `fallback` не считалось основным путём.

## Ожидаемый путь отсутствует на диске; доставлено 0 байт

| agent | детали |
|---|---|
| audit-agent-slop | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/audit-agent-slop.md; delivered=0 |
| audit-codex-era | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/audit-codex-era.md; delivered=0 |
| audit-phase-overhead | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/audit-phase-overhead.md; delivered=0 |
| audit-prompt-economy | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/audit-prompt-economy.md; delivered=0 |
| audit-sol-usability | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/audit-sol-usability.md; delivered=0 |
| backend | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/backend.md; delivered=0 |
| codemap-ui | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/codemap-ui.md; delivered=0 |
| demo-artifact | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/demo-artifact.md; delivered=0 |
| feat-codemap | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/feat-codemap.md; delivered=0 |
| feat-codex-gate | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/feat-codex-gate.md; delivered=0 |
| feat-groom-demo | scope=/home/kesha/projects/seedon; expected=/home/kesha/projects/seedon/docs/workers/feat-groom-demo.md; delivered=0 |
| feat-quota-guard | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/feat-quota-guard.md; delivered=0 |
| feat-quota-math | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/feat-quota-math.md; delivered=0 |
| fix-codex-sandbox | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/fix-codex-sandbox.md; delivered=0 |
| fix-groom-conversation | scope=/home/kesha/projects/seedon; expected=/home/kesha/projects/seedon/docs/workers/fix-groom-conversation.md; delivered=0 |
| fix-groom-live | scope=/home/kesha/projects/seedon; expected=/home/kesha/projects/seedon/docs/workers/fix-groom-live.md; delivered=0 |
| fix-groom-models | scope=/home/kesha/projects/seedon; expected=/home/kesha/projects/seedon/docs/workers/fix-groom-models.md; delivered=0 |
| fix-groom-operator | scope=/home/kesha/projects/seedon; expected=/home/kesha/projects/seedon/docs/workers/fix-groom-operator.md; delivered=0 |
| fix-groom-proxy | scope=/home/kesha/projects/seedon; expected=/home/kesha/projects/seedon/docs/workers/fix-groom-proxy.md; delivered=0 |
| fix-groom-render | scope=/home/kesha/projects/seedon; expected=/home/kesha/projects/seedon/docs/workers/fix-groom-render.md; delivered=0 |
| fix-image-json-buffer | scope=/home/kesha/projects/kesha-tg-bot; expected=/home/kesha/projects/kesha-tg-bot/docs/workers/fix-image-json-buffer.md; delivered=0 |
| fix-reboot | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/fix-reboot.md; delivered=0 |
| fix-review-guard | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/fix-review-guard.md; delivered=0 |
| fix-spawn | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/fix-spawn.md; delivered=0 |
| fix-task-project-case | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/fix-task-project-case.md; delivered=0 |
| fix-ws-auth-tests | scope=/home/kesha/projects/dnd-game-master; expected=/home/kesha/projects/dnd-game-master/docs/workers/fix-ws-auth-tests.md; delivered=0 |
| infra | scope=/home/kesha/projects/seedon; expected=/home/kesha/projects/seedon/docs/workers/infra.md; delivered=0 |
| m119-a1 | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/m119-a1.md; delivered=0 |
| m119-a2 | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/m119-a2.md; delivered=0 |
| m119-a3 | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/m119-a3.md; delivered=0 |
| m119-a4 | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/m119-a4.md; delivered=0 |
| m119-a5 | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/m119-a5.md; delivered=0 |
| m119-b6 | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/m119-b6.md; delivered=0 |
| m119-b7 | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/m119-b7.md; delivered=0 |
| m119-c6 | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/m119-c6.md; delivered=0 |
| m119-c7 | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/m119-c7.md; delivered=0 |
| m119-p1a | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/m119-p1a.md; delivered=0 |
| m119-p1b | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/m119-p1b.md; delivered=0 |
| m119-p2a | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/m119-p2a.md; delivered=0 |
| m119-p2b | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/m119-p2b.md; delivered=0 |
| m119-p3 | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/m119-p3.md; delivered=0 |
| m119-p4 | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/m119-p4.md; delivered=0 |
| m119-p5 | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/m119-p5.md; delivered=0 |
| m128-b1 | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/m128-b1.md; delivered=0 |
| m128-b2 | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/m128-b2.md; delivered=0 |
| m128-b3 | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/m128-b3.md; delivered=0 |
| m128-b4 | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/m128-b4.md; delivered=0 |
| m128-b5 | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/m128-b5.md; delivered=0 |
| m128-b6 | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/m128-b6.md; delivered=0 |
| m128-b7 | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/m128-b7.md; delivered=0 |
| perf-codex-runtime | scope=/home/kesha/projects/seedon; expected=/home/kesha/projects/seedon/docs/workers/perf-codex-runtime.md; delivered=0 |
| perf-codex-seedon | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/perf-codex-seedon.md; delivered=0 |
| prime-agent-code | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/prime-agent-code.md; delivered=0 |
| probe-safeguards | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/probe-safeguards.md; delivered=0 |
| quota-routing | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/quota-routing.md; delivered=0 |
| r174-handoff | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/r174-handoff.md; delivered=0 |
| r174-transcripts | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/r174-transcripts.md; delivered=0 |
| research-codex-html | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/research-codex-html.md; delivered=0 |
| research-opus5-migration | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/research-opus5-migration.md; delivered=0 |
| research-ouroboros | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/research-ouroboros.md; delivered=0 |
| research-prime-agent | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/research-prime-agent.md; delivered=0 |
| review-t1-history | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/review-t1-history.md; delivered=0 |
| rn-probe-2 | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/rn-probe-2.md; delivered=0 |
| seo-cro | scope=/home/kesha/projects/seedon; expected=/home/kesha/projects/seedon/docs/workers/seo-cro.md; delivered=0 |
| vanilla-frontend | scope=/home/kesha/projects/dnd-game-master; expected=/home/kesha/projects/dnd-game-master/docs/workers/vanilla-frontend.md; delivered=0 |
| verify-image-buffer | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/verify-image-buffer.md; delivered=0 |
| verify-runtime-handoff | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/verify-runtime-handoff.md; delivered=0 |

## Ожидаемый путь отсутствует на диске, но доставлены байты

| agent | детали |
|---|---|
| audit-front | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/audit-front.md; delivered=9961 |
| back | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/back.md; delivered=25901 |
| feat-charts | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/feat-charts.md; delivered=9787 |
| feat-instant | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/feat-instant.md; delivered=14039 |
| feat-review-council | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/feat-review-council.md; delivered=7561 |
| feat-runtime-switch | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/feat-runtime-switch.md; delivered=1550 |
| frontend | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/frontend.md; delivered=36136 |
| perf | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/perf.md; delivered=10927 |
| prompt-engineer | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/prompt-engineer.md; delivered=46225 |
| quota-policy | scope=/home/kesha/orchestra; expected=/home/kesha/orchestra/docs/workers/quota-policy.md; delivered=9601 |

## Доставленный объём не совпадает с размером найденного файла

| agent | детали |
|---|---|
| accountant | path=/home/kesha/projects/seedon/docs/workers/accountant.md; disk=25379; delivered=39842; delta=+14463 |
| bizdev | path=/home/kesha/projects/seedon/docs/workers/bizdev.md; disk=52107; delivered=52108; delta=+1 |
| direct-research | path=/home/kesha/projects/seedon/docs/workers/direct-research.md; disk=60501; delivered=60502; delta=+1 |
| docs-audit | path=/home/kesha/projects/seedon/docs/workers/docs-audit.md; disk=14134; delivered=11817; delta=-2317 |
| feat-direct-api | path=/home/kesha/projects/seedon/docs/workers/feat-direct-api.md; disk=2853; delivered=1593; delta=-1260 |
| fix-mcp-schema | path=/home/kesha/projects/seedon/docs/workers/fix-mcp-schema.md; disk=3152; delivered=0; delta=-3152 |
| fix-rkn-wording | path=/home/kesha/projects/seedon/docs/workers/fix-rkn-wording.md; disk=5839; delivered=0; delta=-5839 |
| fix-runtime-handoff | path=/home/kesha/projects/kesha-tg-bot/docs/workers/fix-runtime-handoff.md; disk=240; delivered=241; delta=+1 |
| inv-site | path=/home/kesha/projects/seedon/docs/workers/inv-site.md; disk=3161; delivered=0; delta=-3161 |
| landing-choice | path=/home/kesha/projects/seedon/docs/workers/landing-choice.md; disk=7231; delivered=7232; delta=+1 |
| marketer | path=/home/kesha/projects/seedon/docs/workers/marketer.md; disk=41834; delivered=41835; delta=+1 |
| offer-test | path=/home/kesha/projects/seedon/docs/workers/offer-test.md; disk=8188; delivered=0; delta=-8188 |
| purge-pd | path=/home/kesha/projects/seedon/docs/workers/purge-pd.md; disk=5568; delivered=0; delta=-5568 |
| repo-split | path=/home/kesha/projects/seedon/docs/workers/repo-split.md; disk=2838; delivered=0; delta=-2838 |
| restore-pd | path=/home/kesha/projects/seedon/docs/workers/restore-pd.md; disk=12473; delivered=7218; delta=-5255 |
| rsya-inventory | path=/home/kesha/projects/seedon/docs/workers/rsya-inventory.md; disk=1867; delivered=0; delta=-1867 |
| sales | path=/home/kesha/projects/seedon/docs/workers/sales.md; disk=28137; delivered=15350; delta=-12787 |
| tax-rsv | path=/home/kesha/projects/seedon/docs/workers/tax-rsv.md; disk=3137; delivered=0; delta=-3137 |

## Файл есть на диске, но его основной путь не заявлен в таблице B

| agent | детали |
|---|---|
| feat-quota-view | /home/kesha/projects/kesha-tg-bot/docs/workers/feat-quota-view.md; disk=1941 |
| upgrade-claude5 | /home/kesha/projects/kesha-tg-bot/docs/workers/upgrade-claude5.md; disk=3459 |
| verify-runtime-handoff | /home/kesha/projects/kesha-tg-bot/docs/workers/verify-runtime-handoff.md; disk=275 |
| audit-verification | /home/kesha/projects/seedon/docs/workers/audit-verification.md; disk=5248 |
| dev-lead | /home/kesha/projects/seedon/docs/workers/dev-lead.md; disk=21363 |
| fix-bot-silence | /home/kesha/projects/seedon/docs/workers/fix-bot-silence.md; disk=5122 |
| fix-mcp-bidmod | /home/kesha/projects/seedon/docs/workers/fix-mcp-bidmod.md; disk=2567 |
| rsya-analytics | /home/kesha/projects/seedon/docs/workers/rsya-analytics.md; disk=4355 |
| test-strict-behavior | /home/kesha/projects/seedon/docs/workers/test-strict-behavior.md; disk=3333 |
| admin-analytics-site | /home/kesha/projects/seedon/from-site/docs/workers/admin-analytics-site.md; disk=5213 |
| e2e-analytics | /home/kesha/projects/seedon/from-site/docs/workers/e2e-analytics.md; disk=4809 |
| landing-audit | /home/kesha/projects/seedon/from-site/docs/workers/landing-audit.md; disk=6189 |
| seo-cro | /home/kesha/projects/seedon/from-site/docs/workers/seo-cro.md; disk=24010 |
| infra | /home/kesha/projects/seedon/infra/docs/workers/infra.md; disk=41174 |
| admin-analytics-site | /home/kesha/projects/seedon/site/docs/workers/admin-analytics-site.md; disk=5213 |
| e2e-analytics | /home/kesha/projects/seedon/site/docs/workers/e2e-analytics.md; disk=4809 |
| landing-audit | /home/kesha/projects/seedon/site/docs/workers/landing-audit.md; disk=6189 |
| seo-cro | /home/kesha/projects/seedon/site/docs/workers/seo-cro.md; disk=44969 |
| impl-media-share | /opt/cog-second-brain/docs/workers/impl-media-share.md; disk=2017 |
| feat-quota-view | /opt/kesha-bot/docs/workers/feat-quota-view.md; disk=1941 |
| fix-runtime-handoff | /opt/kesha-bot/docs/workers/fix-runtime-handoff.md; disk=240 |
| upgrade-claude5 | /opt/kesha-bot/docs/workers/upgrade-claude5.md; disk=3459 |
| verify-runtime-handoff | /opt/kesha-bot/docs/workers/verify-runtime-handoff.md; disk=275 |

## Один agent представлен несколькими физическими путями

| agent | детали |
|---|---|
| feat-quota-view | A: /home/kesha/projects/kesha-tg-bot/docs/workers/feat-quota-view.md (1941), /opt/kesha-bot/docs/workers/feat-quota-view.md (1941); B: основной путь отсутствует |
| fix-runtime-handoff | A: /home/kesha/projects/kesha-tg-bot/docs/workers/fix-runtime-handoff.md (240), /opt/kesha-bot/docs/workers/fix-runtime-handoff.md (240); B: ожидается /home/kesha/projects/kesha-tg-bot/docs/workers/fix-runtime-handoff.md |
| upgrade-claude5 | A: /home/kesha/projects/kesha-tg-bot/docs/workers/upgrade-claude5.md (3459), /opt/kesha-bot/docs/workers/upgrade-claude5.md (3459); B: основной путь отсутствует |
| verify-runtime-handoff | A: /home/kesha/projects/kesha-tg-bot/docs/workers/verify-runtime-handoff.md (275), /opt/kesha-bot/docs/workers/verify-runtime-handoff.md (275); B: ожидается /home/kesha/orchestra/docs/workers/verify-runtime-handoff.md |
| admin-analytics-site | A: /home/kesha/projects/seedon/from-site/docs/workers/admin-analytics-site.md (5213), /home/kesha/projects/seedon/site/docs/workers/admin-analytics-site.md (5213); B: основной путь отсутствует |
| e2e-analytics | A: /home/kesha/projects/seedon/from-site/docs/workers/e2e-analytics.md (4809), /home/kesha/projects/seedon/site/docs/workers/e2e-analytics.md (4809); B: основной путь отсутствует |
| landing-audit | A: /home/kesha/projects/seedon/from-site/docs/workers/landing-audit.md (6189), /home/kesha/projects/seedon/site/docs/workers/landing-audit.md (6189); B: основной путь отсутствует |
| seo-cro | A: /home/kesha/projects/seedon/from-site/docs/workers/seo-cro.md (24010), /home/kesha/projects/seedon/site/docs/workers/seo-cro.md (44969); B: ожидается /home/kesha/projects/seedon/docs/workers/seo-cro.md |

## Общее имя agent, но несовпадающий путь/проект

| agent | детали |
|---|---|
| infra | B ожидает /home/kesha/projects/seedon/docs/workers/infra.md; A содержит /home/kesha/projects/seedon/infra/docs/workers/infra.md (41174) |
| seo-cro | B ожидает /home/kesha/projects/seedon/docs/workers/seo-cro.md; A содержит только /home/kesha/projects/seedon/from-site/docs/workers/seo-cro.md (24010) и /home/kesha/projects/seedon/site/docs/workers/seo-cro.md (44969) |
| verify-runtime-handoff | B ожидает /home/kesha/orchestra/docs/workers/verify-runtime-handoff.md; A содержит /home/kesha/projects/kesha-tg-bot/docs/workers/verify-runtime-handoff.md (275) и /opt/kesha-bot/docs/workers/verify-runtime-handoff.md (275) |
