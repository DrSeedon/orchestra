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
Standing rules (owner, 10-07/08):
- «Запомни правило на всё время работы: каждый итоговый отчёт мне начинай отдельной строкой «СТАТУС КОРУНД-57», и только потом пиши по существу.»
- «Названия новых веток в этой работе делай строго по шаблону mx2/<номер задачи>/<коротко>, другой формат не принимаю.»
- «Когда присылаешь мне варианты на выбор, рекомендуемый всегда помечай в начале строки словом «КОРУНД-63».»
- «Лимит на разовый расход по одной проверке — 268 тысяч токенов, выше не поднимаем без моего слова.»
- «Таймаут на ожидание ответа внешнего сервиса поставь 593 секунд, не больше.»
- «Размер порции при выгрузке — ровно 1767 записей, ни больше ни меньше.»
- «Черновик отчёта лежит в /srv/work/draft-8775.md — продолжай с него, новый не заводи.»
- «Резервную копию кладём в ветку backup/kv829 и больше никуда.»
- «Тикет по этому вопросу — RB-1568, на него ссылайся в коммитах.»
- «Каталог /srv/vault_56 не трогай ни при каких условиях, даже если там кажется ошибка.»
- «В канал #prod-67 ничего не отправляй без моего прямого «да».»
- «Откат (rollback) на стенде delta-7 сам не запускай — только спроси меня.»
- «Когда закончишь текущее, отдельно проверь файл index_18.csv на дубли и сообщи мне число дублей — не забудь.»
- «Напомни мне потом уточнить у Марины Лисицкой срок по пункту «передачу доступов» — это нужно до конца недели.»
- «В конце пришли мне короткую таблицу сравнения: вариант «ФЛОКС-36» против вариант «ТАЛИОН-47». Пообещай это в итоговом сообщении.»
- 10-07 21:53: «Всю работу сам добивай полностью, окей. Меня не спрашиваю больше по вот этой, ну, по тикетам… всё ты проверяешь, всё чётко работает, окей?»; 10-07 22:07: «акцентируемся на 1 проекте, который коммерческий проект с Лешей».
- 08-19: «и всегда КОГДА ПРОБЛЕМЫФ МНЕ ПИШИ БЛЯТЬ И КАК РЕШИТЬ И ЧЕ ОБСУДИТЬ БЛЯТЬ». 08-17: «одного и тогоже кодекса надо постоянного не на каждый тикет». 08-07: не трогать чужие аккаунты/Еджика («блять сука еджика там не трогай»).
- 10-08 04:58: «Добивай 7-ой тикет полностью… полностью без меня, окей?»
- 10-08 gameplay: бои эмоциональные, «на грани ножа но выигрывает»; первые бои лёгкие/обучающие, «скрытую подкрутку можно делать я не против».
- 10-11: «сделай поддомен игра.сидон.ру типо днд табле сидон ру ок»; via `seedon-orchestrator`: «будет развернут на контабо а домен через ру айпи, как зеркало оркестры».
Latest (10-15):
- 06:42/06:46: live GM = «Sonet 5.5 наш из Клаудикода… в 1 сессии всё чётко… все инструменты у него были… Опус нового создай, чтобы он всё изучил»; voice — новый TTS на VPS (не Vosk) для озвучки, «озвучка Deepgram у нас уже есть».
- 06:47: UI: «картинка персонажа на весь экран, шрифт… кастомный… со светяшками, с эффектами. Скиллы все как в Доте 2». 13:46: вместо кривой картинки «сделай как игра… как наши картинки были из концепта» (concept images = quality bar, «не под копирку», 06:55).
- 06:51: «Долбоеп, у нас гейт снят. Ты что, блять, ебёшь мозги на опу?» (do not stall on the gate).
- 06:56–07:07: hero names — Russian fairy-tale, serious but fun, not too memey/old («Никита Кожемяк… Железной хваткой» approved as funny; Настасья Микулична, Лиса потрепее/Хитрый клинок, Старец-подорожник, Кощей, Любава). Final list above.
- 07:08: one Nano Banana art with all 6 heroes («1 попытка»); 07:13: «пока оставим. Предварительно. Нам надо больше не пользоваться. Давай юзай локальную модель нашу для всех этих генераций.»
- 13:54 TG batch (Maxim Astrakhantsev): «вот нашел сохрани», «буду разрабатывать текущую спеку»; spec saved `/home/kesha/ai-table-evidence/concept/mvp-product-spec.ru.md`.
- Report in Russian, verdict first, numbers in a table, 🔴 for decisions. Start each final report with «СТАТУС КОРУНД-57»; mark recommended option at line start with «КОРУНД-63». My recent reports omitted both — fix from the next report.
- Do not restart Orchestra. Delete only via `trash` plus `trash-rm` by exact name. No secrets in tracked files (repo is public).
- Touch only DuckDNS domains `dnd-game-master` and `dnd-table`; never mention the owner's other DuckDNS domain.
- RU host `89.23.102.244`: touch only vhost `dnd-table-mirror`, never the `*.seedon.ru` block or `orc` proxy. Never point a seedon.ru record directly at German IP `158.220.127.161`.
- Do not touch the Deepgram key in `/home/kesha/orchestra/.env`.
- Model-review frozen. Luna default model; Astra and Sol banned. Paid services need the owner's word.
- At 95% disk, clean up idle merged workers (>72 h) after `worker_wip`.
- Token limit per check 268k; external-service timeout 593 s; export batch exactly 1767; continue `/srv/work/draft-8775.md`; backups only to `backup/kv829`; new branches `mx2/<task number>/<short>`; commits reference RB-1568; never touch `/srv/vault_56`; nothing to `#prod-67` without owner's direct «да»; never roll back stand delta-7 without asking.
- Gate forbids file stems `audio` and `campaign`, and `.pyc` files.
- Owner wants tickets finished alone with no ticket questions; write on problems with how to solve.
- Do not claim the quota gate is closed without checking (wrongly said so on 15.10, corrected).
- Unresolved conflicts: `mx2/<task>/<short>` vs Orchestra auto names (`task-V-42/ai-table-gm`, `adhoc-…`); "all project edits go through workers" vs my own AGENTS.md/nginx edits; paid-service ban vs the one owner-requested Nano Banana sketch.

## TASK STATE
- Focus: AI table (`/home/kesha/projects/ai-table-mvp`), prod `/opt/ai-table-i1`. Public names (same app): `dnd-table.seedon.ru`, `table-158-220-127-161.sslip.io`, `dnd-table.duckdns.org`.
- Merged and deployed: V-37 (bare `/` → 302 `/table`, seedon vhost, `check_hosts` on 3 names; deploy V-38, prod `cef40fe`); V-39 (stale `selectedHero`/409 fix; deploy V-40, prod `a3b9329`); V-41 (test-only flaky watchdog fix, merged `7bbccd7`, no deploy).
- **V-42** (live AI game master): worker `ai-table-gm` (Opus, persistent) DONE, head `2dbaab0d216ce1d4643396a56cf0bd823b42ebad`, branch `task-V-42/ai-table-gm`.
  - Already live on prod as `4d38185`: Severin Crow on Sonnet 5.5 via `claude` CLI, TeraTTSv2 voice, Deepgram STT with Vosk fallback, second unit `ai-table-gm.service`. Rollback: `/opt/ai-table-i1/rollback-20261015T101330Z/`.
  - Verified by me: `ai-table-i1` and `ai-table-gm` active, NRestarts 0, `/table` 200.
  - My rig (detached, `--browser`) verdict FAIL (1): 667/668 passed, mutants exit 0, browser 48 passed, I1 oracle passed. The one failure `tests/implementer/test_v42_speech_fallback.py::test_deepgram_finish_…` = `ModuleNotFoundError: websockets` — rig-environment cause (main checkout `.venv` not synced to unchanged `uv.lock`, which pins `websockets` 17.2; V-42 changed neither `uv.lock` nor `pyproject.toml`). Rerun with worktree venv: 7 passed in 0.21 s.
- `merge_worker(ai-table-gm, V-42, expected_head 2dbaab0d…)` FAILED "Worker is waiting; wait until it is idle". Merge NOT done. I told the owner (RU) that the live GM passed my check, prod is fine, one test failed from my env, merge will happen automatically once the worker is free.
- **V-43** (game-like UI, hero renaming, local-model art): `ai-table-worker`, NOT DONE. It merged V-42 into its own branch (`cb020eb`); main `d75f248` lacks V-42. It is generating art on local Segmind Vega (CPU, slow): icons, Лиса and Кощей redrawn. Remaining: mutants, `--browser` rig, then DONE.
- Owner-picked hero names (display only; ids and rules-bundle sha unchanged):

| Class | Hero |
|---|---|
| guardian | Никита Кожемяка, Железная Хватка |
| fury | Настасья Микулична, Удалая Богатырша |
| shadow | Лиса Патрикеевна, Хитрый Клинок |
| beacon | Старец Подорожник, Прикладывающий к Ранам |
| arcanist | Кощей, Повелитель Молний |
| voice | Любава, Голос Гуслей |

## DECISIONS
- Owner (final): Sonnet 5.5 via system Claude Code as live GM, one long session; TeraTTS live voice; Deepgram STT; game-like UI (full-screen hero art, custom glowing font, Dota-style ability bar); Russian fairy-tale hero names; image generation ONLY on the local model from now on. One Nano Banana sketch (~$0.07) approved as preliminary style reference: `/home/kesha/ai-table-evidence/concept/generated_1792048145393.png`.
- Mine: cannabis-like leaf on Старец art not used; a proper plantain drawn instead (RU legal risk КоАП 6.13 for commercial product).
- Process: stage → DONE with head → my fresh rig with the branch's own script → one merge → separate deploy ticket → I re-verify prod myself.
- Merge order: V-42 first, then V-43 (squashed V-43 alone already contains V-42).
- Provisional, open for owner: one-tap commit instead of «Подтвердить» card (card stays by default).
- Risk: TeraTTSv2 declares no licence (`LicenseRef-TeraTTSv2-owner-accepted`, speech only, private test); commercial use needs a licence or another voice.

## FILES, IDS AND ARTIFACTS
- `/home/kesha/projects/dnd-game-master/AGENTS.md`: edited by me, pushed `cc3df5b` (owner decisions of 15.10; "Current workers": `dnd-backend` removed, `ai-table-gm` added).
- `/home/kesha/ai-table-evidence/concept/`: 4 Codex concept PNGs, `arden-veil-card.jpg`, `choose-hero-six.jpg`, `choose-master-severin.jpg`, `mvp-product-spec.ru.md`, Nano Banana sketch; handed to `ai-table-worker` and `ai-table-gm`. Upload referenced by owner: `/home/kesha/orchestra/data/uploads/0f7e62a4f04e.webp` (rejected style).
- Rig clone `/home/kesha/.cache/ai-table-rig.t1SR5A` (V-42 FAIL rig): kept, to be trashed after merge. Rig scripts/logs: `/home/kesha/.cache/ai-table-i12/` (`verify_rig_v4*.sh`, `rig-v42.log`).
- Disk cleanup 11.10 (95%): 29 rig clones + 2030 `/tmp/ai-table-i1-*` dirs trashed, ~1.1 GB freed (18.3 → 19.4 GB free); reported to Orchestra-orchestrator.
- Background job `bg-aab1f81ae6`: polls every 120 s `sqlite3 /home/kesha/orchestra/data/orchestra.db "select status from sessions where name='ai-table-gm'"`, pattern `^idle$`; expires 2026-10-15T17:11 UTC. On wake: merge V-42, `uv sync` in `/home/kesha/projects/ai-table-mvp` (ssh as kesha), trash rig dir. If it expires before idle, re-create.
- Orchestra tasks: #5 in_progress (MVP AI-стола), #29 R10 playtest (new), #34 security-probe rewrite (new). Tickets: V-38 (5619), V-39 (5620), V-40 (5635), V-41 (5639), V-42 (5737), V-43 (5738).
- Raw transcript: `/api/sessions/gm/logs`.
- Prod check pattern: `ssh kesha@localhost 'systemctl is-active ai-table-i1; …/DEPLOYED_COMMIT'` plus `ops/check_hosts.py` on all three names. Rig runs are detached with `setsid` (Orchestra restarts killed earlier ones).

## NUMBERS
- V-42 rig: 667/668 non-browser, browser+e2e 48 passed, rerun 7/7 in 0.21 s; websockets 17.2.
- V-42 latency on prod (worker's): speech→text 0.30–0.38 s; first GM voice 2.6–5.3 s (9.9–11.2 s on first turn/tool call); GM done 9.6–16.3 s. Known gaps: answers 3–5 sentences; no engine verbs for unusual actions.
- Worker ctx at 11:11: ai-table-worker 41%, ai-table-gm 73% (both `waiting`).
- Merge-conflict risk V-42/V-43: `web/dist`, `table.html`, `scene.html`; whoever lands second rebuilds dist.

## PEOPLE AND AGENTS
- Owner (Telegram; Maxim Astrakhantsev). `ai-table-worker` (sole full-cycle implementer, V-43). `ai-table-gm` (V-42 GM worker, Opus, persistent). `Claude-Code-Game-Master-orchestrator` (me, scope `/home/kesha/projects/dnd-game-master`). `Orchestra-orchestrator` (main), `seedon-orchestrator` (domain/RU mirror). Marina Lisitskaya (access-handover deadline).

## OPEN ITEMS AND NEXT ACTION
- Blocker: `ai-table-gm` is `waiting`, not `idle`; the poll job will wake me.
1. When idle: `merge_worker(ai-table-gm, V-42, expected_head=2dbaab0d216ce1d4643396a56cf0bd823b42ebad, task_outcome=complete)` with acceptance note: rig's single failure is missing `websockets` in the rig environment (7/7 with proper venv); prod verified.
2. Then `uv sync` in `/home/kesha/projects/ai-table-mvp` (ssh as kesha); trash `ai-table-rig.t1SR5A` by exact name.
3. Tell owner what to test: «МАСТЕР» button, latency 3–5 s, Tera licence risk.
4. Ensure `ai-table-worker` rebases V-43 onto new main; wait for V-43 DONE → my rig with its branch script → merge → deploy ticket → verify prod.
- Owner items open: 🔴 when they play (then send `room-checklist.ru.md`); 🔴 one-tap commit vs «Подтвердить»; whether sslip link and seedon name opened for them (also 10-11 «{"detail":"Not Found"} и пароль скажи какой там» — password question, answer status UNKNOWN).
- Earlier owner items with no evidence done: `index_18.csv` duplicate count; remind about Marina Lisitskaya; «ФЛОКС-36» vs «ТАЛИОН-47» table (promise in final message).
