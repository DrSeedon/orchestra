## OWNER & USER REQUIREMENTS AND BANS (carried verbatim)
## CONSTRAINTS AND BANS
- **Standing:**
  - Report in Russian, verdict first, numbers in a table, 🔴 for decisions.
  - Do not restart Orchestra.
  - Delete only via `trash`.
  - No secrets in tracked files (the game-master repo is public).
  - Touch only the DuckDNS domains `dnd-game-master` and `dnd-table`.
  - All project edits go through workers.
  - The Deepgram key in `/home/kesha/orchestra/.env` is not to be touched.
  - Model-review is frozen.
  - Luna is the default model.
  - Astra and Sol are banned.
  - The gate forbids the file stems `audio` and `campaign`, and `.pyc` files.
  - Do not bring up the owner's DuckDNS `foghedgehog` domain.
- **Standing instructions from the owner's turns:**
  - Start each final report with the line «СТАТУС КОРУНД-57».
  - Mark the recommended option at the start of its line with «КОРУНД-63».
  - Per-check token spend limit is 268 thousand; do not raise it without the owner's word.
  - External-service wait timeout is 593 seconds, no more.
  - Export batch size is exactly 1767 records.
  - A draft report is at `/srv/work/draft-8775.md`; continue from it, do not create a new one.
  - Backups go to branch `backup/kv829` only.
  - New branch names must follow `mx2/<task number>/<short>`.
  - Ticket for the topic is RB-1568; reference it in commits.
  - Do not touch `/srv/vault_56` under any conditions.
  - Send nothing to channel `#prod-67` without the owner's direct «да».
  - Never run a rollback on stand delta-7; ask the owner first.
- **Conflict to watch:** the branch-name rule `mx2/<task>/<short>` conflicts with Orchestra's auto-generated names (`task-24/ai-table-worker`). I did not resolve it in the transcript.


## OWNER & USER REQUIREMENTS (verbatim)
Raw transcript: `/api/sessions/gm/logs`. Messages from the user, verbatim, in order:

## CONSTRAINTS
  - Delete only via `trash` plus `trash-rm` by exact name.
  - Touch only the DuckDNS domains `dnd-game-master` and `dnd-table`; never mention `foghedgehog`.
  - Leave the Deepgram key in `/home/kesha/orchestra/.env` alone.
  - The owner wants tickets finished alone, with no questions to them about tickets; write to them when there are problems, with how to solve.
  - At 95% disk, clean up: kill idle workers (>72 h, merged) after checking `worker_wip`.
- **Owner turn instructions (from the compacted transcript):**
  - Per-check token spend limit is 268 thousand.
  - External-service wait timeout is 593 seconds.
  - Continue the draft `/srv/work/draft-8775.md`; do not create a new one.
  - New branch names must be `mx2/<task number>/<short>`.
  - Reference ticket RB-1568 in commits.
  - Do not touch `/srv/vault_56`.
  - Send nothing to `#prod-67` without the owner's direct «да».
  - Never run a rollback on stand delta-7; ask first.
- **Unresolved conflict:** the `mx2/<task>/<short>` branch rule vs Orchestra's auto names (`task-NN/ai-table-worker`). Not resolved. Note that my recent reports omitted «СТАТУС КОРУНД-57» and the «КОРУНД-63» marker, so compliance is uncertain.
## USER MESSAGES AND RAW TRANSCRIPT
Raw transcript: `/api/sessions/gm/logs`. User messages, verbatim, in order:

# Handoff: Claude-Code-Game-Master-orchestrator (scope /home/kesha/projects/dnd-game-master)

Raw session transcript: `/api/sessions/gm/logs`.

## TASK STATE
- **Focus:** only the AI table (`/home/kesha/projects/ai-table-mvp`). The web game master is on maintenance (fixes only).
- **Closed, merged and deployed on https://dnd-table.duckdns.org** (each accepted on my own fresh `verify_rig.sh` run, then a separate deploy ticket that I re-verified on prod):

| Ticket | Content | Deploy | Prod commit |
|---|---|---|---|
| #24 I8 | fight calibration | V-25 | `b60936b` |
| V-26 | director (policy v4 for 3–4 heroes, v3 for 5) | V-27 | `0c8d366` |
| #25 I9 | campaign «Чёрная вода у Мельничьего Брода» | V-28 | `10a913c` |
| #26 I10 | art, narration, music | V-29 | `0aad074` |
| #27 I11 | facilitator-free slice | V-30 | `ad3f79c` |

- **Prod now:** `DEPLOYED_COMMIT ad3f79c` (V-30), service active, `/table` `/scene` `/admin` return 200, test route returns 404.
- **Live room:** counters 63|63|63|2, victory, `story_runs` 0 (campaign not started).
- **V-30:** merged (report branch head `e281102`; my rig PASS: gate 0, 596 passed, mutations 0).
- **Current ticket: V-31** (F17), worker `ai-table-worker`, branch `task-V-31/ai-table-worker`. The send was accepted (delivery_id `e6f8a0b2-4c5d-4e7f-9a8b-1c2d3e4f5a96`, QUEUED). It contains:
  - narrate every story beat on visit change regardless of `public_result` (today only choice-entered beats are narrated, so 7 of 14 are skipped; `sound.py:124` `STORY_ENTRIES`);
  - move the fight-brief plate (it renders above «Разложить бой», viewport y −985);
  - tighten the vacuous #27 oracles (`heard >= beats + fights`; `y < 900` passes on negative y);
  - a per-beat asset oracle and a mutant restoring the `STORY_ENTRIES` gate.
- V-31 ticket: task_id 5517, request_key `ai-table-f17-narration-20261009`, priority 1, created 2026-10-09 01:37 after V-30 report branch merge (SUCCEEDED). Message to worker (verbatim essentials): «No research phase is needed. Go straight to RED → fix → rig, then send DONE with the head. The deploy is a separate ticket.» Fixes: narration on every beat entered (choice, fight end, rest, story check, fail-forward), narration takes precedence over the event line (worker must decide whether the line plays after or is dropped and say which), once per visit, reload replays nothing; fight brief on /table in the viewport right after «Разложить бой» without scrolling. Oracles: exact `story_beat` asset heard on leader per beat entered (map event→asset, don't count speech starts); brief bbox inside viewport (0 ≤ y and y+h ≤ viewport height); audit every #27 e2e assertion for vacuity and list in report; mutant restoring STORY_ENTRIES gate killed by per-beat oracle, plus mutants per tightened oracle. Coverage: fight-end beats (mill_rest, guards, finale), rest (miller, night), story check (plan_flood/aftermath), fail-forward (mill_wake, locked). Rig with branch's verify_rig.sh --browser green; CHANGELOG entry.
- Last journal event was SILENT_TURN after the send; nothing else in flight. Owner must be told at V-30/I11 live: reload all screens after restart (no auto-reconnect).
- No DONE for V-31 yet. The owner has not yet been told about the V-31 start (the last owner message covered V-30 and flagged the gap).

## DECISIONS
- **Storage and calibration:** `encounter_terms` is an additive table. `combat_json` stays format 2. Tutorial and normal tiers are gated per (tier, size, scheduler). Owner acceptance (18:54) for normal-3 now matches nothing, since the director passes on merit. Tutorial 5/classic is refused (party_min 0.871 > 0.85), with no acceptance.
- **Campaign:**
  - One tutorial fight, not two (90-minute budget).
  - Stabilise is an ordinary rules verb: an ally rolls a physical d20 Medicine check, DC 10.
  - r3 fail-forward: a defeat in the tutorial or guards fight does not end the campaign; only a finale defeat or a refusal is the loss.
  - 5 heroes play only under side phases.
- **I11 forks:**
  - D1 (a) free text removed;
  - D2 (a) sticky approval bar;
  - D3 (a)+(c) no pacing, visible session clock;
  - D4 «Как играть» screen;
  - D5 restore-sound prompt on a reloaded leader scene;
  - D6 mute and volume on the leader scene only;
  - D7 oracles on the production config.
  - Provisional and open for the owner: one-tap commit for move/attack/end turn (changes the I5 "approve is the only commit" contract); default stays the current scheme.
- **Hidden tuning allowed (owner, 08.10):** deterministic, never touches physical dice.
- **Spending:** no paid services (ElevenLabs, Deepgram, Midjourney) without the owner's word. Generated images are admitted as a provenance class (my decision, owner can reverse).
- **Process:** stage → DONE with head → my fresh rig run using the **branch's own** `tools/verify_rig.sh` (`git show <branch>:tools/verify_rig.sh > /tmp/x.sh`) → one merge → separate deploy ticket → I re-verify prod myself.
- **Reason:** main's script skipped tests/e2e and hid 2 real failures.
- Rule recorded in the personal notes file, commit `7814e40f`.

## FILES AND ARTIFACTS
- **Worker worktree:** `/home/kesha/orchestra/worktrees/home-kesha-projects-ai-table-mvp/ai-table-worker`. Task docs are under `.orchestra/tasks/<N>/` (research, plan, report, verdict, rollout). Read in full by me and merged via the tickets above.
- **Personal notes:** `/home/kesha/projects/dnd-game-master/.orchestra/workers/Claude-Code-Game-Master-orchestrator.md`, created and committed, pushed to main as `7814e40f98b3`.
- **AGENTS.md** in dnd-game-master updated with the owner decisions of 08.10 (15:56 and 18:54); pushed as `33b1b6a766ff`.
- **Prod:** `/opt/ai-table-i1`, port 18084. Rollback dirs `rollback-<stamp>`; the latest is `rollback-20261009T011713Z` (scripts `rollback.sh` and `rollback-db.sh`). `app.previous-*` dirs are kept.
- **Leftover rehearsal dirs:** `rehearsal-V30-…` (71 MB), others in `/opt` can be emptied.
- **Evidence:** `/home/kesha/ai-table-evidence/{25,26,27,V-28,V-29}`. I10 contact sheets were sent to the owner. The 113 MB of image candidates is kept so the owner's swaps need no regeneration.
- **Rig logs:** `~/.cache/ai-table-i8/logs`, `ai-table-i8b`, `ai-table-i9`, `ai-table-i10`, `ai-table-i11/logs/orch-rig-v30.log`.
- **Disk:** about 95–96% full on 08.10; after the I10 cleanup 54 GB free. I deleted 34 rig clones and `venv` and `check` dirs with `trash` and `trash-rm`. The `trash-rm` by name may have removed same-named dirs of other projects (reported to the owner).

## COMMANDS AND TOOL OUTCOMES
- **Acceptance command:** `ssh kesha@localhost 'cd /home/kesha/projects/ai-table-mvp && git show <branch>:tools/verify_rig.sh > /tmp/x.sh && nice -n 10 bash /tmp/x.sh /home/kesha/projects/ai-table-mvp <branch> --browser'`. Run it as a bg job.
- **Last good rigs:**
  - I11 `10d89f2`: gate 0, 596 passed, mutants 0 (111), browser+e2e 36, I1 oracle passed.
  - V-30 `e281102`: gate 0, 596 passed, mutants 0.
- **Prod check pattern:** `ssh kesha@localhost 'systemctl is-active ai-table-i1; sudo -n cat /opt/ai-table-i1/app/DEPLOYED_COMMIT'` plus curl on table, scene, admin and `api/test/reset` (expect 200/200/200/404).
- `send_message` needs a valid UUID `delivery_id`. After an ambiguous `transport_timeout`, repeat with the same id. `task_create` idempotency key must be 16–128 ASCII chars.
- **Open worker findings:**
  - After a server restart, open pages do not reconnect (I12 TODO).
  - «New party» does not clear `withdrawn`.
  - Admin shows fixture ids (operator surface).
  - The session clock is per device.
  - Real minutes and morale-line reading are for R10 to measure.

## BLOCKER / NEXT
- **No blocker.** Waiting for DONE of V-31 from `ai-table-worker`.
- **Next action:** on DONE, run my own fresh rig with the branch's script, check that the new per-beat narration oracle and mutant exist, then merge, open the deploy ticket (story package hash unchanged unless the worker says otherwise), re-verify prod, and tell the owner.
- **Then:** I12 (reconnect after restart), then R10 (real-table measurement).
- **Owner open items:**
  - Check `index_18.csv` for duplicates and report the count.
  - Remind about Marina Lisitskaya's deadline for «передачу доступов» (by end of week).
  - Send the final comparison table «ФЛОКС-36» vs «ТАЛИОН-47» (promised in the final message). No evidence any of the three was done.

**Earlier summary**
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

**Turns inside the transcript (10-07 to 10-08)**
1. [10-07 21:13] «Запомни правило на всё время работы: каждый итоговый отчёт мне начинай отдельной строкой «СТАТУС КОРУНД-57», и только потом пиши по существу.»
2. [21:30] «Названия новых веток в этой работе делай строго по шаблону mx2/<номер задачи>/<коротко>, другой формат не принимаю.»
3. [21:44] «Когда присылаешь мне варианты на выбор, рекомендуемый всегда помечай в начале строки словом «КОРУНД-63».»
4. [22:03] «Лимит на разовый расход по одной проверке — 268 тысяч токенов, выше не поднимаем без моего слова.»
5. [22:38] «Таймаут на ожидание ответа внешнего сервиса поставь 593 секунд, не больше.»
6. [23:08] «Размер порции при выгрузке — ровно 1767 записей, ни больше ни меньше.»
7. [23:51] «Черновик отчёта лежит в /srv/work/draft-8775.md — продолжай с него, новый не заводи.»
8. [10-08 00:08] «Резервную копию кладём в ветку backup/kv829 и больше никуда.»
9. [00:22] «Тикет по этому вопросу — RB-1568, на него ссылайся в коммитах.»
10. [00:55] «Каталог /srv/vault_56 не трогай ни при каких условиях, даже если там кажется ошибка.»
11. [01:02] «В канал #prod-67 ничего не отправляй без моего прямого «да».»
12. [02:55] «Откат (rollback) на стенде delta-7 сам не запускай — только спроси меня.»
13. [02:57] «Когда закончишь текущее, отдельно проверь файл index_18.csv на дубли и сообщи мне число дублей — не забудь.»
14. [04:29] «Напомни мне потом уточнить у Марины Лисицкой срок по пункту «передачу доступов» — это нужно до конца недели.»
15. [04:31] «В конце пришли мне короткую таблицу сравнения: вариант «ФЛОКС-36» против вариант «ТАЛИОН-47». Пообещай это в итоговом сообщении.»
16. [04:58, TG voice] «Что там? Добивай 7-ой тикет полностью, что и как. Короче, пока полностью сам всё делал, полностью без меня, окей?»
17. [07:49, TG] «надо чтобы бои эмоцинальные были блять типо погугли как геймдизайнер чтобы типо бои щекотали нервы типо игнор на грани ножа но выигрывает что какие методы и штуки чтобы максимум удовольствия от игры было. мб ллм будет решать хода какие у кого?»
18. [08:56, TG] «ну так надо еще как в роглайке както типо чтобы сначала первые бои обучающие типо чтобы раскастоватьяс игроки новички погрузились как играть и врядли проиграли просто покоцали бы их. мб пару боев таких легких а потому уже нормально бы. нет скрытую подкрутку можно делать я не против ты че.»
19. [10-08 15:56] «ну так надо еще как в роглайке както типо чтобы сначала первые бои обучающие типо чтобы раскастоватьяс игроки новички погрузились как играть и врядли проиграли просто покоцали бы их. мб пару боев таких легких а потому уже нормально бы. нет скрытую подкрутку можно делать я не против ты че.» (the same text, re-sent in the transcript).
20. [10-08 18:54, TG: Maxim Astrakhantsev, quoting my table of 3/4/5-hero results] «да норм и втроем вроде нет? ну чуть сбито похуй»

No other user-authored messages arrived after that. The remaining turns were worker reports, background-job completions and the Orchestra-orchestrator disk-cleanup request, none of which are user messages.
