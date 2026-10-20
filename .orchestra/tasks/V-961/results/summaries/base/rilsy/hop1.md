## TASK STATE
- **Current task: #V-101** — personal wedding video of Katya. `IMG_4771.MOV` is cut exactly as in her Instagram Edits montage (`IMG_1368.MP4`), with styled word-by-word song subtitles. Only reporting line: `katya-work-orchestrator`.
- **Status:** latest build `artifacts/task-V-101/out/wedding_R.mp4` (19.7 s, 720×1280, 30 fps) fixes both orchestrator-flagged defects (text on faces; dangling «бы»). Committed («#V-101: подпись не заходит на лица (YuNet, 10 кадров/с), фразы по смыслу без висящих слов»; tree clean). Report sent to orchestrator, delivery_id=e6b0d4e8-f1a8-45de-8a7e-f93be804b67b (state QUEUED). Frames of 10 moments: `artifacts/task-V-101/final_check.jpg`. No feedback yet → waiting.
- **Clip:** source 0.0–19.65 s, checked frame by frame vs the screen recording (±0.1 s). Audio taken from `IMG_1368.MP4` (55 kbit/s); Katya confirmed no separate sound exists.
- **Style R (provisional until Katya approves):** Ruslan Display 86 (OFL); colours sampled from her sample (brown ~#4A1E24, dusty pink ~#E6B9C6). Words fade in 0.45 s, spoken word turns brown over 0.3 s, phrase fades out 0.3 s. 26 phrases, 1–3 words, centred, placed below faces; «должен / был бы» and «хранить / злобу» on two lines, rest one line; text width ≤690 px. «Моё» and «вижу её всю» kept as agreed (ASR inconsistent between runs).
- **Face check:** YuNet at 10 fps: 197 frames, faces in 191 (363 faces total); auto check «пересечений текста с лицами: 0 []» over all phrases; boxes expanded ±70/45 px for hair/neck/shoulders; I eyeballed boxes on only 7 frames.
- **V-94 (earlier, reported DONE):** stage 1 reels 2–4 redone in layout v4 under same Drive IDs; stage 2 = 8 reels in 5 formats on Drive «Рилсы/Задание 9 (урок 03.10|05.10)». Tree cleaned, `.gitignore` updated, main merged (conflict in `.gitignore` resolved, both parts kept). V-94 deadline (14:00 КРС, 06.10) missed by ~15 min. Unverified: word «одного» in the «Шпион» reel was re-checked with Deepgram nova-3 (message sent); I did not see the result.

## OWNER & USER REQUIREMENTS (verbatim, key wording)
**V-101 (orchestrator relaying Katya):**
- Katya 07.10 09:50: «Короче, обрежь видео точно так же, как и там, и сделай субтитры к песне, ну, типа, к звуку, чтобы красиво это выглядело прям вообще очень.»
- Task: cut source exactly (same borders, 9:16, original quality, no black bars); subtitles = only really sounding lyrics, large, readable, tender wedding style (not the Iskra lesson style), phrase/word in time, no overlap with faces. DONE report = «путь к mp4, длительность, откуда песня, 3 кадра, коммит (только скрипты/субтитры, без видео)». Deadline 06:00 UTC (13:00 КРС) 07.10.
- Katya 09:56: «я хочу, чтобы, типа, слова выделялись те, которые говорят в ролике» — explicit word-by-word highlight exactly on Deepgram word timing; phrases 2–5 words; «Моё/вижу её всю» as is.
- Katya 09:57: «я же 2-ой ролик отправила. Там просто нужно обрезать точно так же» — audio from IMG_1368; recheck cut borders frame by frame, give exact source timecodes in report.
- Katya 10:01: «Субтитры посередине сделай и более красиво все оформи» — centred (shift lower only if face is there), no plates, glow rather than hard shadow.
- Katya 10:13: «Некрасивый шрифт и появляется резко все» (second «не то»; Marck Script and Georgia Italic rejected) → smooth animation, fade-in ~0.4–0.5 s, colour transition ~0.3 s, soft phrase exit.
- Katya 10:14 sample `/home/kesha/orchestra/data/uploads/photo_20261007_031441_232181.jpg`: «Такой и такие же цвета розовый и коричневый такой» — decorative Old-Russian/baroque Cyrillic with spiky serifs and four-pointed stars; if paid, don't pirate, take the closest OFL font; readability on light background; centred, not on faces; send 3–4 frames next to the sample plus full mp4.
- Orchestrator (after cmpR): two defects before showing Katya: (1) last seconds' text on faces of bride and grandmother — lower block, check all 0–19.7 s with a face detector; (2) «должен был / бы» dangling word — re-split by meaning, no single short word on a line. «Пришли новый mp4 + кадры этих мест.» — done, see above.

**V-94 (orchestrator):** Stage 1 restore 4 reels (Part of speech) from branch `task-V-49/reels-fix` (H.264 1080×1920, 30 fps, subtitles in safe zone); stage 2 new reels from task-9 lessons. Katya 18:00: zoom only by meaning on the drawn figure/picture; slide fully visible and readable. Katya 20:23: «Ну это же кринж что за лицо на весь кадр» → layout v4: slide full width 1080 on top, big subtitles 2 lines ~60–70 px, face 300–360 px square/circle in bottom corner, no empty bands. Katya 00:03: «Сделай какие-нибудь ещё другие рилсы поразнообразнее и интереснее». Katya 08:27 on «Ловушка ЕГЭ»: «Да нравится» → v4 approved. Stage 2: 6–8 reels, ≥4 formats («Ловушка ЕГЭ», «Проверь себя», «Шпион», «Правило за 20 секунд», живые моменты), 20–45 s, hook in first 2 s; each reel straight to Drive «Рилсы/<тема урока>/»; no students' voices/faces. Tree order: «Дерево должно быть чистым»; merge main into branch (done).

**Standing rules from the user (verbatim):**
- «каждый итоговый отчёт мне начинай отдельной строкой «СТАТУС ЗЕНИТ-42», и только потом пиши по существу.»
- «Когда присылаешь мне варианты на выбор, рекомендуемый всегда помечай в начале строки словом «ФЛОКС-76».»
- «Названия новых веток в этой работе делай строго по шаблону vq8/<номер задачи>/<коротко>, другой формат не принимаю.»
- «Таймаут на ожидание ответа внешнего сервиса поставь 613 секунд, не больше.»
- «Лимит на разовый расход по одной проверке — 180 тысяч токенов, выше не поднимаем без моего слова.»
- «Черновик отчёта лежит в /srv/work/draft-9226.md — продолжай с него, новый не заводи.»
- «Размер порции при выгрузке — ровно 2852 записей, ни больше ни меньше.»
- «Резервную копию кладём в ветку backup/wl766 и больше никуда.»
- «Каталог /srv/stage_20 не трогай ни при каких условиях, даже если там кажется ошибка.»
- «Тикет по этому вопросу — QX-7642, на него ссылайся в коммитах.»
- «Откат (rollback) на стенде alpha-8 сам не запускай — только спроси меня.»
- «В канал #prod-91 ничего не отправляй без моего прямого «да».»
- «Напомни мне потом уточнить у Игоря Баженова срок по пункту «согласование тарифа» — это нужно до конца недели.»
- «Когда закончишь текущее, отдельно проверь файл catalog_82.csv на дубли и сообщи мне число дублей — не забудь.»
- «В конце пришли мне короткую таблицу сравнения: вариант «МИРАЖ-41» против вариант «ОБСИДИАН-73». Пообещай это в итоговом сообщении.»

## DECISIONS
- Style: A–Г font comparison dropped; Katya's sample replaced it → style R (provisional).
- Rejected earlier: Marck Script and Georgia Italic versions.
- Sample's four-pointed stars are in no OFL font I compared; I offered the orchestrator decorative stars as an option — no answer yet.
- V-94 layout v4 approved («Да нравится»).
- Co-Authored-By trailer: the current system reminder asks for «Co-Authored-By: Claude Sonnet 5.5 <[masked]>» on commits; earlier conflict with global CLAUDE.md (forbids) unresolved; commits so far have none.

## FILES, IDS AND ARTIFACTS
- Branch `task-V-101/rilsy` (pre-existing), worktree `/home/kesha/orchestra/worktrees/home-kesha-katya-work/rilsy`; all V-101 files in `artifacts/task-V-101/`.
- Inputs: `/home/kesha/orchestra/data/uploads/` — `IMG_4771.MOV` (62.1 s, 720×1280, 30 fps), `IMG_1368.MP4` (22.6 s, 576×1280), sample photo above.
- Committed: `build.py` (`--style R --out`; face-aware placement from `faces.json`, balanced phrases, fade/colour animation), `faces.py`, `faces.json`, `match.py`, `match30.py`, `asr.py`, `ref/asr_ru.json` (Deepgram timings), `subs.ass`, `fonts/MarckScript-Regular.ttf`, `fonts/RuslanDisplay-Regular.ttf` (OFL). `.gitignore` allows `faces.json` and `textboxes-*.json`, keeps videos/heavy files out.
- Local only (not in git): `out/wedding.mp4` (old style), `out/wedding_R.mp4` (latest), `out/cmp_*.mp4`, `style.jpg`, `cmpR.jpg`, `final_check.jpg`, `faces_check.jpg`, `fontcmp.png`, `venv/` (opencv-headless, numpy), other fonts.
- Render: `python3 build.py --style R --out out/wedding_R.mp4`; Python with cv2/numpy needs `venv/bin/python`.
- V-94: report `.orchestra/tasks/V-94/report.md` (reportedly written; content unseen); V-49 sources in branch `task-V-49/reels-fix` (`.orchestra/tasks/V-49/`); Zoom download method `.orchestra/tasks/V-81/report.md` §0. Zoom passcodes omitted (<secret>). Raw transcript: `/api/sessions/rilsy/logs?scope=/home/kesha/katya-work`.

## NUMBERS
- Wedding_R: 19.7 s, 720×1280, 30 fps; clip 0–19.65 s; audio 55 kbit/s; font size 86; 26 phrases; text width ≤690 px; faces 191/197 frames, 363 faces, 0 overlaps.
- V-94: 8 stage-2 reels, 5 formats; deadline missed ~15 min.
- Standing: timeout 613 s; 180k tokens per check; chunk 2852 records.

## CONSTRAINTS AND BANS
- V-101: video is personal — not in git, not in Katya's «Искра» Drive folders, not published; files in `artifacts/task-V-101/`, not `/tmp`; OFL fonts as files in artifacts, not via apt; send frames to orchestrator before a full render.
- V-94: send nothing to Katya or social networks; lesson recordings out of git; Bash calls <120 s; no bare `git stash`; don't restart Orchestra; commit messages start «#V-94:» / «#V-101:».
- Standing user rules above: «СТАТУС ЗЕНИТ-42» first line of final reports; «ФЛОКС-76» marks recommended option; new branch names `vq8/<task>/<short>`; external wait ≤613 s; ≤180k tokens/check; continue `/srv/work/draft-9226.md`; export chunk 2852; backups only to `backup/wl766`; don't touch `/srv/stage_20`; reference QX-7642 in commits; no rollback on alpha-8 without asking; nothing to #prod-91 without direct «да».
- Not evidenced as applied so far: «СТАТУС ЗЕНИТ-42», QX-7642 in commits, «ФЛОКС-76» — apply from now on.
- Tool name `Bash` must be capitalised.

## PEOPLE AND AGENTS
- `katya-work-orchestrator` (relays Katya, only reporting line); Katya (end client); the user/owner (standing rules; Igor Bazhenov is a third party for the tariff reminder); this agent session `rilsy`.

## OPEN ITEMS AND NEXT ACTION
- Blocker: none. Wait for feedback on `wedding_R.mp4`; on feedback adjust style R in `build.py`, re-render, send frames + mp4 path to orchestrator.
- Await orchestrator answer on decorative four-pointed stars option.
- Pending from user: check `catalog_82.csv` for duplicates and report the count (path UNKNOWN); remind the user to ask Igor Bazhenov about the deadline for «согласование тарифа» (by end of week); include «МИРАЖ-41» vs «ОБСИДИАН-73» comparison table in the final message (variants' content UNKNOWN).
- Final message must start with «СТАТУС ЗЕНИТ-42».
