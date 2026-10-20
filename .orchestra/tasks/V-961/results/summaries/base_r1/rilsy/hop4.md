## TASK STATE
- **Current task: #V-222**, 5 reels from existing lesson recordings (Katya 18.10 09:06: «Ты мне рилсов каких-то наделай из того что есть интересных»). Reporting line is only `katya-work-orchestrator`. Model switched to Opus.
- **Status:** first DONE sent (commit b1d421d3, delivery_id=f12df25f-b051-440c-a95c-03376929b208). Orchestrator (18.10 02:52, last journal event id 743306) rejected it as is: «Моменты выбраны хорошо, но в таком виде Кате отдавать нельзя: по п. 42 главное в кадре — слайд, крупно и читаемо, ничего не налезает. Нужен второй проход». **Second pass NOT started**; no edits since the DONE. Checklist was at 2 of 5; remaining: build, checks, Drive upload/report.
- **Second-pass requirements (orchestrator, verbatim-close):**
  - All: «плашка заголовка не должна закрывать слайд или доску. Сделай её меньше, подними выше или убери после 3 с». «Ни одно слово на слайде не должно обрезаться краем кадра; если строка шире кадра, наезжай на её половину, о которой говорят, но слова целиком.»
  - r1 «Ах! Ура! Мяу!»: almost whole frame is empty dark background with a small cat; Katya banned «тупо тёмный фон». Top slide strip cut on the left («ерсонажа»). At 5 s and 14 s no cat and no subtitle. «Сделай её слайд «Междометие» с персонажем крупно (с 17 с он уже есть) и держи его с самого начала, а коты пусть будут крупнее и лежат поверх слайда. Пустых кадров быть не должно.»
  - r2 «Благодаря репетитору»: slide table cut on the left («епри», «ала»), plate covers header. At 11–14 s slide small and cut. «Нужна таблица целиком и рукописная строка «благодаря репетитору» крупно.»
  - r3 «Доп. курсы»: table cut on the right («части / не вв»), plate covers «Повторение: какая часть речи». At 5–7 s and 23–26 s frame sits mid-table with cell fragments. «Держи в кадре строку «отчаянный» целиком (слово и ответ) и наезжай на неё.»
  - r4 «Свеча горела»: document text small. «Наезжай на строку темы, которую сейчас называют, крупно (≥48 px).» At 6–9 s document flipped to «Гамлета»: «вырежи это или закрой мемом».
  - r5 «Брат с сестрой»: at 0–7 s plate covers card «В школе отменили физкультуру». Edges of cards 3/4 cut, «СРЕДИ НАС ШПИОН» cut at the bottom. «Покажи карточки 3 и 4 целиком рядом, а то, о чём говорят, — крупно.»
  - Check: «лист кадров 1/с — смотри каждый кадр на обрезанные слова, перекрытия и пустоту. Повторная расшифровка, замена на Диске под теми же ID. В DONE — пути к новым листам.»
- **Earlier tasks:**
  - V-107: idle (HEAD 502fa9a, merge reported).
  - V-173: DONE sent; 3 «Недоросль» clips in Drive folder «видео» id `1Ss2uVVqwYfQpRon0qqplBNRXCQP5UtM4`, commit edb8ccb. Deletion of downloads on 89.23.102.244 (/root/v171) was not verified in visible output.
  - V-193: 4 reels delivered after 3 passes (p3 «Выучить — это подвиг» dropped as weak), final commit dddac667. Drive «Рилсы с уроков 15.10» id `1Sid7qur9hO3ROeEq3H4al7khvMgjVukI`; file IDs p1 `11EO-r-tI49Jq7sf1kGVAzBUaQQlkMeJT`, p2 `1Exxe83ggJy54u54DiOgzimJXBv4xRVzu`, p4 `11zHw4zinyHZmbbHaSWNibQ5zY41i7y3j`, p5 `17DWryHrZhNxIrZr0-UR9NRxGfjyZeB4n`. No feedback after pass 3.

## OWNER & USER REQUIREMENTS (verbatim)
**V-222 original brief (orchestrator, 18.10 02:10), still applies:**
- 3–5 new reels ≤30 s from existing recordings (Zoom recordings in artifacts of past tasks, own room /opt/urok/data/rec/ on SeedonRuInfra — read only; search all, not only 15.10). Pick liveliest moments, not «кусок объяснения». Guide: V-220 research (`.orchestra/tasks/V-220/report.md`, section 4): student guesses/errs funnily, live dialogue with punchline, riddle with answer, «учитель против…». Reference «Винегрет — в вине» (п. 42): complete thought from question to punchline.
- Do not duplicate «Винегрет», «Цыган на цыпочках» (V-202, video-platforma) or V-193 reels («Ну, сдайся!», «Шарики…», «Спать — это отдых», «Мне — не подлежащее»).
- Katya's rules (AGENTS.md п. 42, 43, 43а — read whole): cuts exactly on words, pauses and «э-э» cut, face window doesn't freeze; main thing in frame is slide/board large and legible, her face a small window; zoom by meaning; text in Reels safe zone (not top ~14%, bottom ~20%, not right edge); word-by-word subtitles, spoken word highlighted, smooth, centered, her font/color sample (decorative Cyrillic, pink and brown); reels differ in design; hook in first 3 s; shot changes 1–3 s, memes/pictures for words, BUT «слишком быстро всё мелькает, ничего не понятно» → ≥2.5 s per picture with text; no empty dark/burgundy backgrounds; end card «Забирай подарок в телеграм-канале. Там 23 аргумента для итогового сочинения» and @iskra_rus_lit (new address!), text exactly centered, not stuck to the edge. Student voices OK, no names or faces. Rules checked against MR FIPI/navigator documents, not memory.
- Describe each reel in text with hashtags for copying. Before DONE: frame sheet 1 frame/s and last frame of each reel — look yourself; re-transcription: no cut words. Put on her Drive in the rilsy folder (new subfolder «Рилсы 18.10»), publish nothing, send nothing to students.
- DONE format: table (title, duration, source of moment, Drive ID) + paths to frame sheets.
**From V-193 (apply to V-222 too):** п. 42: zoom only by meaning, hold, then smoothly to next; slide fully visible and legible otherwise («не приближать СДВГ-шно туда-сюда, а по смыслу, и чтоб слайд было тоже полностью видно и было читаемо»); face small corner window («Ну это же кринж что за лицо на весь кадр»); cuts exactly on word/phrase boundaries; cut pauses. Palette Iskra: бордовый 732117, коричневый 3D2B1F, кремовый FCF9DC, ≤3 colors, not bright; headings in decorative Ruslan Display. Method KB: `.orchestra/kb/rilsy-nareznya-zoom.md`. Don't trust Deepgram word-end timings; set cuts at silence and verify by re-transcription. Transcription only Deepgram. Students are minors, videos public: no student cameras in frame (cover/crop tiles), no names in subtitles/captions (cut/mute if said aloud). Board text size ≈70–90 px line height in 1080×1920, no more than 15% empty background; if source resolution insufficient, say pixel size of the source. Cursor tag plate (purple) must not cover words — paint over with board background.

**Standing user rules (durable, verbatim):**
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
- No evidence yet that «СТАТУС ЗЕНИТ-42», QX-7642 commit reference or «ФЛОКС-76» were applied. Apply from now on. The vq8 branch rule covers NEW branches only; existing `task-V-*/rilsy` stay. These rules come from the earlier compaction and stay in force.

## DECISIONS
- Reuse the V-193 engine for V-222. Layout «F» = full-frame board with a band under subtitles. Subtitles Ruslan Display, word by word.
- End card appended by `endcard.py`, centered. Memes (cat-shocked, cat-glasses, grumpy, kot-ryzhii, cat-teacher) in `artifacts/V-222/memes/`.
- r5 in-recording pan was judged Katya's own scrolling and left; now revisited by orchestrator's r5 feedback.
- Student labels «ученик:»/«ученица:», no names. Cursor name tags painted over.
- Moments (all five stay): r1 interjection (lesson1 ~2014–2030), r2 «Благодаря репетитору» (lesson2 ~935–), r3 «Отчаянный»/доп. курсы, r4 «Свеча горела» (v1678, ~632–), r5 «Брат с сестрой» (card game, V-193 Masha recording ~1769–1827). Exact mapping in `artifacts/V-222/spec.py` (not re-verified).
- Earlier edits: `build_reel2.py` — per-reel `fs`, `student_of`, meme overlay, `RAMP` condition (`starts[1] - starts[0] < RAMP`), trim/atrim fix (r4 ffmpeg failure). `cutter.py`: `dip()` hard error relaxed.

## FILES, IDS AND ARTIFACTS
- Worktree: `/home/kesha/orchestra/worktrees/home-kesha-katya-work/rilsy` (branch `task-V-222/rilsy`); base `artifacts/V-222/`. Current session cwd is a sandbox (`.../hop4/sandbox/draft`), NOT that worktree — verify path first.
- Committed in b1d421d3: scripts `spec.py, prep.py, build_reel2.py, cutter.py, themes.py, endcard.py, desc.py, finish.sh, run.sh, pitch.py, fmt.py, check_safe.py, verify_asr.py, contact1.py, transcribe_file.py, dump.py`; data `reels3.json, lessons3.json, words/, tr/`; `.orchestra/tasks/V-222/report.md` + sheets (names unknown). Git-ignored: `artifacts/V-222/{clips,out,work,__pycache__}/`.
- Outputs in `artifacts/V-222/out/` (all «В ЗОНЕ»; a `.txt` description with hashtags beside each):

| Reel | File | Dur s | ASR |
|---|---|---|---|
| r1 | `Рилсы 18.10 · 1. Ах, ура, мяу — что за часть речи.mp4` | 29.4 | 89% |
| r2 | `Рилсы 18.10 · 2. Благодаря репетитору — предлог или деепричастие.mp4` | 27.7 | 100% |
| r3 | `Рилсы 18.10 · 3. Отчаянный — и доп. курсы для учителя.mp4` | 29.6 | 94% |
| r4 | `Рилсы 18.10 · 4. Свеча горела — на все темы итогового.mp4` | 26.8 | 92% |
| r5 | `Рилсы 18.10 · 5. Брат с сестрой и пульт — где шпион.mp4` | 29.9 | 95% |

- Sheets: `artifacts/V-222/work/sheet-r{1..5}.jpg` (1 frame/s); last frames `work/last-*.jpg` (not confirmed for every reel).
- Drive folder «Рилсы 18.10» in «Рилсы», id `1FP8i46XxVJPk9q1AUoLoA52CDqRhozo-`. Seen txt IDs: r1 `1TJvq5ueINLUWADTU37_QPJiFByNf4xjL`, r2 `1av2QU1pBTBLgXpSawpNrEdA3RIks4hA5`, r3 `1_IdVZiUbdcN3a_BHQVoGTmSB6CmgZnAv`, r4 `1Gl6yRsgDCxA7UbiOHn4a5Y4DU7rY2BnC`; mp4 IDs are in the DONE message/report (not visible). Replace via `/home/kesha/katya-work/artifacts/V-45/gpatch.sh <id> <file>`.
- Tooling: `./finish.sh rN` (render, safe zone, ASR, sheet); `./run.sh prep|plan`. Run `ssh kesha@localhost` commands as `choom -n 1000 -- bash -c '...'` (hook «ssh_agent_oom_priority»). Bash calls <120 s; long renders via `mcp__orchestra__bg_create` (restarts interrupted jobs; check files after restart).
- V-173 source: https://youtu.be/sHTARGBrqGE; Drive remote `iskra:` via `/home/kesha/katya-drive/bin/rclone --config /home/kesha/katya-drive/rclone.conf`.
- Note: Deepgram showed «междуметее» in r1 — machine error, not a reel defect. Cut-word check for r1 and r4 pending after second pass.

## CONSTRAINTS AND BANS
- Publish and send nothing; only Katya publishes. Nothing to students.
- Server 89.23.102.244 and /opt/urok/data/rec are read-only.
- Video/sources >50 MB never in git; files in `artifacts/`, not `/tmp`.
- Commit messages start «#V-NNN:». Commit finished pieces one at a time (restarts interrupt turns).
- Drive: update by PATCH under same IDs; before any Drive deletion first send orchestrator a «что удаляю» list; never delete `lesson1..3`.
- Check AGENTS.md п. 42, 43, 43а: shot with text held ≥2.5 s, hook in first 3 s, end gift card, no student names/faces, FIPI-checked rules.
- Don't restart Orchestra; no bare `git stash`. Reports in Russian, short, deadlines up front.
- Unresolved: system reminder asks Co-Authored-By trailer while global CLAUDE.md forbids; prior commits have none.

## PEOPLE AND AGENTS
- `katya-work-orchestrator` — sole reporting line for tasks. Katya — owner of content/publishing. video-platforma — other agent (V-202, Винегрет/Цыган). Igor Bazhenov — contact for the «согласование тарифа» deadline.

## OPEN ITEMS AND NEXT ACTION
- **Next:** in `artifacts/V-222`, open `work/sheet-r1..r5.jpg`, fix per-reel `shots`/layout in `spec.py` and `themes.py`, rebuild via `finish.sh`. Start with r1 (full «Междометие» slide from start, large cats over slide, no empty frames). Then re-check every frame at 1 fps, re-transcribe, replace on Drive under same IDs, commit (`#V-222:`), send DONE with new sheet paths (+ table). Blocker: none known.
- Owed to user, still open: check `catalog_82.csv` for duplicates and report count (path UNKNOWN); remind to ask Igor Bazhenov for the «согласование тарифа» deadline (by end of week); include «МИРАЖ-41» vs «ОБСИДИАН-73» comparison table in final message (content UNKNOWN); V-101 `wedding_R.mp4` feedback and four-pointed stars answer pending.
