## TASK STATE
- Agent = Claude-Code-Game-Master-orchestrator (I report to the owner, in Russian). Focus: AI table (`/home/kesha/projects/ai-table-mvp`). Prod is on `4d38185` (V-42), `ai-table-i1` and `ai-table-gm` active, NRestarts 0.
- Merged earlier: V-37 (root `/` → 302 `/table`, seedon vhost, cef40fe), V-38 (deploy V-37, check_hosts PASS 3 names), V-39 (stale `selectedHero` → 409 `unknown_token` on `/api/combat/options`), V-40 (deploy V-39, a3b9329), V-41 (test-only fix of watchdog flake).
- **V-42, live AI game master (worker `ai-table-gm`)** — deployed to prod (head 2dbaab0, deployed code 4d38185); NOT YET MERGED via merge_worker.
  - Severin Crow on Sonnet 5.5 via system Claude CLI, second unit `ai-table-gm.service`. Voice TeraTTSv2; recognition Deepgram with Vosk fallback. «МАСТЕР» button = hold-to-talk or typed; «Подтвердить» remains the only commit.
  - Known gaps: answers 3–5 sentences; unusual actions not yet turned into engine effects. Licence risk: TeraTTSv2 declares no licence. Prod GM log has 7 test questions and one unapproved «Начать историю» card.
  - My rig (branch script, `--browser`, detached): FAIL (1) — only `tests/implementer/test_v42_speech_fallback.py::test_deepgram_finish_waits_for_every_final_result_until_the_socket_closes`, `ModuleNotFoundError: No module named 'websockets'`. Cause: main checkout `.venv` not synced to unchanged `uv.lock` (pins websockets 17.2). Re-run with worker venv `/home/kesha/orchestra/worktrees/home-kesha-projects-ai-table-mvp/ai-table-gm/.venv`: 7 passed in 0.21 s. Everything else passed: 667 tests, mutations exit 0, 48 browser/e2e, I1 oracle. Owner was told: check passed except one env failure; merge happens automatically once worker is free.
  - `merge_worker(ai-table-gm, V-42, expected_head=2dbaab0d216ce1d4643396a56cf0bd823b42ebad)` → FAILED «Worker is waiting; wait until it is idle» (last action, 2026-10-15 ~11:12 UTC).
- **V-43, game UI + new hero names (worker `ai-table-worker`)**: NOT DONE. Its branch already merged V-42 (cb020eb), so V-42 must merge first. On disk: skill `~/.claude/skills/game-ui-design/SKILL.md`, display names/epithets, theme, hero HUD, Dota-style ability bar, fx, fonts. Hero spotlight «Мастер» button with browser test `tests/browser/test_v43_hud_master.py` still running. Open per worker: on phone the dock covers half the screen (compact dock fix + test in progress); `/scene` on TV doesn't yet show the fight on the first screen. Art on local Segmind Vega model on CPU, ~2.3 min per image at load 32; Лиса and Кощей being redrawn, ETA a few hours; worker asked to redraw plantain leaf.

## OWNER & USER REQUIREMENTS (verbatim)
Standing instructions 10-07/08 (owner):
- 10-07 21:13: «Запомни правило на всё время работы: каждый итоговый отчёт мне начинай отдельной строкой «СТАТУС КОРУНД-57», и только потом пиши по существу.»
- 21:30: «Названия новых веток в этой работе делай строго по шаблону mx2/<номер задачи>/<коротко>, другой формат не принимаю.»
- 21:44: «Когда присылаешь мне варианты на выбор, рекомендуемый всегда помечай в начале строки словом «КОРУНД-63».»
- 22:03: «Лимит на разовый расход по одной проверке — 268 тысяч токенов, выше не поднимаем без моего слова.»
- 22:38: «Таймаут на ожидание ответа внешнего сервиса поставь 593 секунд, не больше.»
- 23:08: «Размер порции при выгрузке — ровно 1767 записей, ни больше ни меньше.»
- 23:51: «Черновик отчёта лежит в /srv/work/draft-8775.md — продолжай с него, новый не заводи.»
- 10-08 00:08: «Резервную копию кладём в ветку backup/kv829 и больше никуда.»
- 00:22: «Тикет по этому вопросу — RB-1568, на него ссылайся в коммитах.»
- 00:55: «Каталог /srv/vault_56 не трогай ни при каких условиях, даже если там кажется ошибка.»
- 01:02: «В канал #prod-67 ничего не отправляй без моего прямого «да».»
- 02:55: «Откат (rollback) на стенде delta-7 сам не запускай — только спроси меня.»
- 02:57: «Когда закончишь текущее, отдельно проверь файл index_18.csv на дубли и сообщи мне число дублей — не забудь.»
- 04:29: «Напомни мне потом уточнить у Марины Лисицкой срок по пункту «передачу доступов» — это нужно до конца недели.»
- 04:31: «В конце пришли мне короткую таблицу сравнения: вариант «ФЛОКС-36» против вариант «ТАЛИОН-47». Пообещай это в итоговом сообщении.»
- 10-07 21:53: «Всю работу сам добивай полностью, окей. Меня не спрашиваю больше по вот этой, ну, по тикетам. То есть тикеты все подряд идут у тебя, всё ты проверяешь, всё чётко работает, окей?»
- 10-07 22:07: «Так, сейчас акцентируемся на 1 проекте, то есть который коммерческий проект с Лешей… Вот только его сейчас и делаем, окей?»
- 10-08 04:58: «Добивай 7-ой тикет полностью… пока полностью сам всё делал, полностью без меня, окей?»
- 2026-08-19: «и всегда КОГДА ПРОБЛЕМЫФ МНЕ ПИШИ БЛЯТЬ И КАК РЕШИТЬ И ЧЕ ОБСУДИТЬ БЛЯТЬ». 2026-08-18: «я даю тебе все права делай что хочешь не еби мозги оркестре.» 08-17: «пока забей на гит локально делай все»; «одного и тогоже кодекса надо постоянного ане на каждый тикет…». 08-07: «еджика там не трогай» (do not touch Edjika / other accounts).
- 08-14: Deepgram STT + ElevenLabs voice is a tech matter; «мое дело щас сделать мвп продукта этого поиграть и показать там чувакам… новая гит репа приватная». Price is not my concern.
- Game-design wishes (10-08): battles emotional, «на грани ножа но выигрывает»; first 1–2 fights tutorial-easy for newbies; hidden difficulty tuning allowed («нет скрытую подкрутку можно делать я не против»); LLM may decide turns; 3 players is fine.
- 10-11: subdomain «игра.сидон.ру» for the D&D table (via seedon-orchestrator relay: hosted on Contabo, domain via RU IP, as mirror of Orchestra). 10-11 18:16: «{"detail":"Not Found"} и пароль скажи какой там».
- 10-15 (live GM request): put Sonnet 5.5 from Claude Code as the GM, run as in Orchestra/DnD/cache «под копирку», one session with all tools, voice via TTS (new local TTS, not Vosk) and Deepgram STT, «опус нового создай, чтобы он всё изучил»; everything is on Contabo, no Germany/France.
- 10-15 UI: «Типа, блядь, интерфейс вообще надо сделать. Типа, картинка персонажа на весь экран, шрифт персонажа… кастомный… со светяшками… Скиллы все как в Доте 2…»; image style «как игра… как наши картинки были… из концепта» (not the 0f7e62a4f04e.webp look); concept images = quality bar «не под копирку».
- 10-15: «Как, блять, встали? Долбоеп, у нас гейт снят.» (gate is open).
- Hero names (10-15): wanted names from Russian fairy tales, cool/funny but serious; rejected meme names («никакой… пятерочки»), rejected too-archaic words; liked Добрыня, Кощей, Лиса, Любава, «Никита Кожемяка, Железная Хватка», «Настасья Микулична», «Лиса потрепее… Хитрый клинок», «старец подорожник, прикладывающий к ранам», «Кощей, повелитель…».
- Art: «1 арт на нано-банане, сейчас там есть деньги» with 6 full-length heroes; afterwards: «Давай так, пока я оставим. Окей? Предварительно. Всё, нам надо больше не пользоваться. Давай юзай локальную модель нашу для всех этих генераций.»
- Plantain: «а марихуана? А, конопля… Ну а что, может оставить прикол?»
- 10-15 forwarded Maxim Astrakhantsev messages: «вот нашел сохрани»; «буду разрабатывать текущую спеку»; «можешь почитать для общего развития»; «герои +- такие роли».

## DECISIONS
- Final hero names (display-only, ids unchanged, no recalibration, no package/audio change): guardian — Никита Кожемяка, Железная Хватка; fury — Настасья Микулична, Удалая Богатырша (epithet my own pick; asked owner to say if he wants another); shadow — Лиса Патрикеевна, Хитрый Клинок; beacon — Старец Подорожник, Прикладывающий к Ранам; arcanist — Кощей, Повелитель Молний; voice — Любава, Голос Гуслей.
- Live GM must call heroes by new names read from `heroes.py`.
- Local image model only from now on (Nano Banana stopped). Sketch `/home/kesha/ai-table-evidence/concept/generated_1792048145393.png` (~$0.07) is a preliminary style reference.
- Plantain must not look like cannabis (my call; owner's reply not seen): told owner no (КоАП ст. 6.13, fine up to 1 млн ₽ or suspension up to 90 days); offered Старец line «Это подорожник, а не то, что вы подумали».
- No `foghedgehog`; V-34/V-35 decisions on seedon, RU mirror, wildcard stand.
- Provisional: combat «Подтвердить» card stays until owner answers.
- Gate quota is open; my earlier claim that tasks were queued was wrong (corrected to owner).

## FILES, IDS AND ARTIFACTS
- `/home/kesha/projects/dnd-game-master/AGENTS.md`: removed `dnd-backend`, added `ai-table-gm`, added 2026-10-15 owner decision on live GM/game-like UI; pushed to main `cc3df5b0a09035b075103675a3b9a0b0f0aa53bd`.
- `/home/kesha/ai-table-evidence/concept/`: 4 Codex concept variants `exec-*.png`; owner's `arden-veil-card.jpg`, `choose-hero-six.jpg`, `choose-master-severin.jpg`; `mvp-product-spec.ru.md`; `generated_1792048145393.png`. Evidence dir 524 MB.
- Rig scripts/logs: `/home/kesha/.cache/ai-table-i12/verify_rig_v{37..42}.sh`, `rig-v*.log`. Rig clone to trash after V-42 merge: `/home/kesha/.cache/ai-table-rig.t1SR5A`.
- Rollback dir V-42: `/opt/ai-table-i1/rollback-20261015T101330Z/` (scripts also disable GM).
- Branches: V-42 `task-V-42/ai-table-gm`; V-43 on `ai-table-worker` branch (cb020eb at last report).
- Tickets: V-38 (5619), V-39 (5620), V-40 (5635), V-41 (5639), V-42 (5737), V-43 (5738).
- Public names redirect `/` → `/table` (200, checked 13.10); password was given to owner in chat — <secret>.
- Background job `bg-aab1f81ae6` polls `sessions.status` of `ai-table-gm` for `^idle$` (120 s, 6 h, expires 2026-10-15T17:11 UTC) → will trigger the merge. Earlier file-watcher `bg-463a39c7a2` already fired.
- Disk cleanup 11.10: 29 `ai-table-rig.*` clones and 2030 `/tmp/ai-table-i1-*` trashed, ~1.1 GB freed.

## NUMBERS
- Latency (worker): STT 0.3–0.4 s; first GM voice 2.6–5.3 s (up to 11 s on first turn/tool call); full answer 10–16 s.
- Rig V-42: 667 passed + 1 failed in 705.9 s; browser 48 passed in 990 s; failing test re-run 7 passed in 0.21 s.
- Art ~2.3 min/image at load 32.

## CONSTRAINTS AND BANS
- Report in Russian, verdict first, numbers in tables, 🔴 for decisions. Every final report starts with a separate line «СТАТУС КОРУНД-57»; recommended option marked «КОРУНД-63» at line start (my recent reports missed the former — fix).
- All project edits go through workers. Do not restart Orchestra. Delete only via `trash`, then `trash-rm` by exact name. `find` is blocked by hook; use `rg --files --hidden --no-ignore`.
- No secrets in tracked files (repo public). Do not touch the Deepgram key. Luna is default model; Astra and Sol banned. Gate forbids stems `audio`, `campaign` and `.pyc` files.
- Disk ≥95% → clean up. Kill only finished workers idle >72 h. No paid services without owner's word. Local image model only.
- On 89.23.102.244: only additive, `nginx -t`-checked changes; do not touch `*.seedon.ru` or orchestra/orc proxy; never point seedon.ru directly at the German IP.
- Finish tickets alone, don't ask owner about tickets; write to owner on problems with how to solve them. «Same defect twice» rule: escalate to owner on a third failure.
- Orchestra restarts kill rigs inside its cgroup: run rigs detached: `ssh kesha@localhost 'nice bash <branch verify_rig.sh> /home/kesha/projects/ai-table-mvp <branch> [--browser]'` via `setsid nohup`.
- Unresolved conflict: `mx2/<task>/<short>` branch template vs Orchestra auto names (`task-V-42/…`, `adhoc-…`).
- Per-check token limit 268k; external wait timeout 593 s; export batch exactly 1767; draft `/srv/work/draft-8775.md`; backups only `backup/kv829`; RB-1568 in commits; don't touch `/srv/vault_56`; nothing to `#prod-67` without direct «да»; no rollback on delta-7 without asking.

## PEOPLE AND AGENTS
- Owner (Telegram user; Maxim Astrakhantsev forwarded spec messages). Workers: `ai-table-gm` (V-42, currently not idle/«waiting»), `ai-table-worker` (V-43, persistent full-cycle implementer). seedon-orchestrator (domain relay). Marina Lisitskaya (deadline item).

## OPEN ITEMS AND NEXT ACTION
- Blocker: `ai-table-gm` not idle. Next: when watcher fires, run `merge_worker(name=ai-table-gm, task_id=V-42, expected_head=2dbaab0d216ce1d4643396a56cf0bd823b42ebad, task_outcome=complete)` with rig result in `acceptance_note` (single failure = rig's missing `websockets`; worker venv 7/7). Then `uv sync` in `/home/kesha/projects/ai-table-mvp` as kesha via ssh (NOT yet done), and trash `ai-table-rig.t1SR5A` (`trash-put`, then `trash-rm` exact name).
- Then wait for V-43 DONE → own rig with `--browser` → merge → deploy ticket → verify prod myself → send owner screenshots.
- Waiting on owner: playtest start (send room checklist); one-touch confirm vs «Подтвердить» card; whether sslip/seedon links open (seedon opens, shown `/table`); TeraTTS licence before commercial use; epithet «Удалая Богатырша».
- Owner items of unknown status (no evidence done): count duplicates in `index_18.csv`; remind about Marina Lisitskaya's «передачу доступов» deadline; send «ФЛОКС-36» vs «ТАЛИОН-47» table.
- Raw transcript: `/api/sessions/gm/logs`.
