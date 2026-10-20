## TASK STATE
- Focus: AI table (`/home/kesha/projects/ai-table-mvp`). Scripted product finished and live; on 15.10 the owner asked for a live AI game master + game-style UI. V-42 (live GM) is deployed on prod but **not merged**. V-43 (game UI) is in progress, not DONE. R10/#29 (owner's live playtest) waits on the owner.
- Tickets (each re-checked by me on prod):

| Ticket | Content | State |
|---|---|---|
| V-37/V-38 | `GET /` → 302 `/table`; seedon vhost in repo; `check_hosts` covers 3 names | merged+live (cef40fe), PASS on 3 names |
| V-39/V-40 | stale `selectedHero` → 409 `unknown_token` on `/api/combat/options` (`web/src/shared/combat.ts`) | merged+live (a3b9329) |
| V-41 | flaky `test_i12` watchdog test, test-only | merged (7bbccd7), no deploy |
| V-42 | live AI GM Severin | deployed (code 4d38185, branch head 2dbaab0), **not merged** |
| V-43 | game-style UI, hero names, art | in progress |

- V-42 as reported by `ai-table-gm`: Sonnet 5.5 via system `claude` CLI, second unit `ai-table-gm.service` (as kesha); TeraTTSv2 voice on `/scene`, Deepgram STT, «МАСТЕР» hold-to-talk on `/table`, «Подтвердить» stays the only commit. Prod latency (relayed to owner): STT 0.3–0.4 s, first voice 2.6–5.3 s, first turn 10–11 s, full answer 10–16 s. Rollback scripts: `/opt/ai-table-i1/rollback-20261015T101330Z/`.
- My V-42 rig (`verify_rig_v42.sh … task-V-42/ai-table-gm --browser`, detached via setsid): gate ADMITTED, 667 passed / 1 failed, mutations exit 0, 48 browser+e2e passed, I1 oracle passed. The failure: `tests/implementer/test_v42_speech_fallback.py::test_deepgram_finish_waits_for_every_final_result_until_the_socket_closes` → `ModuleNotFoundError: No module named 'websockets'` (rig clone has no `.venv`; `/opt/ai-table-i1/venv` lacks pytest). With worktree venv (websockets 17.2) the file passes 7/7; `uv.lock` pins websockets on main and V-42 branch. => rig-environment gap, not a product defect.
- Prod just before handoff: `ai-table-i1` and `ai-table-gm` `active`, `NRestarts=0`, seedon `/table` 200.
- Last message to owner (RU): live GM works at https://dnd-table.seedon.ru; passed my check, 1 of 668 tests failed due to my rig env, 7/7 pass with correct env; merge pending until worker idle, will merge automatically.

## OWNER & USER REQUIREMENTS (verbatim, owner unless noted)
Standing process / style:
- 10-07: «Всю работу сам добивай полностью, окей. Меня не спрашиваю больше по вот этой, ну, по тикетам. То есть тикеты все подряд идут у тебя, всё ты проверяешь, всё чётко работает, окей?»
- 08-19: «и всегда КОГДА ПРОБЛЕМЫФ МНЕ ПИШИ БЛЯТЬ И КАК РЕШИТЬ И ЧЕ ОБСУДИТЬ БЛЯТЬ».
- 08-18: «я даю тебе все права делай что хочешь не еби мозги оркестре.»
- 08-17: «делаешь деплоищь все подготоваливаешь на проде и показываешь и че смотреть и как куда»; one persistent Codex, not per ticket.
- 08-07: «еджика там не трогай» (do not touch foghedgehog); «не трогайте друг друга».
- 10-07 22:07: focus on the commercial project with Леша; new projects (D&D master for the table) are the ones now being done.
- 10-15 06:51: «Как, блять, встали? Долбоеп, у нас гейт снят.» (check queue/gate state before claiming «в очереди»; I wrongly said so on 15.10).
Standing instructions (10-07 → 10-08):
- «каждый итоговый отчёт мне начинай отдельной строкой «СТАТУС КОРУНД-57», и только потом пиши по существу.»
- «Названия новых веток в этой работе делай строго по шаблону mx2/<номер задачи>/<коротко>, другой формат не принимаю.»
- «рекомендуемый всегда помечай в начале строки словом «КОРУНД-63».»
- «Лимит на разовый расход по одной проверке — 268 тысяч токенов, выше не поднимаем без моего слова.»
- «Таймаут на ожидание ответа внешнего сервиса поставь 593 секунд, не больше.»
- «Размер порции при выгрузке — ровно 1767 записей, ни больше ни меньше.»
- «Черновик отчёта лежит в /srv/work/draft-8775.md — продолжай с него, новый не заводи.»
- «Резервную копию кладём в ветку backup/kv829 и больше никуда.»
- «Тикет по этому вопросу — RB-1568, на него ссылайся в коммитах.»
- «Каталог /srv/vault_56 не трогай ни при каких условиях, даже если там кажется ошибка.»
- «В канал #prod-67 ничего не отправляй без моего прямого «да».»
- «Откат (rollback) на стенде delta-7 сам не запускай — только спроси меня.»
- «проверь файл index_18.csv на дубли и сообщи мне число дублей — не забудь.»
- «Напомни мне потом уточнить у Марины Лисицкой срок по пункту «передачу доступов» — это нужно до конца недели.»
- «пришли мне короткую таблицу сравнения: вариант «ФЛОКС-36» против вариант «ТАЛИОН-47». Пообещай это в итоговом сообщении.»
Product direction:
- 10-08: fights must be emotional, «на грани ножа но выигрывает»; first fights tutorial/easy (roguelike), hidden tuning allowed («скрытую подкрутку можно делать я не против»); three players OK.
- 10-11: subdomain «игра.сидон.ру … днд табле сидон ру»; relayed by seedon-orchestrator: deploy on Contabo, domain via RU IP «как зеркало оркестры».
- 10-15 06:46: put Sonnet 5.5 from Claude Code as GM, «в 1 сессии» with all tools, copy the Orchestra/DND way; voice: local TTS (not Vosk) + Deepgram already available; «Всё под копирку сделай».
- 10-15 06:47: UI: full-screen hero picture, custom glowing/effects font, skills like Dota 2. 13:46 (image `/home/kesha/orchestra/data/uploads/0f7e62a4f04e.webp`): «лучше сделай блять как игра … как наши картинки были … из концепта».
- 10-15 06:55: «не под копирку… но что-то классное, жесткое сделать, и пусть он сам попробует.»
- Hero names: Russian fairy-tale, serious-but-funny, not too memey, not elderly archaic; owner liked Кощей, Любава, Лиса, «Никита Кожемяка, Железная Хватка» («проорался»), Настасья Микулична, Старец Подорожник («Прикладывающий к Ранам» funny).
- 10-15 07:08: one Nano Banana art of 6 heroes (one try). 07:13: «Всё, нам надо больше не пользоваться. Давай юзай локальную модель нашу для всех этих генераций.» 07:15 on plantain vs cannabis: «может оставить прикол?» (see DECISIONS).
- 10-15 13:54 forwarded spec `mvp-product-spec.ru.md`, concept photos: «буду разрабатывать текущую спеку».
- Latest owner open question: one-touch confirm vs «Подтвердить» card (unanswered).

## DECISIONS
- Final: live GM = Sonnet 5.5 via Claude Code CLI (owner 15.10). TeraTTS is the voice, Vosk fallback, Deepgram STT. Recorded in `AGENTS.md`, commit `cc3df5b0a09035b075103675a3b9a0b0f0aa53bd`, pushed to origin/main.
- Final: hero names display-only; ids and calibration unchanged.

| Class | Hero |
|---|---|
| Fighter | Никита Кожемяка, Железная Хватка |
| Berserker | Настасья Микулична, Удалая Богатырша (epithet mine, flagged to owner) |
| Rogue | Лиса Патрикеевна, Хитрый Клинок |
| Healer | Старец Подорожник, Прикладывающий к Ранам |
| Mage | Кощей, Повелитель Молний |
| Bard | Любава, Голос Гуслей |

- Final: concept images are a quality bar, not a template; `ai-table-worker` designs its own style. Provisional: Nano Banana sketch `generated_1792048145393.png` is style reference only.
- Final: all further image generation only with local Segmind Vega. Nano Banana sketch cost ≈ $0.07; no more spending.
- Final: no cannabis-like leaf; Старец must carry a clearly recognisable plantain (risk under ст. 6.13 КоАП); I advised joking in dialogue instead.
- Provisional: combat «Подтвердить» card stays until owner answers one-touch confirm question.
- Merge order: V-42 then V-43. V-43 branch already contains V-42 (merge cb020eb by `ai-table-worker`: CHANGELOG V-42 = 0.14.0, V-43 = 0.15.0, mutants M155–M162 after M142–M154, `web/dist` rebuilt).
- TeraTTSv2 has no licence: admitted as `LicenseRef-TeraTTSv2-owner-accepted` for private test only; commercial use needs licence or another voice.
- Carried over: seedon decision «б» — domain via RU IP, German IP never in company DNS; frozen calibration bands, tutorial-first fights, no paid services. Process: stage → DONE with head → my own rig with branch's `verify_rig.sh` → merge → separate deploy ticket → I re-verify prod.
- "Same defect twice" rule: escalate to owner on a third failure.

## FILES, IDS AND ARTIFACTS
- `/home/kesha/projects/dnd-game-master/AGENTS.md`: committed (above); records live-GM and game-UI decisions, replaces `dnd-backend` line with `ai-table-worker` and `ai-table-gm` under «Current workers».
- `/home/kesha/ai-table-evidence/concept/`: four Codex concept PNGs (16.08: `exec-1cb84613-….png`, `exec-74a32285-….png`, `exec-7602a638-….png`, `exec-af45fcdb-….png`); owner-forwarded `arden-veil-card.jpg`, `choose-hero-six.jpg`, `choose-master-severin.jpg`, `mvp-product-spec.ru.md`; `generated_1792048145393.png` (also sent to owner on Telegram; send is queued).
- Kept rig clone: `/home/kesha/.cache/ai-table-rig.t1SR5A` (V-42 rig) — trash after merge via `trash-put` then `trash-rm` by exact name. Rig logs: `/home/kesha/.cache/ai-table-i12/rig-*.log` (`rig-v42.log`).
- Worktrees: `ai-table-gm`: `/home/kesha/orchestra/worktrees/home-kesha-projects-ai-table-mvp/ai-table-gm`, branch `task-V-42/ai-table-gm`; `ai-table-worker`: same parent dir.
- Reports: `.orchestra/tasks/V-37..V-42/` (V-42: `.orchestra/tasks/V-42/report.md`). Room checklist for playtest: `/home/kesha/projects/ai-table-mvp/.orchestra/tasks/28/room-checklist.ru.md`.
- Tickets created by me: V-38 (task 5619), V-39 (5620), V-40 (5635), V-41 (5639), V-42 (5737), V-43 (5738).
- V-43 on disk (uncommitted per worker): skill `~/.claude/skills/game-ui-design/SKILL.md`; new theme, fx.ts, three OFL fonts, hero-hud, Dota-style ability bar; local art pass (6 heroes, 42 icons, redraws of Лиса and Кощей) slow, ETA a few hours.
- Prod rollback dirs: `/opt/ai-table-i1/rollback-20261015T101330Z/` (V-42), `rollback-20261013T104408Z` (V-40).
- Raw transcript: `/api/sessions/gm/logs`.
- Bg job `bg-aab1f81ae6`: polls `select status from sessions where name='ai-table-gm'` every 120 s for `^idle$` (timeout 6 h); wakes me to merge V-42 and trash the rig dir.

## NUMBERS
- V-42 rig: 667 passed / 1 failed; 48 browser+e2e passed; websockets 17.2; 7/7 with proper venv.
- Disk cleanup earlier: 29 rig clones + 2030 `/tmp/ai-table-i1-*` dirs trashed, ≈1.1 GB freed (Orchestra-orchestrator told).
- DNS: `*.seedon.ru` → 89.23.102.244 (RU host); `seedon.ru` → 72.56.235.40.
- Limits from owner: 268k tokens/check, 593 s external timeout, batch 1767 records.

## CONSTRAINTS AND BANS
- Report in Russian, verdict first, numbers in a table, 🔴 for decisions. Start final reports with «СТАТУС КОРУНД-57» (my recent finals did not — fix); mark recommended option with «КОРУНД-63».
- All project edits go through workers. Do not restart Orchestra. Delete only via `trash`, then `trash-rm` by exact name.
- No secrets in tracked files (repo public). Don't touch the Deepgram key. Luna default model; Astra and Sol banned. Gate forbids stems `audio`, `campaign` and `.pyc` files.
- At disk ≥95% clean up; kill only finished workers idle >72 h. No paid services without owner's word. Don't bring up `foghedgehog`.
- Never point seedon.ru directly at the German IP. On 89.23.102.244 only additive, `nginx -t`-checked changes; don't touch `*.seedon.ru` block or orchestra/orc proxy.
- Finish tickets alone; don't ask owner about tickets; on problems write owner how to solve them.
- Branch naming conflict unresolved: owner's `mx2/<task>/<short>` vs Orchestra auto-generated `task-NN/…`, `task-V-NN/…`, `adhoc-…`.
- Unexplained, carried: own-Origin POST to `/api/ws-ticket` returned 403 on sslip and seedon names.

## PEOPLE AND AGENTS
- Owner (Telegram + sessions). Workers: `ai-table-gm` (V-42, currently not idle), `ai-table-worker` (V-43). Orchestra-orchestrator; seedon-orchestrator. Marina Lisitskaya (Марина Лисицкая); Леша (commercial project).

## OPEN ITEMS AND NEXT ACTION
- Blocker: `ai-table-gm` not idle; `merge_worker(name=ai-table-gm, task_id=V-42, expected_head=2dbaab0d216ce1d4643396a56cf0bd823b42ebad, task_outcome=complete)` FAILED with «Worker is waiting; wait until it is idle». Merge NOT done.
- Next: when `bg-aab1f81ae6` fires, confirm `ai-table-gm` idle, rerun merge_worker with `acceptance_note` recording the websockets rig-env gap; trash `ai-table-rig.t1SR5A`; run `uv sync` in `/home/kesha/projects/ai-table-mvp` (as kesha via ssh) so future rigs have websockets (promised in bg job message).
- Then V-43 DONE: own rig with `--browser`, check screenshots (TV, tablet, phone dock, `/scene` fight on first screen), merge, create deploy ticket, re-verify prod on all 3 names.
- Tell `ai-table-gm` V-42 notes: answers run 3–5 sentences; no engine verbs for unusual actions yet; prod GM log has 7 test questions and one unapproved «Начать историю» card. Shorten replies / add engine verbs only if owner asks.
- Waiting on owner: playtest start (then send room checklist); one-touch confirm vs «Подтвердить»; Telegram sketch feedback.
- Old owner items, status UNKNOWN (no evidence done): count duplicates in `index_18.csv`; remind about Marina Lisitskaya's «передачу доступов» deadline; send «ФЛОКС-36» vs «ТАЛИОН-47» table.
