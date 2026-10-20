# Handoff: Claude-Code-Game-Master-orchestrator (scope /home/kesha/projects/dnd-game-master)

Raw session transcript: `/api/sessions/gm/logs`. No files were written during compaction, because the conversation names no canonical Markdown path plus an exact fact to store.

## TASK STATE
- **Focus:** only the AI table (`/home/kesha/projects/ai-table-mvp`). The web game master is on maintenance: no new features, only fixes.
- **Closed and deployed on https://dnd-table.duckdns.org:**

| Ticket | Content | Deploy | Main after merge |
|---|---|---|---|
| #21 I5 | voice | V-19 | `beaa3cb` |
| #22 I6 | sound | V-20 | `ca1c0b0` |
| V-21 | /admin sound buttons | deployed | `ed2eaa0` |
| #23 I7 | story | V-23 | `4bd6625` |

- Each was accepted on my own fresh `verify_rig.sh` run. The I7 numbers are in the first bullet under "Prod" below.
- **Prod now:**
  - `DEPLOYED_COMMIT d4789425` (main `d478942`, I7), service active, `/table` 200.
  - The live room is unchanged (victory, revision 63, `story_runs` empty).
  - Rollback is blocked while a `story_check` roll is pending.
- **V-24 research** (fight feel, worker `fight-feel-research`): merged into ai-table-mvp main as `0a6a368`, worker killed.
  - 13 500 fights measured on the real kernel.
  - LLM enemy turns are not recommended (cost $4–19k for the calibration matrix, non-reproducible).
  - The "spare the downed" policy cuts deaths and costs ≤1 percentage point of wins.
- **Current ticket: #24 I8** (fight calibration), worker `ai-table-worker`, branch `task-24/ai-table-worker`, head `4a16efa`. This is stages 1–3b and is not rebased onto `0a6a368`. Contents:
  - rosters per party size;
  - round cap that ends in `withdrawn`;
  - objective;
  - `encounter_terms` table;
  - policy v3;
  - morale (leader down → `victory`, `terms.ended_by=routed`);
  - the `tools/calibrate_encounters.py` tool;
  - the tension metrics.
- **Checks on I8:**
  - Rig on `e7aef1f` with `--browser`: gate passed, 476 passed / 8 failed (the `test_i8_core_calibration` RED oracles waiting for freeze), mutants exit 0, browser 14 passed.
  - The rig on `4a16efa` is not yet reported.
- **First measurement:** the fights are too easy (cakewalk 46–100%).
- **Worker's finding:** two of my "normal" bands are unreachable on this kernel.
  - `party_min` median 0.40–0.65 conflicts with death ≤5%.
  - Per-cell tension bands cannot hold across party compositions.
- The worker expects a FAIL verdict at all sizes.
- **Status of my band amendment:** I sent it to the worker three times. Each send returned `transport_timeout` (ambiguous delivery), and a `delivery_id` error occurred once. Delivery is unconfirmed.

## DECISIONS
- **I8 storage:** option (a), additive table `encounter_terms`. `combat_json` stays format 2. The rollback guard refuses when `combat.status == withdrawn` or a `story_check` roll is pending.
- **Tutorial fights (owner, 08.10):**
  - Own tier in freeze-v1 with its own candidate and verdict: win ≥98%, death ≤1%, edge ≤35%, cakewalk ≤50%, `party_min` median 0.55–0.85.
  - 1–2 tutorial fights open the campaign (I9).
- **Hidden tuning allowed (owner, 08.10):**
  - The "director" is deterministic and never touches physical dice.
  - It is a separate ticket after I8. A ticket for it is not evidenced as created yet.
- **My amended normal bands** (I own them; sent but delivery unconfirmed; full text sent to worker, "freeze-v1 для `normal` фиксируй так"):
  - Safety per cell (composition × scheduler): win ≥90%, TPK ≤2%; death ≤12% worst cell and ≤5% mean per party size.
  - Tension as mean over compositions of one size: `edge` 35–70%, `edge_win` ≥30%, `cakewalk` ≤25%.
  - Round cap reached ≤50% of fights (was ≤25%); R9 minutes unchanged.
  - Must record per-cell edge/edge_win/death spread per party (input for the director ticket).
  - Owner was told the amended bands in a Russian table (final message of the transcript); send used a delivery_id guard against duplicates, but the 3rd retry also timed out and one try failed with `delivery_id must be a UUID` (retry needs a valid UUID).
  - Earlier bullets:
  - `party_min` is recorded, not gated.
  - Tension is judged as a mean over compositions.
  - Death ≤5% mean and ≤12% worst composition.
  - Cap reached ≤50%.
  - The director ticket restores strict per-composition bands.
- **LLM for enemy turns:** not now. Option (c) is deterministic turns, with an LLM later only for lines and announced intents. Any paid use needs per-fight cost first.
- **Spending:**
  - No paid services (ElevenLabs, Deepgram) without the owner's word.
  - I told the owner I would stop asking about them.
  - Free Vosk and vosk-tts stay in use.
- **Process:** stage → DONE with head → my fresh-rig run → one merge → separate deploy ticket → I re-verify prod myself.
- **Rules (`AGENTS.md`) updated and pushed:**
  - V-22: workers use the system CLI 2.1.293 and read `AGENTS.md` alone.
  - Two owner decisions of 08.10 recorded.
  - Latest dnd-game-master main `e18d61e44576`, pushed.

## FILES, IDS AND ARTIFACTS
- **Worker worktree:** `/home/kesha/orchestra/worktrees/home-kesha-projects-ai-table-mvp/ai-table-worker`
  - `.orchestra/tasks/24/research.md` and `plan.md` (read in full).
  - `.orchestra/tasks/24/iterations/*.out` and `*.cells.json`: roster sweeps (not read by me).
- **V-24 research:** `.orchestra/tasks/V-24/research.md` (563 lines, read in full), merged in ai-table-mvp main as `0a6a368`.
- **Deploy reports** (read in full, merged): `.orchestra/tasks/V-19`, `V-20`, `V-21`, `V-23`.
- **Rig logs:** `~/.cache/ai-table-i5/logs`, and `ai-table-i7/logs/orch-final-rig.log` (I6's final rig log was `~/.cache/ai-table-i6/logs/orch-final-rig.log`).
- **Audio store:** `~/.cache/ai-table-i6/audio-store` (63 files, 5.5 MB), deployed at `/opt/ai-table-i1/audio-store`.
- **Prod:** `/opt/ai-table-i1`, port 18084, rollback dirs `rollback-<stamp>`, `app.previous-<stamp>`. Leftover `rehearsal-V19/V20/V21/V23-*` directories can be emptied.
- **Disk cleanup:**
  - Trashed the Vosk large model, the TTS zip, the Piper onnx files and the small-model zip, then ran `trash-rm`.
  - Free space went from 22 GB to 27 GB (91%). The 4.5 GB freed was reported to Orchestra-orchestrator.
  - Rig directories under `~/.cache/ai-table-rig.*` were not deleted (about 5–6 MB each).
- **Workers:**
  - `ai-table-worker`: persistent, Opus 5.5.
  - `dnd-backend`: idle. Its V-22 was merged on 08.10, so the 72-hour rule is not yet reached.
  - `fight-feel-research`: killed.

## NUMBERS AND COMMANDS
- **Acceptance command:** `AI_TABLE_PYTHON=<worker>/.venv/bin/python bash tools/verify_rig.sh /home/kesha/projects/ai-table-mvp <branch> --browser`, run as a bg job.
  - I7 final rig: gate ADMITTED, 466 passed, mutants 63 killed (exit 0), browser 13 passed.
- **Prod check pattern:** ssh to localhost for `systemctl is-active`, `DEPLOYED_COMMIT`, unit env, and the test routes returning 404.
- **Last tool outcomes in the transcript:**
  - `get_worker_logs` for `ai-table-worker` returned `transport_timeout`.
  - Orchestra server load was about 26.
  - Whether the worker got my amended bands is `UNKNOWN`.

## OPEN ITEMS AND NEXT ACTION
- **Blocker:** unconfirmed delivery of the band amendment to `ai-table-worker`. Cause is probably server overload, but that is not confirmed.
- **Next single action:** check `ai-table-worker` state (`get_worker_logs` or `worker_wip`) and resend the amended bands if the worker did not act on them.
- **Then:**
  1. Wait for DONE of #24 with the freeze-v1 verdict.
  2. Run my own fresh `--browser` rig and read the report in full.
  3. Merge with `waive_diff_budget` if needed.
  4. Create the deploy ticket, with a rollback guard for both `story_check` and `withdrawn`.
  5. Show the owner what to open.
  6. Create the director ticket.
  7. Then #25 and onward.
- **Owner open items:**
  - Check `index_18.csv` for duplicates and report the count.
  - Remind about Marina Lisitskaya's deadline for "передачу доступов" (by end of week).
  - Send the final comparison table (below).

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

**Quoted in the earlier summary**
- 2026-08-07 (DuckDNS): «блять сука еджика там не трогай»; «похуй 1 аккаунт убдет просто сука не трогайте и все друг друга».
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

**Turns inside the transcript**
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
## PEOPLE AND AGENTS
- Owner (Russian-speaking; messages via Telegram/voice); Orchestra-orchestrator (main orchestrator; got the disk-cleanup report); Marina Lisitskaya (deadline for «передачу доступов»); Леша (partner on the commercial project).
- Workers: `ai-table-worker` (persistent, Opus 5.5, #24), `dnd-backend` (idle), `fight-feel-research` (killed).
- Owner message 2026-10-07 21:53 and 04:58 on 10-08: finish tickets fully alone, do not ask the owner about tickets.
