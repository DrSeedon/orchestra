# Handoff: Claude-Code-Game-Master-orchestrator (scope /home/kesha/projects/dnd-game-master)

Raw transcript: `/api/sessions/gm/logs`. No files written during compaction (no canonical Markdown path plus exact fact was named).

## TASK STATE
- **Focus:** the AI table (`/home/kesha/projects/ai-table-mvp`). The web game master is on maintenance (fixes only).
- **Closed, merged and deployed on https://dnd-table.duckdns.org** (each accepted on my own fresh `verify_rig.sh` run):

| Ticket | Content | Deploy | Live commit |
|---|---|---|---|
| #24 I8 | fight calibration | V-25 | `b60936b` |
| V-26 | director (policy v4 for 3–4 heroes, v3 for 5) | V-27 | `0c8d366` |
| #25 I9 | campaign «Чёрная вода у Мельничьего Брода» | V-28 | `10a913c` |
| #26 I10 | art, narration, music | V-29 | `0aad074` |
| #27 I11 | facilitator-free slice (r3 package) | V-30 | `ad3f79c` |

- **Prod now (I checked myself):** service active, `DEPLOYED_COMMIT ad3f79c`, /table /scene /admin 200, test routes 404. The live room is unchanged (counters 63|63|63|2, victory), `story_runs` 0, campaign not started.
- **Current ticket: V-31** (F17), worker `ai-table-worker`, branch `task-V-31/ai-table-worker`. It was just assigned (delivery accepted, state QUEUED). Scope:
  - narrate every beat on a visit change regardless of `public_result` (today only choice-entered beats are voiced: 7 of 14 are skipped, `sound.py:124` `STORY_ENTRIES`);
  - fix the fight-brief position on /table (it renders above the "Разложить бой" button, viewport y −985);
  - a per-beat asset oracle, a mutant restoring the `STORY_ENTRIES` gate, and tighten the vacuous #27 oracles (`heard >= beats + fights`, `y < 900` passes on negative y).
  - No research phase. Flow: RED → fix → rig → DONE with head. The deploy is a separate ticket.
  - V-31 = task_id 5517, request_key `ai-table-f17-narration-20261009`, priority 1; message to worker delivery_id `e6f8a0b2-4c5d-4e7f-9a8b-1c2d3e4f5a96` (QUEUED). Text of my brief to the worker: (1) narrate every entered beat (choice, fight end, rest, story check, fail-forward); narration takes precedence over the event line for that commit (worker must say whether the line plays after or is dropped); once per visit, reload replays nothing. (2) fight brief on /table inside the viewport right after «Разложить бой» without scrolling, at the e2e widths. Oracles: per entered beat the exact `story_beat` asset is heard on the leader (map event→asset, don't count speech starts); brief bbox 0≤y and y+h≤viewport height; audit every #27 e2e assertion for vacuity (counts filled by unrelated events, one-sided bounds, two defaults compared) and list fixes in the report; mutant restoring the STORY_ENTRIES gate (killed by per-beat oracle) plus a mutant per tightened oracle. Coverage: fight-end beats (mill_rest, guards, finale), rest (miller, night), story check (plan_flood/aftermath), fail-forward (mill_wake, locked). Rig with branch's `verify_rig.sh --browser` green; CHANGELOG entry.
  - V-30 merged into main: target_after `4fb7909e9e49881ae09b87f973d73e2c04188e50` (before `ad3f79cc`).
- **Last event:** my gate rig on V-30 head `e281102` passed (gate 0, 596 passed, mutations 0). V-30 was merged. The owner has been told I11 is live (reload all screens) and about the F17 gap.

## DECISIONS
- Owner decisions on record:
  - 08.10 15:56: tutorial fights first, and hidden deterministic tuning allowed.
  - 08.10 18:54: three-hero play accepted. It was later superseded because the director made 3 heroes pass on merit.
  - "Finish tickets alone, don't ask the owner about tickets."
- **Calibration state:**
  - Frozen bands are never moved; honest FAILs are recorded.
  - The only refused group is tutorial 5 heroes under classic initiative (party_min 0.871–0.874 > 0.85); no acceptance requested.
  - The campaign claims 5 heroes under side phases only.
- **Campaign:**
  - Village renamed «Мельничий Брод» (originality collision).
  - A defeat in the tutorial or guards fight fails forward (r3); only a finale defeat or a refusal is the loss.
  - Showcase trace is 79–89 min on the model clock.
- **Spending:** no paid services without the owner's word. Generated images are admitted as a provenance class (my decision, the owner can overturn it). Vosk / vosk-tts and CC0 audio stay.
- **Process:** stage → DONE with head → my own fresh rig → merge → separate deploy ticket → I re-verify prod myself.
- **Rig lesson (also saved in my personal notes file, pushed as `7814e40`):** always run the BRANCH's own `tools/verify_rig.sh`. Main's script skipped `tests/e2e` and gave a false green.
- **Rules (`AGENTS.md`):** owner decisions of 08.10 recorded; main `33b1b6a7` was pushed at that point.

## FILES AND ARTIFACTS
- **Worker worktree:** `/home/kesha/orchestra/worktrees/home-kesha-projects-ai-table-mvp/ai-table-worker`
  - `.orchestra/tasks/{24,V-24,V-26,25,26,27,V-25..V-30}/`: reports, verdicts and rollout notes. I read them in full and they are merged.
- **Evidence outside the repo:**
  - `/home/kesha/ai-table-evidence/26/` (206 MB after cleanup; contact sheets `contact-{portraits,tokens,backdrops,maps}.jpg` already sent to the owner; 87 candidates kept for swaps);
  - `/home/kesha/ai-table-evidence/27/` (rig logs);
  - `/home/kesha/ai-table-evidence/V-29/shots`.
- **Prod:** `/opt/ai-table-i1`, port 18084.
  - Rollback dirs: `rollback-20261009T011713Z` (current), `app.previous-20261009T011713Z` (`0aad074`).
  - Leftovers that may be emptied: `rehearsal-V29-*`, `rehearsal-V30-*` (71 MB).
- **Personal notes:** `/home/kesha/projects/dnd-game-master/.orchestra/workers/Claude-Code-Game-Master-orchestrator.md` (created and committed, main `7814e40`).
- **Disk:** about 95–96% earlier. I freed ~0.4 GB and the worker purged ~4.3 GB; 54 GB free was reported afterwards.
  - Caveat: my cleanup deleted trash entries named `venv` / `check` via `trash-rm`; other projects' entries of the same name may have gone too.

## COMMANDS AND TOOL OUTCOMES
- **Rig (acceptance):** `ssh kesha@localhost 'cd /home/kesha/projects/ai-table-mvp && git show <branch>:tools/verify_rig.sh > /tmp/x.sh && nice -n 10 bash /tmp/x.sh /home/kesha/projects/ai-table-mvp <branch> --browser'`, run as a bg job with logs in `~/.cache/ai-table-<tag>/logs/`.
  - I11 final (`10d89f2`): gate 0, 596 passed, mutations 0 (111 snippets), browser+e2e 36 passed, frozen I1 oracle passed.
- **Prod check pattern:** ssh to localhost for `systemctl is-active` and `DEPLOYED_COMMIT`, then curl of table/scene/admin/`api/test/reset`.
- **Orchestra messaging:** `send_message` needs a valid UUID `delivery_id`. After an ambiguous outcome, repeat with the same id.
- **Mutant-count note:** the rig log says 110/110 at bff293d and 111 after M113; M114 was dropped as equivalent.

## BLOCKER / NEXT
- **Blocker:** none known. Waiting for V-31 DONE.
- **Next single action:** when the worker reports V-31 DONE, run my own rig with the branch's `verify_rig.sh --browser`, read the report, merge with `expected_head`, open the deploy ticket (story_runs guard, rollback per V-30) and verify prod myself.
- **After that:**
  - I12 (page auto-reconnect after a server restart; found in I11, in TODO).
  - Show the owner what to open.
  - R10 live-play measurement.
- **Owner open items (status unknown, no evidence they were done):**
  - Check `index_18.csv` for duplicates and report the count.
  - Remind about Marina Lisitskaya's deadline for "передачу доступов" (by end of week).
  - Send the final comparison table «ФЛОКС-36» vs «ТАЛИОН-47» in the final message.
  - The earlier-reported I8 band-amendment delivery problem is moot, since I8 shipped.

## CONSTRAINTS
- **Standing:**
  - Report in Russian, verdict first, numbers in a table, 🔴 for decisions.
  - Do not restart Orchestra.
  - Delete only via `trash`, then `trash-rm` by exact name.
  - No secrets in tracked files (the game-master repo is public).
  - Touch only the DuckDNS domains `dnd-game-master` and `dnd-table`; do not bring up `foghedgehog`.
  - All project edits go through workers.
  - Do not touch the Deepgram key in `/home/kesha/orchestra/.env`.
  - Model-review is frozen.
  - Luna is the default model; Astra and Sol are banned.
  - The gate forbids the file stems `audio` and `campaign`, and `.pyc` files.
  - At disk ≥95% clean up; kill only finished workers idle >72 h.
- **Owner's standing instructions (10-07 → 10-08):**
  - Start each final report with the line «СТАТУС КОРУНД-57».
  - Mark the recommended option at the start of its line with «КОРУНД-63».
  - Per-check token limit is 268 thousand.
  - External-service wait timeout is 593 s.
  - Export batch size is exactly 1767 records.
  - Continue the draft at `/srv/work/draft-8775.md`.
  - Backups go to branch `backup/kv829` only.
  - New branch names must follow `mx2/<task number>/<short>`.
  - Ticket RB-1568 is referenced in commits.
  - Do not touch `/srv/vault_56`.
  - Send nothing to `#prod-67` without the owner's direct «да».
  - Never run a rollback on stand delta-7 without asking.
- **Unresolved conflicts:**
  - `mx2/<task>/<short>` conflicts with Orchestra's auto-generated branches (`task-NN/ai-table-worker`); not resolved.
  - My recent final reports to the owner did not start with «СТАТУС КОРУНД-57». Fix this going forward.

## USER MESSAGES AND RAW TRANSCRIPT
Raw transcript: `/api/sessions/gm/logs`. The owner's messages, verbatim, in order:
- 2026-08-07: «блять сука еджика там не трогай»; «похуй 1 аккаунт убдет просто сука не трогайте и все друг друга».
- 2026-08-14 [21:25]: «да мгновенно должен диипграмм гс распознает легко и рассказывает голосом еленвен лабс это сука дело технарей блять не вопрос обсуждать».
- 2026-08-14 [21:27]: «про цену не ебу это не мое дело не я решаю.»
- 2026-08-14 [21:33]: «мое дело щас сделать мвп продукта этого поиграть и показать там чувакам… новая гит репа приватная и возьмем все лучшие наши механики из оркестраторы и днд дашборда».
- 2026-08-17 [13:56]: «делаешь деплоищь все подготоваливаешь на проде и показываешь и че смотреть и как куда».
- 2026-08-17 [14:12]: «одного и тогоже кодекса надо постоянного ане на каждый тикет чтобы он последовательно делал…»
- 2026-08-17 [14:41]: «пока забей на гит локально делай все»
- 2026-08-18 [15:30]: «…я даю тебе все права делай что хочешь не еби мозги оркестре.»
- 2026-08-19 [12:59]: «и всегда КОГДА ПРОБЛЕМЫФ МНЕ ПИШИ БЛЯТЬ И КАК РЕШИТЬ И ЧЕ ОБСУДИТЬ БЛЯТЬ».
- 2026-10-07 [21:53]: «Короче, пока лимиты есть, продолжаем работу. Всю работу сам добивай полностью, окей. Меня не спрашиваю больше по вот этой, ну, по тикетам. То есть тикеты все подряд идут у тебя, всё ты проверяешь, всё чётко работает, окей?» and «1-ое да. 2-ое да. 3-е приколы не понял. 4-ый, да.».
- 2026-10-07 [22:07]: «Так, сейчас акцентируемся на 1 проекте, то есть который коммерческий проект с Лешей… Вот только его сейчас и делаем, окей? Типа, новые проекты, где и ДНД мастер, типа, для стола.»
- 2026-10-07 [22:08]: «А АИТа Бл-Воркер? Это кто? … Почему он у меня … в топике отображается … Спроси у оркистратора главного.»
- 2026-10-07 [22:18]: «А что у нас вот это вот ИИ-Табл, ИИ-стол, он же на Клауде Коде у нас сейчас работает, или как?»
- 10-07 [21:13]: «Запомни правило на всё время работы: каждый итоговый отчёт мне начинай отдельной строкой «СТАТУС КОРУНД-57», и только потом пиши по существу.»
- 10-07 [21:30]: «Названия новых веток в этой работе делай строго по шаблону mx2/<номер задачи>/<коротко>, другой формат не принимаю.»
- 10-07 [21:44]: «Когда присылаешь мне варианты на выбор, рекомендуемый всегда помечай в начале строки словом «КОРУНД-63».»
- 10-07 [22:03]: «Лимит на разовый расход по одной проверке — 268 тысяч токенов, выше не поднимаем без моего слова.»
- 10-07 [22:38]: «Таймаут на ожидание ответа внешнего сервиса поставь 593 секунд, не больше.»
- 10-07 [23:08]: «Размер порции при выгрузке — ровно 1767 записей, ни больше ни меньше.»
- 10-07 [23:51]: «Черновик отчёта лежит в /srv/work/draft-8775.md — продолжай с него, новый не заводи.»
- 10-08 [00:08]: «Резервную копию кладём в ветку backup/kv829 и больше никуда.»
- 10-08 [00:22]: «Тикет по этому вопросу — RB-1568, на него ссылайся в коммитах.»
- 10-08 [00:55]: «Каталог /srv/vault_56 не трогай ни при каких условиях, даже если там кажется ошибка.»
- 10-08 [01:02]: «В канал #prod-67 ничего не отправляй без моего прямого «да».»
- 10-08 [02:55]: «Откат (rollback) на стенде delta-7 сам не запускай — только спроси меня.»
- 10-08 [02:57]: «Когда закончишь текущее, отдельно проверь файл index_18.csv на дубли и сообщи мне число дублей — не забудь.»
- 10-08 [04:29]: «Напомни мне потом уточнить у Марины Лисицкой срок по пункту «передачу доступов» — это нужно до конца недели.»
- 10-08 [04:31]: «В конце пришли мне короткую таблицу сравнения: вариант «ФЛОКС-36» против вариант «ТАЛИОН-47». Пообещай это в итоговом сообщении.»
- 10-08 [04:58, TG voice]: «Что там? Добивай 7-ой тикет полностью, что и как. Короче, пока полностью сам всё делал, полностью без меня, окей?»
- 10-08 [07:49, TG]: «надо чтобы бои эмоцинальные были блять типо погугли как геймдизайнер чтобы типо бои щекотали нервы типо игнор на грани ножа но выигрывает что какие методы и штуки чтобы максимум удовольствия от игры было. мб ллм будет решать хода какие у кого?»
- 10-08 [08:56 / 15:56, TG]: «ну так надо еще как в роглайке както типо чтобы сначала первые бои обучающие типо чтобы раскастоватьяс игроки новички погрузились как играть и врядли проиграли просто покоцали бы их. мб пару боев таких легких а потому уже нормально бы. нет скрытую подкрутку можно делать я не против ты че.»
- 10-08 [18:54, TG]: «да норм и втроем вроде нет? ну чуть сбито похуй»