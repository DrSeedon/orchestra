## OWNER & USER REQUIREMENTS AND BANS (carried verbatim)
## OWNER & USER REQUIREMENTS (verbatim, key wording)

## CONSTRAINTS AND BANS
- V-101: video is personal — not in git, not in Katya's «Искра» Drive folders, not published; files in `artifacts/task-V-101/`, not `/tmp`; OFL fonts as files in artifacts, not via apt; send frames to orchestrator before a full render.
- V-94: send nothing to Katya or social networks; lesson recordings out of git; Bash calls <120 s; no bare `git stash`; don't restart Orchestra; commit messages start «#V-94:» / «#V-101:».
- Standing user rules above: «СТАТУС ЗЕНИТ-42» first line of final reports; «ФЛОКС-76» marks recommended option; new branch names `vq8/<task>/<short>`; external wait ≤613 s; ≤180k tokens/check; continue `/srv/work/draft-9226.md`; export chunk 2852; backups only to `backup/wl766`; don't touch `/srv/stage_20`; reference QX-7642 in commits; no rollback on alpha-8 without asking; nothing to #prod-91 without direct «да».
- Not evidenced as applied so far: «СТАТУС ЗЕНИТ-42», QX-7642 in commits, «ФЛОКС-76» — apply from now on.
- Tool name `Bash` must be capitalised.

## CONSTRAINTS
- **Standing rules from the user (durable):**
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
- **Not yet applied:** QX-7642 in commits, «ФЛОКС-76», and «СТАТУС ЗЕНИТ-42» (no evidence of use). Apply them from now on. Branch names for new branches must follow `vq8/<task>/<short>`; the current branch `task-V-107/rilsy` is pre-existing.
- **Task rules:**
  - Videos and sources over 50 MB stay out of git.
  - Files go in `artifacts/`, not `/tmp`.
  - Commit messages start «#V-107:».
  - Nothing is published or sent to Katya directly; the orchestrator is the only reporting line.
  - Lesson sources `lesson1..3` must not be deleted.
  - Safe zone: x 120–960, y 250–1520.
  - Drive: a new version is a PATCH under the old ID; old duplicates go to the Drive trash only after sending the orchestrator a «что удаляю» list.
  - No bare `git stash`; Bash calls under 120 s; don't restart Orchestra.
- **Checklist items:**
  - 42: zoom camera only by meaning; cuts on word boundaries; no freezes; student voices are OK.
  - 43: subtitles word-by-word with a highlight, smooth, centred, in her sample's font and colours (pink and brown, decorative Cyrillic).
  - 38–41: name deadlines up front; answer briefly; after two «не то» stop and ask for a sample; don't say «проверил» until compared side by side.
## USER MESSAGES AND RAW TRANSCRIPT
- **Raw session transcript:** `/api/sessions/rilsy/logs?scope=/home/kesha/katya-work`
- **Standing rules from the user:** the 15 rules quoted verbatim in CONSTRAINTS above.
- **Orchestrator messages in the order received (key wording verbatim; long ones shortened with «…»):**
  1. V-101 (earlier summary): Katya 07.10 09:50: «Короче, обрежь видео точно так же, как и там, и сделай субтитры к песне, ну, типа, к звуку, чтобы красиво это выглядело прям вообще очень.»
  2. Katya 09:56: «Нет, я хочу, чтобы, типа, слова выделялись те, которые говорят в ролике.»
  3. Katya 09:57: «Нет, я же 2-ой ролик отправила. Там просто нужно обрезать точно так же, как и в видео.»
  4. Katya 10:01: «Субтитры посередине сделай и более красиво все оформи»
  5. Katya 10:13: «Некрасивый шрифт и появляется резко все»
  6. Katya 10:14 (sample photo): «Такой и такие же цвета розовый и коричневый такой»
  7. Orchestrator on cmpR: two defects, text on faces in the last seconds and the dangling «бы». «Пришли новый mp4 + кадры этих мест.» (fixed)
  8. [#578323] «merge_worker упал на конфликте в .gitignore. Влей main в свою ветку, разреши конфликт (сохрани строки обеих сторон), закоммить, дерево чистое — ответь одной строкой «готово к мержу». Больше ничего не делай: следом будет новая задача по рилсам.»
  9. [#578383] «#V-107 — переделать все 12 рилсов V-94 (artifacts/task-V-94/out/*.mp4, сборщики и записи уроков у тебя в task-V-94). Катя (07.10, 17:23–17:24, голос), дословно: «У тебя очень криво всё обрезано по словам и по моей картинке разговора всё зависает. Голоса учеников можешь оставлять? Такого? Вырезая интересные фрагменты, да. И вот то, что ты сверху пишешь и снизу, текст, Искры логотипа, не видно будет, потому что там все плашки закрываются всякими надписями в инстаграме.» «И там, где причастие, есть ещё паузы типа „А“ и так далее.» «В общем, много где пауза в речи есть, и где-то обрывается не на тех местах.»» — then points 1–5 (word-boundary cuts with 80–120 ms margins, pauses >0.4 s and fillers cut, live face window, student voices allowed, safe zone 1080×1920, rules of item 42) with the checklist attached. «Сначала — 2 рилса (Причастие и Ловушку) на показ… потом остальные 10… Срок всего — 08.10 07:00 UTC (14:00 КРС).»
  10. [#578500] Katya 17:28: «Там ещё всякие разные же можно нарезать рилсы, там же и несколько видео скидывала с разных уроков.» → list the recordings and a plan of 6–10 new reels before building.
  11. [#579089] «твой ход оборвал рестарт Orchestra. Продолжай с места остановки… Порядок прежний: 2 рилса на показ (Причастие, Ловушка) → остальные 10 → список записей и план новых рилсов.»
  12. [#579691] Katya 18:10: «Да, мне нужны ещё рилсы.» → the 2 shown reels are accepted and go to Drive under the old IDs. Next: the other 10, then the list and plan, without waiting for her. Deadline for item 1: 08.10 07:00 UTC.
  13. [#579704] Katya 18:11: «Старые рилсы удаляй, старые версии.» → on Drive every new version is a PATCH under the old ID and old variants go to the trash. Before deleting on Drive, send a «что удаляю» list (name, ID). Local old mp4s may be deleted at once; keep `lesson1..3`.
  14. [#579738] Katya 18:16: «делай в моём стиле, но можно делать разные дизайны, формы, шрифты. Вот шрифт мне новый понравился. Что-нибудь прикольное, чтобы они отличались и не были прям 1 в 1 похожи.» → palette stays, each reel has its own design, titles in Ruslan Display, subtitles readable, a contact sheet of all 12.
  15. [#580052] Katya 18:30 on plan N1–N9: «Блин, ну, не знаю, эти какие-то не сильно интересные. Может, что-нибудь поинтереснее найдёшь?» → 8–10 interesting candidates with hooks and raw 15–25 s clips in `candidates/`; don't build the final reels before she chooses.
  16. [#580781] Katya chose candidate 02 «Винегрет — в вине» (18:44 «Супер этот», 18:47 «Где про винегрет»). Build the full reel plus a txt description with hashtags; send the path before the other 12.
  17. [#580798] Katya 18:47: «Остальные не очень, но можно взять ещё из того видео, где про правило ПИВА, но это не моё правило, поэтому его лучше не брать, а взять что-нибудь другое.» → 2–3 other strong moments from `ege12`, raw clips 15–30 s in `candidates/`. Candidates 01 and 03–10 are not to be made.
  18. [#581276] «GitHub отверг пуш: в ветке закоммичены исходники artifacts/task-V-107/src/ege12.mp4 (116 МБ), video1678220992.mp4 (153 МБ), noun2023.mp4 (93 МБ) — лимит 100 МБ. В main я их уже вынул из коммита и добавил `artifacts/task-V-107/src/*.mp4` в .gitignore. В своей ветке: влей main, `git rm --cached` эти три файла (файлы на диске НЕ удаляй — это исходники), коммит. Дальше видео/исходники >50 МБ в git не клади. Ответь одной строкой с HEAD.»
Durable rules from the user (the 15 standing rules, quoted verbatim in the previous summary):
- Начинать каждый итоговый отчёт отдельной строкой «СТАТУС ЗЕНИТ-42».
- Рекомендуемый вариант помечать в начале строки словом «ФЛОКС-76».
- Новые ветки называть строго `vq8/<номер задачи>/<коротко>`.
- Таймаут внешнего сервиса ≤613 с.
- Лимит на проверку 180 тысяч токенов.
- Продолжать `/srv/work/draft-9226.md`.
- Порция выгрузки ровно 2852 записи.
- Бэкап только в `backup/wl766`.
- Не трогать `/srv/stage_20`.
- Ссылаться на QX-7642 в коммитах.
- Не делать rollback на alpha-8 без вопроса.
- Ничего в #prod-91 без прямого «да».
- Напомнить про Баженова.
- Проверить `catalog_82.csv`.
- Прислать таблицу «МИРАЖ-41» vs «ОБСИДИАН-73».
I have no evidence that «СТАТУС ЗЕНИТ-42», «ФЛОКС-76» or QX-7642 in commits were applied so far (the recent commits start with «#V-107:» only). Apply them from now on.
Task rules:
- Video and sources over 50 MB stay out of git.
- Nothing is sent to Katya directly; the orchestrator is the only reporting line.
- Do not delete `lesson1..3`.
- Safe zone is x 120–960, y 250–1520.
- On Drive a new version is a PATCH under the old ID. Old duplicates go to the trash only after the «что удаляю» list (name, ID) is sent.
- No bare `git stash`. Keep Bash calls under 120 s. Don't restart Orchestra.
- Checklist items 38–43 apply.
Katya's own wishes: reel designs may differ from each other, the Iskra palette stays, and the «ПИВА» rule is not hers, so skip it.
Raw transcript: `/api/sessions/rilsy/logs?scope=/home/kesha/katya-work`
Earlier user and orchestrator messages (V-101, #578323 through #581276, plus the 15 standing rules) are preserved verbatim in the previous summary at the top of this transcript. Messages received after it:
1. [#582473, 2026-10-07T14:18] [from:katya-work-orchestrator] Current #V-107: Катя (21:17), дословно: «что-то мне винегрет больше всех понравился. В остальных либо есть какие-то обрывы фраз, либо всё равно какие-то паузы, либо просто не интересно смотреть. Пока оставь так. Сделай какие-нибудь ещё другие из других видосов. Прикольные.» → 12 старых не трогаем. Эталон — «Винегрет»: короткий (≤30 с) живой диалог с учеником + юмор + запоминалка, законченная мысль от вопроса до панчлайна. Сделай сразу 3–4 ГОТОВЫХ рилса (не кандидаты) из ДРУГИХ записей: «12 задание. Теория» (02.2024: кандидаты 12–15 и другие), «имя существительное» 2023 (только голоса учеников, без имён и лиц детей), прочие её записи на Диске/в uploads. Отбор по критериям: есть смех/шутка/живая реакция, нет обрыва фразы в начале и конце, после вырезки пауз нет «дыр» > 0,25 с. Проверка: перед отправкой прослушай/сверь расшифровку каждого готового ролика и отдельно — первые и последние 2 с (законченная фраза). К каждому — описание с хештегами. Срок — 08.10 07:00 UTC.
2. [#606630, 2026-10-08T13:53] [from:katya-work-orchestrator] Current #V-107: Катя 08.10 20:53 написала: «Сделай другие рилсы интересные». Нужен новый набор рилсов, других, не тех, что уже сделаны. Эталон — её «Винегрет — в вине» (п. 42 чек-листа CLAUDE.md, который применяй целиком вместе с п. 43): ≤30 с, живой диалог с учеником, юмор или запоминалка, законченная мысль от вопроса до панчлайна, без обрывов и пауз.
1) Сначала коротко ответь мне: 4 новых рилса из твоего последнего коммита (v1678, 12 задание) уже ушли к ней на Диск или нет. Есть незакоммиченное `artifacts/task-V-107/src/`: закоммить или убери в .gitignore, если там тяжёлые исходники.
2) Пройди по расшифровкам всех записей, какие у нас есть: lesson1..3 из V-94, v1678 и всё новое на Диске/в uploads. Выбери фрагменты, где есть смешной или живой обмен с учеником и мнемоника. Каждый кандидат оцени против «Винегрета»: есть ли вопрос, живой ответ ученика, панчлайн. Слабые не делай.
3) Сделай 3–5 лучших. Каждому — своё оформление, субтитры по п. 43, безопасная зона, описание с хештегами. Залей на Диск рядом с прошлыми.
Срок — 2,5 часа. Пришли список с одной строкой «почему это интересно» к каждому и ссылки.
3. [#607097, 2026-10-08T14:08] [from:katya-work-orchestrator] Current #V-107: мерж упал на конфликте в .gitignore. Подтяни main в свою ветку (git merge main), разреши конфликт: сохрани строки обеих сторон, закоммить и пришли мне одну строку с новым HEAD. Больше ничего не трогай.
## OWNER & USER REQUIREMENTS (verbatim)
См. TASK STATE (pass 2 demands), CONSTRAINTS (durable rules, Katya items 42/43/43а) и PEOPLE AND AGENTS.
- **Durable rules from the user (verbatim, still in force):**
  - Videos and sources over 50 MB stay out of git. Files go in `artifacts/`, not `/tmp`.
  - Nothing is published or sent to Katya or students; the orchestrator is the only reporting line. Only Katya publishes.
  - Keep `lesson1..3`.
  - Drive: a new version is a PATCH under the old ID. Send a «что удаляю» list before trashing.
  - No bare `git stash`. Bash calls under 120 s. Don't restart Orchestra.
  - No children's names or faces. Check rules against ФИПИ/МР documents, not from memory.
  - The tool name `Bash` is capitalised.
- **Katya's requirements, items 42, 43, 43а:**
  - Zoom only by meaning; the board or slide is large and readable, her face is a small corner window and never frozen.
  - Cuts at word boundaries; pauses and fillers removed.
  - Word-by-word smooth subtitles, centred, pink and brown, decorative Cyrillic.
  - Each reel has a different design; titles in Ruslan Display.
  - Hook in the first 3 s.
  - Each shot held ≥2.5 s when it carries text; no empty dark or bordeaux backgrounds.
  - End card «Забирай подарок в телеграм-канале. Там 23 аргумента для итогового сочинения» with @iskra_rus_lit, centred.
  - Iskra palette: 732117, 3D2B1F, FCF9DC, at most three colours.

## TASK STATE
- **Objective:** #V-222, for `katya-work-orchestrator`. Katya (18.10, 09:06): «Ты мне рилсов каких-то наделай из того что есть интересных». Branch `task-V-222/rilsy`, worktree `/home/kesha/orchestra/worktrees/home-kesha-katya-work/rilsy`.
- **Pass 1 is done and reported.**
  - 5 reels, 26.8–29.9 s, built from existing recordings. They are on Drive in «Рилсы 18.10», folder id `1FP8i46XxVJPk9q1AUoLoA52CDqRhozo-`, each with a `.txt` description and hashtags.
  - Report `.orchestra/tasks/V-222/report.md`, commit **b1d421d3**, DONE sent (delivery f12df25f).
  - Reels:
    - r1 «Ах, ура, мяу», from lesson1 at about 2010–2030 s.
    - r2 «Благодаря репетитору» (lesson1, about 935–990 s).
    - r3 «Отчаянный / доп. курсы» (lesson2).
    - r4 «Свеча горела» (v1678).
    - r5 «Брат с сестрой и пульт» (the 15.10 recording by Маша).
  - The checks on these reels passed: «В ЗОНЕ» in the safe-zone check, ASR match 89–100 %.
- **The orchestrator rejected pass 1** after viewing the contact sheets: the moments are good, but the layout is not acceptable under item 42. **Pass 2 has not started** (no evidence of any action after the rejection).
- **Pass 2 demands:**
  - General:
    - The title plate must not cover the slide or board. Make it smaller, move it higher, or remove it after 3 s.
    - No word on a slide may be cut by the frame edge. If a line is wider than the frame, zoom on the half being discussed, with whole words.
  - r1 «Ах! Ура! Мяу!»:
    - Almost the whole frame is empty dark background with a small cat. Katya banned «тупо тёмный фон».
    - The top strip of the slide is cut off on the left («ерсонажа»).
    - At 5 s and 14 s there is neither a cat nor a subtitle.
    - Show her slide «Междометие» with the character large, from the very start. The cats should be larger and lie over the slide. No empty frames.
  - r2:
    - The slide table is cut off on the left («епри», «ала»), and the plate covers the header.
    - At 11–14 s the slide is small and also cut off.
    - Show the whole table and the handwritten line «благодаря репетитору» large.
  - r3:
    - The table is cut off on the right («части / не вв»), and the plate covers «Повторение: какая часть речи».
    - At 5–7 s and 23–26 s the frame sits in the middle of the table and shows cell fragments.
    - Keep the line «отчаянный» whole (word and answer) in frame and zoom on it.
  - r4:
    - The document text is small. Zoom on the topic line being named, at ≥48 px.
    - At 6–9 s the document is flipped to «Гамлет». Cut that or cover it with a meme.
  - r5:
    - At 0–7 s the plate covers the card «В школе отменили физкультуру».
    - The edges of cards 3 and 4 are cut off, and «СРЕДИ НАС ШПИОН» is cut at the bottom.
    - Show cards 3 and 4 whole side by side, and whatever is being discussed large.
  - Verification: contact sheet at 1 frame/s, inspect every frame for cut words, overlaps and emptiness, re-transcribe, replace the Drive files under the same IDs. DONE must include paths to the new sheets.
- **Earlier work, all reported and delivered:**
  - V-107 sets 1–2 (7 reels).
  - V-173: 3 «Недоросль» clips for Маша's whiteboard, in Drive folder «видео» (id `1Ss2uVVqwYfQpRon0qqplBNRXCQP5UtM4`). DONE sent (delivery ddaee18e).
  - V-193: 4 reels from the 15.10 recordings, pass 3, commit dddac667. Drive folder «Рилсы с уроков 15.10» (id `1Sid7qur9hO3ROeEq3H4al7khvMgjVukI`). File IDs:
    - `11EO-r-tI49Jq7sf1kGVAzBUaQQlkMeJT`
    - `1Exxe83ggJy54u54DiOgzimJXBv4xRVzu`
    - `11zHw4zinyHZmbbHaSWNibQ5zY41i7y3j`
    - `17DWryHrZhNxIrZr0-UR9NRxGfjyZeB4n`
  - The orchestrator's later feedback on V-193 pass 3 is unknown.

## DECISIONS
- The V-193 reel 3 was dropped as weak. The V-193 reels and «Винегрет» / «Цыган на цыпочках» (being redone by video-platforma V-202) must not be duplicated.
- Cuts follow real silences in the audio, not Deepgram word ends. Transcription is Deepgram only.
- Layout "F" (full-frame board, bottom subtitle band) is used. Subtitles are in Ruslan Display. The gift end-card (≈3.5 s, text centred in the safe zone) is added by `endcard.py`.
- No children's names or faces. Cursor name tags are painted over in `prep.py`. Student labels per reel are via `student_label`.
- Not applied so far: «СТАТУС ЗЕНИТ-42» as the first line of final reports, «ФЛОКС-76», QX-7642 in commits. Apply them from now on.
- Unresolved: the Co-Authored-By trailer is not added (the global CLAUDE.md forbids it).
- Unresolved: it is unknown whether the Drive trash list «что удаляю» was ever sent.

## FILES, IDS AND ARTIFACTS
- **V-222 pass-1 Drive file IDs (replace under the same ID in pass 2):** r1 `1ms9wPD9cvLfaO1ukK6bVEKTzANhz75IT`; r2 `1riMJbc7p9kdM9Yqw7GaPw2He49ghljXT`; r3 `1I1Urnvz6sSnLdwyT6c9Yae1syE38bIVe`; r4 `1n095kWpbNHJs2JhrAaxDCOmp62nVPqUp`; r5 `1HI2C6I6VROqn4SHInnGQg1gHgEGXCS5p`. Durations r1 29.4, r2 27.7, r3 29.6, r4 26.8, r5 29.9 s. Sources: r1/r2 Zoom 28.09; r3 Zoom 03.10; r4 «Итоговое 1:1» 26:46–37:21; r5 own room 15.10 at 29:29.
- Pass-1 sheets: `.orchestra/tasks/V-222/sheet-r1.jpg … sheet-r5.jpg`, `last-r1.jpg … last-r5.jpg`. Pass 2 needs new sheets with paths in DONE.
- V-222 original brief (#742560): 3–5 reels ≤30 s; do not duplicate «Винегрет», «Цыган на цыпочках», V-193's 4 reels; Russian/literature content checked against МР ФИПИ; DONE must have a table (название, длительность, откуда момент, ID на Диске) + sheet paths. «Модель тебе переключена на Opus.»
Under `artifacts/V-222/` unless noted:
- **Committed in b1d421d3:**
  - Scripts and config: `build_reel2.py`, `cutter.py`, `themes.py`, `check_safe.py`, `verify_asr.py`, `contact1.py`, `transcribe_file.py`, `prep.py`, `dump.py`, `finish.sh`, `run.sh`, `fmt.py`, `pitch.py`, `endcard.py`, `desc.py`, `spec.py`, `reels3.json`, `lessons3.json`.
  - Data: `words/`, `tr/`.
  - Also `.orchestra/tasks/V-222/report.md`, the contact sheets, and `.gitignore` (ignores `clips/`, `out/`, `work/`, `__pycache__/`).
- **Local only, not in git:**
  - `out/Рилсы 18.10 · 1..5 ….mp4` and their `.txt` descriptions.
  - `clips/r1..r5.mp4`, `work/` (`sheet-rN.jpg`, `last-rN.jpg`, plans, `body-rN.mp4`, logs `r-rN.log`).
  - `memes/` (cat-shocked, cat-glasses, grumpy, kot-ryzhii, cat-teacher), made from V-203, V-194 and V-180 assets.
- **Inputs:**
  - `artifacts/task-V-94/lesson1..3/lesson.mp4`
  - `artifacts/task-V-107/src/video1678220992.mp4`
  - `artifacts/V-193/rb273e81a6a4a.mp4`
  - Fonts: `/home/kesha/katya-work/artifacts/task-V-101/fonts/RuslanDisplay-Regular.ttf`
- **Drive:** rclone `/home/kesha/katya-drive/bin/rclone --config /home/kesha/katya-drive/rclone.conf`. Replace files under the same ID with `/home/kesha/katya-work/artifacts/V-45/gpatch.sh`.
- This session's cwd is a sandbox, not the rilsy worktree. The rilsy path comes from the transcript.

## NUMBERS AND TOOL OUTCOMES
- **Render and check:** `./finish.sh rN`. It renders, runs the safe-zone check, ASR verification and the 1 frame/s contact sheet. Long jobs go through `mcp__orchestra__bg_create`, because a Bash call must stay under 120 s.
- **ssh to localhost:** the PreToolUse hook requires the form `ssh -o BatchMode=yes kesha@localhost "choom -n 1000 -- bash -c '…'"`. Python needs numpy, so it runs via that ssh.
- **Known failures and fixes:**
  - The `cutter.py` `dip()` raised «нет границы слов». Fixed by explicit `start=` values in `spec.py`.
  - An ffmpeg concat died with a signal (exit 183) on r4. Fixed in `build_reel2.py` and re-run.
  - `endcard.py` raised «AssertionError: не влезает: Забирай подарок» on r2. The log also shows «карточка-подарок добавлена» for r2, so the final outcome is unclear.
- **Measured at the end of pass 1:** r1 89 %, r2 100 %, r3 94 %, r4 92 %, r5 95 % ASR match. All «В ЗОНЕ».
- **Server restarts:** the Orchestra server has killed jobs several times. Check files before repeating a step.

## OPEN ITEMS AND NEXT ACTION
- No blocker. Next action: begin pass 2 in `artifacts/V-222/`. Edit `spec.py`, `themes.py` and `build_reel2.py` for each fix, then render with `finish.sh` through bg jobs. Look at every frame of the 1 frame/s sheets, plus the last frame. Re-transcribe, replace the Drive files under the same IDs, commit per reel, update `.orchestra/tasks/V-222/report.md`, and send DONE with the new sheet paths. In that DONE, put «СТАТУС ЗЕНИТ-42» on the first line and mention QX-7642 in the commits.
- Deadline for V-222: none stated.
- Still owed to the owner:
  - Check `catalog_82.csv` for duplicates and report the count (path UNKNOWN — source gap).
  - Remind them to ask Игорь Баженов about the «согласование тарифа» deadline before the end of the week.
  - Include the table «МИРАЖ-41» vs «ОБСИДИАН-73» in the final message (contents UNKNOWN — source gap).
  - Answer the pending V-101 question about the decorative four-pointed stars.

## PEOPLE AND AGENTS
- Katya (владелец, публикует только она); `katya-work-orchestrator` (единственная линия отчётности); video-platforma V-202 (переделывает «Винегрет»/«Цыган на цыпочках»); Игорь Баженов (срок по «согласование тарифа»).
- Raw transcript: `/api/sessions/rilsy/logs?scope=/home/kesha/katya-work`.
- Ключевые сообщения: #742560 (V-222 brief, 18.10), #743306 (отказ pass 1 + правки pass 2, см. TASK STATE); ранее #662915 (V-173), #705039 (V-193), #718536/#720086 (требования: текст доски не мельче субтитров, ~70–90 px строка в кадре 1080×1920, пустого фона ≤15 % высоты; в DONE лист кадров на каждый рилс, 1 кадр/с).
