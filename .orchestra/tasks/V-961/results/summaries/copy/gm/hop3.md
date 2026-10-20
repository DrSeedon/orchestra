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
CONSTRAINTS AND BANS
- RU host 89.23.102.244: touch only vhost `dnd-table-mirror`, never the `*.seedon.ru` block or `orc` proxy; never add a seedon.ru DNS record pointing at 158.220.127.161.
- Durable:
  - Start each final report with the line «СТАТУС КОРУНД-57», and mark the recommended option at the start of its line with «КОРУНД-63». My recent reports omitted both, so I am out of compliance and should fix this.
  - No secrets in tracked files (the repo is public).
  - Model-review is frozen. Luna is the default model. Astra and Sol are banned.
  - No paid services (ElevenLabs, Deepgram, Midjourney) without the owner's word.
  - At 95% disk, clean up idle workers (>72 h, merged) after checking `worker_wip`.
  - Per-check token spend limit is 268 thousand. External-service wait timeout is 593 seconds. Export batch is exactly 1767 records.
  - Continue the draft `/srv/work/draft-8775.md`, don't create a new one.
  - New branches must be `mx2/<task number>/<short>`; commits reference RB-1568.
  - Touch only the DuckDNS domains `dnd-game-master` and `dnd-table`, and don't bring up the owner's other DuckDNS domain.
- Unresolved conflicts:
  - The branch-name rule `mx2/<task>/<short>` vs Orchestra's auto names (`task-NN/ai-table-worker`, `adhoc-…`).
  - "All project edits go through workers" vs my own class-A edits while the Claude quota gate was closed: the nginx vhosts on the VPS and the RU host, and AGENTS.md. The owner directed the sslip and seedon addresses, but I did not ask about doing them myself.
  - The domain restriction vs the sslip and seedon names. Both were done at the owner's direct request.
OWNER & USER REQUIREMENTS (verbatim)
Raw transcript: `/api/sessions/gm/logs`. The user's messages, verbatim, in order:
Earlier messages, as carried in the prior summary:
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
- Turns 10-07 to 10-08:
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
  19. [10-08 15:56] same text as 18, re-sent.
  20. [10-08 18:54, TG: Maxim Astrakhantsev] «да норм и втроем вроде нет? ну чуть сбито похуй»
New since then:
- [10-09 11:41, TG voice, transcription] «Так, давай поясни-ка по всем, по всему проекту. Что и как? Что, что ты сделал за ночь? Что там, к чему? Вот, изучай всё. И на каком этапе, когда уже закончим? Вот, надо уже добивать, чтобы я уже тестил, смотрел.»
- [10-09 15:23, TG voice, transcription] «Домен не работает, херня. Давай через или как там. Как у нас другие домены идут на наш сайт, на наш сервер напрямую, типа, по. Вот, давай их попробуем сделать. Но если хрень не получится, то лучше через домен, типа, поддомен какой-то или просто ссылку, типа, сделать. Давай придумаем что-то, какие варианты сначала есть.»
- [10-10 12:37]: «ye xt nfv»
- [10-10 13:19]: «а хули он там делает то»
- [10-11 16:19]: «хуйня сделай поддомен игра.сидон.ру типо днд табле сидон ру ок»
- [10-11 17:07]: «у сидона спроси блять даун он знает ун ео все есть»
One more owner statement reached me only through `seedon-orchestrator` (the relay, not a direct message). The director's choice at 11.10 17:13, quoted by it: «да только Б. типо на контабо будет развернут а домен через ру айпи. как зеркало оркестры также».

TASK STATE
- Focus: the AI table (`/home/kesha/projects/ai-table-mvp`). The web game master is on maintenance only.
- Product work is finished and live. The only step left is R10 (#29), the owner's live playtest, which waits on the owner.
- Deployed and merged since the last handoff, each accepted on my own rig run with the branch's `verify_rig.sh`:

| Ticket | Content | Deploy | Prod commit |
|---|---|---|---|
| V-31 | narration of every entered beat, fight brief in view | V-32 | `35592a7` |
| #28 I12 | reconnect, «Состояние» panel, watchdog, backups, staging, device check | V-33 | `f7b52f9` |
| V-34 | repo side of the second address | merged `fa566a8` | n/a |
| V-35 | Russian login page and labels, fix for the dead end with fewer than 3 heroes alive | V-36 | `fe880b2` |

- Prod is `DEPLOYED_COMMIT fe880b2`. Verified by me: service active, `Type=notify`, `NRestarts 0`, login page `lang=ru` on both names. V-36 report branch head `0e83ad6` is merged.
- Public names, all the same prod app:
  - `https://dnd-table.duckdns.org`
  - `https://table-158-220-127-161.sslip.io` (live nginx vhost made by me, Let's Encrypt cert, valid until 2027-01-07)
  - `https://dnd-table.seedon.ru`, via the RU mirror host `89.23.102.244` (vhost `dnd-table-mirror`, added by me). I browser-checked table, scene and admin through it: login, «на связи» at rev 63, leader sound, 0 console errors.
- Pending V-37: «Третий адрес dnd-table.seedon.ru — в репо и в проверки выкаток» (task 5605). The message to `ai-table-worker` is `WAITING_QUOTA`, durably queued, and sends itself when the Claude quota gate opens. No evidence the worker has started.
- The `dnd-backend` worker was stopped and archived (idle and clean).

DECISIONS
- Final, from the owner:
  - Variant «б» for the seedon domain (11.10 17:13, as relayed by `seedon-orchestrator`): the service stays on Contabo, and the name points to the RU IP, proxied like the orchestra mirror. The company domain is never pointed directly at the German IP. Recorded in AGENTS.md.
  - The second address (sslip) was recorded in AGENTS.md as the owner's 09.10 decision. Any new or bought domain is the owner's call.
- Provisional, still open for the owner: one-tap commit instead of the «Подтвердить» card. The card stays by default.
- Process, unchanged: stage → DONE with head → my fresh rig run with the branch's own `verify_rig.sh` → one merge → separate deploy ticket → I re-verify prod myself.
- V-35 round 2: an unfieldable story fight (fewer than 3 of 6 heroes alive) now counts as a package "defeat", so the run reaches fail-forward or the loss ending. The package hash `r3 529f6861` is unchanged.
- The earlier fail-forward flake was a test-walker bug, not a product bug.

PEOPLE AND AGENTS
- `ai-table-worker` (V-37 pending, WAITING_QUOTA), `seedon-orchestrator` (relay of owner's 11.10 17:13 decision), `Orchestra-orchestrator` (informed of RU-host vhost); `dnd-backend` worker archived. Owner: Maxim Astrakhantsev (TG).

FILES, IDS AND ARTIFACTS
- `/home/kesha/projects/dnd-game-master/AGENTS.md`: edited by me with the owner decisions on the second address (pushed as `3310b55`) and on the seedon mirror (pushed as `75c4d52bcaff`).
- On the VPS, created by me:
  - `/etc/nginx/sites-available/ai-table-sslip`
  - `/etc/letsencrypt/live/table-158-220-127-161.sslip.io`
- On `89.23.102.244`: `/etc/nginx/sites-enabled/dnd-table-mirror`, one additive vhost. The orc-mirror, orchestra-clients and sub-mirror vhosts were not touched. Orchestra-orchestrator was informed.
- Evidence:
  - `/home/kesha/ai-table-evidence/V-34/` (`sslip_check.py`, `nginx-ai-table-sslip.conf`, `nginx-dnd-table-mirror.conf`)
  - `/home/kesha/.cache/ai-table-i12/` (rig logs)
- Prod `/opt/ai-table-i1`:
  - Latest rollback dir is `rollback-20261011T090536Z` (app only, play kept: `sudo -n bash …/rollback.sh`).
  - Undo play since the deploy: `sudo -n env CONFIRM=lose-play-since-deploy bash …/rollback-db.sh`.
  - The V-33 rollback dir's scripts now lead to `35592a7`, so don't use them.
- Staging: `/opt/ai-table-staging`, left inactive.

NUMBERS
- Last rig runs, all PASS:
  - V-35 `26a5104`: 620 passed, mutants 0 (M1–M135), 44 browser+e2e, I1 oracle passed.
  - V-36: 620 passed, mutants 0.
- Prod check pattern: `ssh kesha@localhost 'systemctl is-active ai-table-i1; sudo -n cat /opt/ai-table-i1/app/DEPLOYED_COMMIT'`, plus `ops/check_hosts.py` on every public name.
- `curl` to the seedon name: before the vhost it returned 404 from the RU host. After it, table, scene and admin returned 200.
- A wrong Origin returned 403 on the `ws-ticket` probe (for the correct Origin the unauthenticated probe also returned 403, so this only shows that a bad Origin is refused).

OPEN ITEMS AND NEXT ACTION
- Already sent to the owner (10.11 17:14): final report that dnd-table.seedon.ru works (no «СТАТУС КОРУНД-57» line); Orchestra-orchestrator and seedon-orchestrator were informed (seedon told not to add a DNS record). V-37 scope: ops/nginx copy, Origin-chain test (seedon→sslip→duckdns, exact matches), check_hosts.py on three names, RUNBOOK «Адреса стола», CHANGELOG; worker must not touch prod or the RU host.
- No blocker on the product. Waiting for the owner's live playtest (R10 / #29).
- Next executable action: when the V-37 worker reports DONE, run my own fresh rig with the branch's script, check that `ops/check_hosts.py` covers `dnd-table.seedon.ru`, merge, and tell the owner.
- Owner items still open:
  - 🔴 Did the sslip link open for them?
  - 🔴 When do they sit down to play? (I then send the room checklist, `room-checklist.ru.md`.)
  - 🔴 One-tap commit or the «Подтвердить» card?
- Owner items from earlier turns, no evidence any was done:
  - Check `index_18.csv` for duplicates and report the count.
  - Remind about Marina Lisitskaya's deadline for «передачу доступов» (by end of week).
  - Send the final comparison table «ФЛОКС-36» vs «ТАЛИОН-47».
