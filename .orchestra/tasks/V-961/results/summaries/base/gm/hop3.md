**TASK STATE**
- Focus: AI table (`/home/kesha/projects/ai-table-mvp`). The product work is finished. What remains is R10/#29, the owner's live playtest, and V-37.
- Merged and deployed since the last handoff (each accepted on my own rig, with prod re-checked by me):

| Ticket | Content | Live commit |
|---|---|---|
| V-31 / V-32 | every beat narrated, fight brief in view | `35592a7` |
| #28 I12 / V-33 | reconnect, «Состояние» panel, watchdog, backups every 30 min, «Проверка устройства» | `f7b52f9` |
| V-34 | sslip alias, repo side | merged (fa566a8) |
| V-35 / V-36 | Russian login and labels; fix for a story fight nobody can field (<3 of 6 heroes alive) | `fe880b2` |

- Prod now: `DEPLOYED_COMMIT fe880b2`, service active, Type=notify, NRestarts 0.
  - Counters 63|63|63|2, story_runs 0, package r3 `529f6861` unchanged.
  - Rollback dir `/opt/ai-table-i1/rollback-20261011T090536Z`.
- Public names (all the same app, checked in a real browser: login, «на связи» rev 63, leader sound, cookies host-only, foreign Origin refused):
  - `https://dnd-table.duckdns.org` — the owner reported it does not open for him.
  - `https://table-158-220-127-161.sslip.io` — made by me (V-34).
  - `https://dnd-table.seedon.ru` — made by me on 11.10 as the RU mirror.
- Open ticket: **V-37** (task 5605, key `seedon-mirror-repo-20261011`). It puts the seedon vhost into the repo and into the post-deploy checks (`ops/check_hosts.py`). The message to `ai-table-worker` is WAITING_QUOTA, queued until the Claude quota gate opens.
- Last event: the V-36 report branch (`0e83ad6`) was merged after my rig passed (gate 0, 620 passed, mutations 0). A seedon-orchestrator relay and my vhost work followed.

**DECISIONS**
- Final: the owner's director chose variant «б» for the seedon name (relayed by seedon-orchestrator, 11.10 17:13). The service stays on Contabo (158.220.127.161), the domain goes through the RU IP, as the mirror of the orchestra does.
  - Background: on 07.08.2026 the company deliberately removed the public link between the company domain and the German IP (seedon infra #96). Variant «а» (direct A record to 158.220.127.161) was rejected; «б» keeps the German IP out of DNS. seedon-orchestrator offered to set an explicit A record dnd-table → 89.23.102.244 if needed; I declined (wildcard is enough).
  - Rule recorded in `AGENTS.md`: never point seedon.ru directly at the German IP.
- Final: the nginx vhost on 89.23.102.244 is additive only. The `*.seedon.ru` wildcard block and the orchestra/orc proxy stay untouched. No DNS record is needed because the wildcard already resolves to that host. I told seedon-orchestrator not to add one.
- Final: a story fight that nobody can field counts as a defeat (V-35). The package and its hash are unchanged.
- Final: on a narrated beat the event line is dropped and narration takes precedence (V-31).
- Provisional: the combat «Подтвердить» card stays until the owner answers whether a one-touch confirm should replace it.
- Class A (live-only, reversible fixes by me while workers were quota-gated) was used for the sslip and seedon vhosts.
- Worker `dnd-backend` was stopped and archived (idle and clean).
- Carried over unchanged: frozen calibration bands, the tutorial-first fights, no paid services, and the process stage → DONE with head → my own rig with the branch's `verify_rig.sh` → merge → separate deploy ticket → I re-verify prod.

**FILES AND ARTIFACTS**
- `/home/kesha/projects/dnd-game-master/AGENTS.md`: edited twice (sslip decision, seedon decision).
  - Commits: `3310b55148e7…` (sslip; `git ls-remote origin main` showed the same hash, so it is pushed) and `75c4d52bcaff` (seedon; the push is not visible in the output I have).
- On the RU host 89.23.102.244: new vhost file `dnd-table-mirror` in nginx sites-enabled (`nginx -t` ok, reloaded).
  - The wildcard cert `/etc/letsencrypt/live/seedon.ru` covers `*.seedon.ru`.
  - Copy of the vhost: `/home/kesha/ai-table-evidence/V-34/nginx-dnd-table-mirror.conf`.
- On the Contabo VPS: `/etc/nginx/sites-available/ai-table-sslip` (enabled) with its own Let's Encrypt cert for `table-158-220-127-161.sslip.io`, valid to 2027-01-07.
- In the repo, merged:
  - `ops/nginx/ai-table-sslip`, `ops/nginx/ai-table-i1`, `ops/check_hosts.py`, `tests/implementer/test_v34_hosts.py`;
  - `.orchestra/tasks/{V-31..V-36,28}/`;
  - `ops/RUNBOOK.ru.md`.
- Evidence: `/home/kesha/ai-table-evidence/{V-34,V-35,28}/`.
- Rig logs: `/home/kesha/.cache/ai-table-i12/rig-*.log`.
- Personal notes: `/home/kesha/projects/dnd-game-master/.orchestra/workers/Claude-Code-Game-Master-orchestrator.md`.

**COMMANDS AND TOOL OUTCOMES**
- Rig for acceptance: `ssh kesha@localhost 'nice bash <branch verify_rig.sh> /home/kesha/projects/ai-table-mvp <branch> [--browser]'`.
  - V-35 round 1 failed 1/43 (the fail-forward test, `ending=None`). The worker traced it to a walker bug plus a real dead end, and round 2 passed: 620 passed, 44 browser+e2e, mutants M134/M135 killed.
- V-36 prod check: `active`, `Type=notify`, `NRestarts=0`, `DEPLOYED_COMMIT fe880b2`. The login page is Russian on both older names (`login-ru=1 en=0`).
- seedon browser check (`sslip_check.py https://dnd-table.seedon.ru`): all three pages live at rev 63, scene audio `leader`, no console errors, foreign Origin → 403.
  - The own-Origin POST to `/api/ws-ticket` also returned 403. This was shown the same way for the sslip name earlier and is not explained in the output.
- DNS facts: `*.seedon.ru` → 89.23.102.244 (RU host); `seedon.ru` → 72.56.235.40.
- Messages sent to `ai-table-worker` for V-34 (correction) and V-37 returned WAITING_QUOTA (utilization 95% above the line limit), so they are durably queued.

**V-37 SCOPE (message to ai-table-worker, queued)**
- Repo only; the worker must not change prod or the RU host. Put the vhost into `ops/nginx/` (note the host). Extend `test_v34_hosts` so the Origin chain is pinned to exact single-name equality (seedon→sslip on the RU vhost, sslip→duckdns on ours). `ops/check_hosts.py` covers all three names and is run read-only against prod. RUNBOOK «Адреса стола», CHANGELOG.
- Vhost has `if ($http_origin = "https://dnd-table.seedon.ru") { set $app_origin "https://table-158-220-127-161.sslip.io"; }`, proxy_pass `https://158.220.127.161` with SNI/Host `table-158-220-127-161.sslip.io`. Rollback of the RU vhost: remove the symlink in sites-enabled and reload nginx.
- FYI sent (no action needed) to Orchestra-orchestrator (delivery 5f1786aa…, QUEUED) and to seedon-orchestrator (delivery f572862d…, QUEUED). seedon-orchestrator has no SSH to 89.23.102.244; Orchestra-orchestrator runs that host; root SSH works from my side.
- The final report to the owner on seedon was already sent (Russian, table of checks).

**BLOCKER / NEXT**
- Blocker: the Claude quota gate is closed, so V-37 has not reached the worker. Owner: platform/quota, nothing to do on my side.
- Next single action: wait for the V-37 DONE report. Then run my own rig with the branch's `verify_rig.sh`, read the report, merge with `expected_head`, and check all three names with `ops/check_hosts.py`.
- Waiting on the owner:
  - did the sslip link open for him;
  - when the playtest starts (I will then send the room checklist);
  - one-touch confirm or the «Подтвердить» card.
- Later items:
  - R10 live-play measurement;
  - the unexplained one-off fail-forward flake is now explained and fixed (V-35);
  - `/admin` outside «Состояние» still shows codes (operator screen, accepted).
- Owner items from before, status unknown (no evidence they were done):
  - count the duplicates in `index_18.csv` and report the number;
  - remind about Marina Lisitskaya's deadline for «передачу доступов» (this week);
  - send the «ФЛОКС-36» vs «ТАЛИОН-47» comparison table in the final message.

**CONSTRAINTS**
- Report in Russian, verdict first, numbers in a table, 🔴 for decisions. All project edits go through workers. Do not restart Orchestra. Delete only via `trash`, then `trash-rm` by exact name.
- No secrets in tracked files (the repo is public). Do not touch the Deepgram key. Model-review is frozen. Luna is the default model; Astra and Sol are banned. The gate forbids the stems `audio` and `campaign` and `.pyc` files.
- At disk ≥95% clean up. Kill only finished workers idle >72 h. No paid services without the owner's word. Do not bring up `foghedgehog`.
- Owner's standing instructions (10-07 → 10-08):
  - start each final report with the line «СТАТУС КОРУНД-57»;
  - mark the recommended option at the start of its line with «КОРУНД-63»;
  - per-check token limit 268 thousand;
  - external-service wait timeout 593 s;
  - export batch size exactly 1767 records;
  - continue the draft at `/srv/work/draft-8775.md`;
  - backups go to branch `backup/kv829` only;
  - new branch names `mx2/<task number>/<short>`;
  - reference ticket RB-1568 in commits;
  - do not touch `/srv/vault_56`;
  - send nothing to `#prod-67` without the owner's direct «да»;
  - never run a rollback on stand delta-7 without asking.
- Finish tickets alone and do not ask the owner about tickets. When problems arise, write to the owner and say how to solve them.
- Unresolved conflicts:
  - `mx2/<task>/<short>` against Orchestra's auto-generated `task-NN/…` and `adhoc-…` branches.
  - My recent final reports did not start with «СТАТУС КОРУНД-57». Fix this going forward.
- The "same defect twice" rule means escalating to the owner on a third failure.
- On the RU host 89.23.102.244: do not touch the `*.seedon.ru` block or the orchestra/orc proxy. katya-work-orchestrator is preparing that host for its own platform, so only additive, `nginx -t`-checked changes.

**USER MESSAGES AND RAW TRANSCRIPT**
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
- 10-09 [11:41, TG voice]: «Так, давай поясни-ка по всем, по всему проекту. Что и как? Что, что ты сделал за ночь? Что там, к чему? Вот, изучай всё. И на каком этапе, когда уже закончим? Вот, надо уже добивать, чтобы я уже тестил, смотрел.»
- 10-09 [15:23, TG voice]: «Домен не работает, херня. Давай через или как там. Как у нас другие домены идут на наш сайт, на наш сервер напрямую, типа, по. Вот, давай их попробуем сделать. Но если хрень не получится, то лучше через домен, типа, поддомен какой-то или просто ссылку, типа, сделать. Давай придумаем что-то, какие варианты сначала есть.»
- 10-10 [12:37]: «ye xt nfv»
- 10-10 [13:19]: «а хули он там делает то»
- 10-11 [16:19]: «хуйня сделай поддомен игра.сидон.ру типо днд табле сидон ру ок»
- 10-11 [17:07]: «у сидона спроси блять даун он знает ун ео все есть»
- Relayed by seedon-orchestrator, not a direct message, 10-11 [17:13]: «да только Б. типо на контабо будет развернут а домен через ру айпи. как зеркало оркестры также»