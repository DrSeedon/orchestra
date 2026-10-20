**TASK STATE**
- Focus: AI table (`/home/kesha/projects/ai-table-mvp`). Current: live AI game master V-42 (done, on prod, merge pending) and game-style UI V-43 (not done). R10/#29 (owner's live playtest) waits on the owner.
- Merged+live earlier, re-checked on prod: V-37/V-38 (bare `/` → 302 `/table` on all 3 names; seedon vhost in repo; cef40fe), V-39/V-40 (stale `selectedHero` fix, 409 `unknown_token`; a3b9329), V-41 (flaky `test_i12` watchdog test).
- **V-42 (worker `ai-table-gm`)**: DONE, already deployed. Live code `4d38185`; branch `task-V-42/ai-table-gm`, head `2dbaab0d216ce1d4643396a56cf0bd823b42ebad`. Severin Кроу = Sonnet 5.5 via system Claude CLI, second unit `ai-table-gm.service`; voice TeraTTSv2, STT Deepgram (Vosk fallback); hold-to-talk «МАСТЕР» on `/table`. Prod check by me: `ai-table-i1` and `ai-table-gm` active, NRestarts 0, `/table` 200.
  - My rig (`verify_rig_v42.sh --browser`): gate ADMITTED, 667 passed / 1 failed, mutations_exit 0, 48 browser/e2e passed, I1 oracle passed. The single failure `tests/implementer/test_v42_speech_fallback.py::test_deepgram_finish_waits_for_every_final_result_until_the_socket_closes` = `ModuleNotFoundError: websockets` (`server/ai_table/adapters/stt.py:218`): rig-environment gap, not a product defect. With worker's synced venv 7/7 pass. Main `.venv` not synced to `uv.lock` (lock pins websockets 17.2; lock/pyproject identical main vs V-42). Whether websockets is a direct dep in `pyproject.toml`: UNKNOWN.
  - **Merge not done**: `merge_worker(name=ai-table-gm, task_id=V-42, expected_head=2dbaab0d216ce1d4643396a56cf0bd823b42ebad, task_outcome=complete, acceptance_note=…)` refused (op 18fff443-d10d-4789-bc4d-8ad6d05d45a8): "Worker is waiting; wait until it is idle". Background poll `bg-aab1f81ae6` (sqlite check of `ai-table-gm` session status, pattern `^idle$`, every 120 s, expires 2026-10-15T17:11Z) will notify when idle.
- **V-43 (game UI, worker `ai-table-worker`)**: NOT DONE. On disk: skill `~/.claude/skills/game-ui-design/SKILL.md`, display names/epithets, 3 OFL Cyrillic fonts, hero HUD with large art, Dota-style ability bar, fx layer, «Мастер» button. Branch already contains V-42 (merge commit `cb020eb`) → V-42 must be merged first. Still generating on local Segmind Vega (CPU, ~2.3 min/image): icons + redraws of Лиса (first draft had low-cut corset) and Кощей (skeleton monster); ETA hours. Open: phone dock covers half the screen; `/scene` on TV doesn't show the fight on first screen. After: mutants and `--browser` rig.
- Prod before V-42: `fe880b2` → `cef40fe` → `a3b9329`; counters 63|63|63|2, story_runs 0, package r3 `529f6861` unchanged. V-42 rollback dir `/opt/ai-table-i1/rollback-20261015T101330Z/`.
- Worker-reported GM latency: speech→text 0.3–0.4 s; first GM voice 2.6–5.3 s typical (10–11 s first turn/tool call); full answer 10–16 s.
- Last message to owner (RU): live GM passed my check, prod intact, 1 of 668 tests failed due to my test env (7/7 after fix); will merge automatically when worker is free. list_agents: ai-table-worker and ai-table-gm both "waiting"; project tasks: #5 in_progress, #29 (R10 playtest) new, #34 (rewrite security-probe on real ASGI path) new.

**OWNER & USER REQUIREMENTS (verbatim, owner unless noted)**
- 08-19: «и всегда КОГДА ПРОБЛЕМЫФ МНЕ ПИШИ БЛЯТЬ И КАК РЕШИТЬ И ЧЕ ОБСУДИТЬ БЛЯТЬ».
- 08-18: «…я даю тебе все права делай что хочешь не еби мозги оркестре.» 08-07: «блять сука еджика там не трогай»; «не трогайте и все друг друга». 08-17: «одного и тогоже кодекса надо постоянного ане на каждый тикет…»; «пока забей на гит локально делай все».
- 10-07 21:53: «Всю работу сам добивай полностью, окей. Меня не спрашиваю больше по вот этой, ну, по тикетам. То есть тикеты все подряд идут у тебя, всё ты проверяешь, всё чётко работает, окей?» 10-07 22:07: focus only on the commercial project with Леша; new projects (ДНД мастер для стола) are separate. 10-08 04:58: «Добивай 7-ой тикет полностью… полностью без меня».
- 10-08 07:49 / 15:56: fights must be emotional («на грани ножа но выигрывает»); first fights tutorial/easy so newbies don't lose; hidden calibration tweak allowed («нет скрытую подкрутку можно делать я не против»).
- 10-11 16:19: «сделай поддомен игра.сидон.ру типо днд табле сидон ру ок»; relayed 17:13: «да только Б. типо на контабо будет развернут а домен через ру айпи. как зеркало оркестры также».
- 10-15 06:46 (live GM): Sonnet 5.5 from Claude Code, one long session with all tools (not a session per request); voice via the local TTS (not Vosk) + Deepgram; «Опус нового создай, чтобы он всё изучил это и всё внедрил»; owner called the scripted table «бред».
- 10-15 06:47 (UI): «картинка персонажа на весь экран, шрифт… кастомный… со светяшками, с аффектами… Скиллы все как в Доте 2». 06:55: concepts are only a quality bar, not a copy.
- 10-15 07:13: «Давай так, пока я оставим. Окей? Предварительно. Всё, нам надо больше не пользоваться. Давай юзай локальную модель нашу для всех этих генераций.» (Nano Banana sketch kept as preliminary; no more Nano Banana.)
- Names: owner wanted serious yet fun Russian-fairy-tale names, no archaic words, no modern/«пятерочка» jokes (06:59, 07:01, 07:02); 07:07 picked final set (see DECISIONS).
- 10-15 07:15 on plantain/cannabis: joke alternative — «может оставить прикол?» (see DECISIONS for how handled).
- Standing instructions carried from earlier summary (10-07/10-08; not seen as raw owner rows in this journal, treat as active): start each final report with separate line «СТАТУС КОРУНД-57»; mark recommended option at line start with «КОРУНД-63»; per-check limit 268 тыс. токенов; external-service timeout 593 s; export batch exactly 1767 records; continue draft `/srv/work/draft-8775.md`; backups only to branch `backup/kv829`; new branches strictly `mx2/<номер задачи>/<коротко>`; reference RB-1568 in commits; never touch `/srv/vault_56`; send nothing to `#prod-67` without direct «да»; never run rollback on stand delta-7 without asking.
- Owner promises pending (earlier): check `index_18.csv` for duplicates and report count; remind about Марина Лисицкая deadline («передачу доступов», end of week); table «ФЛОКС-36» vs «ТАЛИОН-47» in final message. No evidence these were done.

**DECISIONS**
- Live GM decision recorded in `/home/kesha/projects/dnd-game-master/AGENTS.md`, commit `cc3df5b0a09035b075103675a3b9a0b0f0aa53bd`, pushed; same commit removed `dnd-backend` from "Current workers".
- UI must look like a game; class colours: fighter gold, barbarian fire, rogue violet, cleric white-gold, wizard blue, bard emerald.
- Hero names (display-only, ids unchanged, no recalibration): Fighter — Никита Кожемяка, Железная Хватка; Berserker — Настасья Микулична, Удалая Богатырша; Rogue — Лиса Патрикеевна, Хитрый Клинок; Cleric — Старец Подорожник, Прикладывающий к Ранам; Wizard — Кощей, Повелитель Молний; Bard — Любава, Голос Гуслей. «Удалая Богатырша» is my own epithet; change offered, no answer.
- Nano Banana sketch `/home/kesha/ai-table-evidence/concept/generated_1792048145393.png` (~$0.07, one attempt) kept as preliminary style reference; all further images on local Segmind Vega only.
- No cannabis-like leaf: Старец's plantain must clearly be plantain (RU КоАП 6.13 risk); owner's joke alternative: Старец mutters it in a line.
- Provisional: combat «Подтвердить» card stays until owner answers on one-touch confirm. TeraTTSv2 has no declared licence: admitted as `LicenseRef-TeraTTSv2-owner-accepted`, speech only, private test; commercial use needs licence/another voice.
- Carried: seedon variant «б» (service on Contabo, domain via RU IP); frozen calibration bands; tutorial-first fights; acceptance process: stage → DONE with head → my own rig with branch's `verify_rig.sh` → merge with `expected_head` → separate deploy ticket → I re-verify prod.

**FILES, IDS AND ARTIFACTS**
- `/home/kesha/ai-table-evidence/concept/` (not in repo): four Codex concept PNGs `exec-*.png` (Арден Вейл), `arden-veil-card.jpg`, `choose-hero-six.jpg`, `choose-master-severin.jpg`, `mvp-product-spec.ru.md`, `generated_1792048145393.png`.
- Rig: `/home/kesha/.cache/ai-table-i12/verify_rig_v42.sh`, `rig-v42.log`; rig clone `/home/kesha/.cache/ai-table-rig.t1SR5A` (to trash). Run detached: `ssh kesha@localhost 'setsid nohup nice bash …/verify_rig_v42.sh /home/kesha/projects/ai-table-mvp task-V-42/ai-table-gm --browser'` (earlier runs were killed by Orchestra restarts).
- Tickets: V-38 (5619), V-39 (5620), V-40 (5635), V-41 (5639), V-42 (5737), V-43 (5738). Worktrees: `/home/kesha/orchestra/worktrees/home-kesha-projects-ai-table-mvp/`. Prod venvs: `/opt/ai-table-i1/venv-beaa3cb` (websockets 17.2), `/opt/ai-table-i1/venv` (no pytest).
- Repo bits: `ops/nginx/dnd-table-mirror`, `ops/check_hosts.py`, `tests/implementer/test_v37_root.py`, `.orchestra/tasks/V-31..V-41/`, `ops/RUNBOOK.ru.md`; playtest checklist `.orchestra/tasks/28/room-checklist.ru.md`.
- Hosts: `dnd-table.seedon.ru`, `table-158-220-127-161.sslip.io`, `dnd-table.duckdns.org` (all bare `/` → 302 `/table` → 200). Owner-forwarded image `/home/kesha/orchestra/data/uploads/0f7e62a4f04e.webp` (owner: use game-like concept style instead).
- Raw transcript: `/api/sessions/gm/logs`.

**NUMBERS**
- V-42 rig: 667 pass/1 fail/668; browser+e2e 48; fix rerun 7/7; websockets 17.2. V-37 rig 43/44 (i11 flake, fixed V-39); V-41 30/30 under load. Image gen ~2.3 min/image. Disk cleanup 11.10: 29 rig clones (775 MB) + 2030 `/tmp/ai-table-i1-*` (294 MB) ≈ 1.1 GB.

**CONSTRAINTS AND BANS**
- Report in Russian, verdict first, numbers in table, 🔴 for decisions. All project edits go through workers. Do not restart Orchestra. Delete only via `trash`, then `trash-rm` by exact name. No secrets in tracked files (repo public; room passphrases out of evidence). Do not touch the Deepgram key. Model-review frozen. Luna default model; Astra and Sol banned. Gate forbids stems `audio`, `campaign` and `.pyc`. Disk ≥95% → clean up. Kill only finished workers idle >72 h. No paid services without owner's word. Do not bring up `foghedgehog`. Finish tickets alone, don't ask owner about tickets; on problems write owner with a solution. Escalate on third failure of same defect.
- RU host 89.23.102.244: only additive, `nginx -t`-checked changes; never touch `*.seedon.ru` block or orchestra/orc proxy; never point seedon.ru directly at the German IP.
- Check claims against facts before sending (10-15 I wrongly said tasks were queued behind a quota gate). Unresolved conflict: `mx2/<task>/<short>` rule vs Orchestra auto `task-NN/…` and `adhoc-…` branches. My recent final reports (incl. 10-15) lacked «СТАТУС КОРУНД-57» — fix going forward.

**PEOPLE AND AGENTS**
- Workers: `ai-table-gm` (Opus, persistent, V-42), `ai-table-worker` (V-43), `seedon-orchestrator` (relays seedon), Orchestra-orchestrator (asked disk cleanup at 95%), `Claude-Code-Game-Master-orchestrator` (bg target).

**OPEN ITEMS AND NEXT ACTION**
1. When `bg-aab1f81ae6` fires (ai-table-gm idle): `merge_worker(ai-table-gm, V-42, expected_head=2dbaab0d216ce1d4643396a56cf0bd823b42ebad, complete)` with the same acceptance note (new operation).
2. Then trash `/home/kesha/.cache/ai-table-rig.t1SR5A`; run `uv sync` in `/home/kesha/projects/ai-table-mvp` as kesha via ssh; tell `ai-table-worker` V-43 now sits on merged V-42 and must rebuild `web/dist`.
3. Wait for V-43 DONE → own `--browser` rig, read report, merge, deploy ticket, deploy, re-verify prod, send owner screenshots (promised).
4. Watch: GM answers 3–5 sentences (too long); no engine verbs for unusual actions (TODO); prod GM log holds worker's 7 test questions and one unapproved «Начать историю» card; Claude quota shared with Orchestra (GM silent if exhausted); TeraTTS licence.
5. Waiting on owner: did the seedon link work; playtest start (then send room checklist); one-touch confirm vs «Подтвердить»; berserker epithet.
6. UNKNOWN: whether `hero_names` rename and stored-fight projection fix are merged (worker reported them on disk, uncommitted).
