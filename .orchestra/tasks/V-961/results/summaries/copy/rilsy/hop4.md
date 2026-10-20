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
## OWNER & USER REQUIREMENTS (verbatim, standing rules from the user — durable, still active)
(Contents of the Баженов/catalog_82/МИРАЖ-ОБСИДИАН items beyond these words are UNKNOWN; promise the table in the final message.)
## OWNER & USER REQUIREMENTS (verbatim, V-222 current task, orchestrator #743306)
- «плашка заголовка не должна закрывать слайд или доску. Сделай её меньше, подними выше или убери после 3 с»
- «Ни одно слово на слайде не должно обрезаться краем кадра; если строка шире кадра, наезжай на её половину, о которой говорят, но слова целиком.»
- «Проверка та же: лист кадров 1/с — смотри каждый кадр на обрезанные слова, перекрытия и пустоту. Повторная расшифровка, замена на Диске под теми же ID. В DONE — пути к новым листам.»
- #742560: «Кате ничего не отправлять» style: orchestrator is the only reporting line; DONE must contain a table (название, длительность, откуда момент, ID на Диске) + paths to frame sheets. Reels ≤30 s; hook in first 3 s; ≥2.5 s per image with text; no empty dark/burgundy backgrounds (Katya forbade «тупо тёмный фон»); end card «Забирай подарок в телеграм-канале. Там 23 аргумента для итогового сочинения» + @iskra_rus_lit; student voices OK, no names/faces. Model switched to Opus.
- Katya's wishes (V-107): palette Iskra stays, different design per reel, new font Ruslan Display; «ПИВА» rule is not hers — skip it.
- Drive: new version = PATCH under old ID; old duplicates go to trash only after sending orchestrator a «что удаляю» list (name, ID). Safe zone x 120–960, y 250–1520. Don't delete lesson1..3. Checklist items 38–43 apply.
- **Durable user rules:** the 15 standing rules from the earlier summary.
  - Start each final report with the separate line «СТАТУС ЗЕНИТ-42».
  - Mark the recommended option with «ФЛОКС-76» at the start of its line.
  - Branch names are `vq8/<task>/<short>`.
  - External wait ≤613 s; ≤180k tokens per check.
  - Continue `/srv/work/draft-9226.md`.
  - Export chunk 2852; backups only to `backup/wl766`.
  - Don't touch `/srv/stage_20`.
  - Reference QX-7642 in commits.
  - No rollback on alpha-8 without asking; nothing to #prod-91 without an explicit «да».
- **Not applied so far:** «СТАТУС ЗЕНИТ-42», «ФЛОКС-76» and QX-7642. The recent commits carry only «#V-xxx:» prefixes. Apply them from now on.
  - Publish and send nothing to Katya or students; the orchestrator is the only reporting line.
  - Video and sources over 50 MB stay out of git (limit 100 MB); work files go in `artifacts/`, not `/tmp`.
  - Commit messages start «#V-222:».
  - Never use bare `git stash`; keep Bash calls under 120 s; don't restart Orchestra.
  - Server `89.23.102.244` is read-only: download only.
  - No student names or faces in frame or subtitles.
  - Verify any grammar rule shown against the ФИПИ materials (МР), not from memory.
  - Items 42 and 43 apply in full: word-boundary cuts, pauses and fillers removed, no frozen face window, safe zone (not the top ~14 %, bottom ~20 % or right edge), word-by-word subtitles with the spoken word highlighted, Iskra palette, a different design per reel, Ruslan Display for titles, a hook in the first 3 s, a gift end card with @iskra_rus_lit.
Raw transcript: `/api/sessions/rilsy/logs?scope=/home/kesha/katya-work`. Earlier messages (V-101…#607097, incl. the standing rules) are in the previous summary. Later ones, condensed (full V-222 wording is in the requirements section):
1. #662915 (14.10) V-173: cut 3 «Недоросль» fragments (youtu.be/sHTARGBrqGE) for Masha's Meleto board; «Кате ничего не отправлять»; server 89.23.102.244: download only, delete downloaded files from /root/v171 afterwards. Done.
2. #705039 (15.10) V-193: 3–5 reels ≤30 s from the 15.10 lessons (rec rb273e81a6a4a; group room g-c0ff87d3a58c), reference «Винегрет — в вине», no names/faces, nothing published. Done.
3. #716926/#718536/#719871/#720086 (17.10) V-193 rework: board text not smaller than subtitles (~70–90 px line height in 1080×1920), empty background ≤15 % of frame height, remove «угу» in reel 3, listen to each reel via waveform + re-transcription, replace on Drive under same IDs, one frame sheet per reel at 1 frame/s. Done.
4. #742560 (18.10 02:10) V-222: see requirements. 5. #743306 (18.10 02:52) V-222 pass-2 corrections: see requirements/DECISIONS.

## TASK STATE
- **Current objective:** V-222 for `katya-work-orchestrator`, branch `task-V-222/rilsy`, worktree `/home/kesha/orchestra/worktrees/home-kesha-katya-work/rilsy`. Katya (18.10 09:06): «Ты мне рилсов каких-то наделай из того что есть интересных». The brief was 3–5 new reels ≤30 s from existing lesson recordings, with a gift end card, a description with hashtags per reel, and upload to Drive folder «Рилсы 18.10».
- **Pass 1 is done and was sent as DONE.** The commit is b1d421d3 and git was clean. Five reels are on Drive in «Рилсы → Рилсы 18.10» (folder `1FP8i46XxVJPk9q1AUoLoA52CDqRhozo-`), each with a `.txt` description:
  - r1 «Ах, ура, мяу — что за часть речи» (29.4 s)
  - r2 «Благодаря репетитору — предлог или деепричастие» (27.7 s)
  - r3 «Отчаянный — и доп. курсы для учителя» (29.6 s)
  - r4 «Свеча горела — на все темы итогового» (26.8 s)
  - r5 «Брат с сестрой и пульт — где шпион» (29.9 s)
  - Safe-zone check reported «В ЗОНЕ» for all five. Re-transcription match: r1 89 %, r2 100 %, r3 94 %, r4 92 %, r5 95 %.
- **The orchestrator rejected pass 1 (#743306).** Pass 2 is required, with replacement on Drive under the same IDs.
- **Earlier work, all reported DONE:**
  - V-173: 3 «Недоросль» clips for Masha's Meleto board, folder «видео» `1Ss2uVVqwYfQpRon0qqplBNRXCQP5UtM4`.
  - V-193: 4 reels from Masha's 15.10 lesson, final commit dddac667, folder «Рилсы с уроков 15.10» `1Sid7qur9hO3ROeEq3H4al7khvMgjVukI`. Drive file IDs: `11EO-r-tI49Jq7sf1kGVAzBUaQQlkMeJT`, `1Exxe83ggJy54u54DiOgzimJXBv4xRVzu`, `11zHw4zinyHZmbbHaSWNibQ5zY41i7y3j`, `17DWryHrZhNxIrZr0-UR9NRxGfjyZeB4n`. Reel 3 was dropped as weak.
  - V-107 sets 1 and 2 are in the previous summary.
- Pass 2 has not been started: no evidence of any edit after #743306.

## DECISIONS
- Pass 1 reels were built on the V-193 engine (layout F, full-frame board, Ruslan Display subtitles) and copied into `artifacts/V-222`.
- Moments came from `lesson1` (междометие 2010–2030 s, «благодаря репетитору», «отчаянный»), `lesson2`, and the V-193 recording `rb273e81a6a4a` (Masha: «Свеча горела», siblings and remote control).
- Cuts follow real silences, not Deepgram boundaries.
- A «dip»-style start was replaced by explicit start times where there was no silence.
- `gap_max` is configurable per reel.
- Cat and meme stickers are placed over the slide via a `memes` field.
- Ruslan is used for titles and subtitles.
- Student names and faces are kept out of frame. The cursor name-tag is painted over by background substitution.
- Orchestrator rules for pass 2: the title plate must not cover the slide or board, so make it smaller, raise it, or remove it after 3 s. No word on a slide may be clipped by the frame edge. If a line is wider than the frame, zoom to the half being discussed with whole words. There must be no empty dark frames. Hold every plan long enough to be read, ≥2.5 s per image with text.
- Per-reel fixes requested:
  - r1: no empty dark background; the top strip is cut at left («ерсонажа»); at 5 s and 14 s there is no cat and no subtitle. Show the «Междометие» slide with the character large from the start, with bigger cats on top of the slide.
  - r2: the table is clipped at left («епри», «ала») and the plate covers the header. At 11–14 s the slide is small and clipped. Show the whole table and the handwritten line «благодаря репетитору» large.
  - r3: the table is clipped at right («части / не вв») and the plate covers «Повторение: какая часть речи». At 5–7 s and 23–26 s the frame sits mid-table with cell fragments. Keep the whole «отчаянный» row (word and answer) in frame and zoom to it.
  - r4: the document text is small. Zoom to the topic line being named, ≥48 px. At 6–9 s the document is flipped to «Гамлет», so cut it or cover it with a meme.
  - r5: at 0–7 s the plate covers the card «В школе отменили физкультуру». The edges of cards 3 and 4 are clipped and «СРЕДИ НАС ШПИОН» is cut at the bottom. Show cards 3 and 4 whole side by side, and show what is being discussed large.
- Unresolved: the Co-Authored-By trailer. The global rule forbids it and a system reminder asks for it, so it is not added.

## FILES AND ARTIFACTS
- All paths below are under the rilsy worktree; `artifacts/V-222/` is the V-222 working dir.
- **Committed in b1d421d3** (and e4974938, the engine commit):
  - `artifacts/V-222/` scripts: `build_reel2.py`, `cutter.py`, `themes.py`, `prep.py`, `spec.py`, `reels3.json`, `lessons3.json`, `endcard.py`, `desc.py`, `finish.sh`, `run.sh`, `contact1.py`, `check_safe.py`, `verify_asr.py`, `transcribe_file.py`, `dump.py`, `pitch.py`, `fmt.py`, plus `words/` and `tr/`.
  - `.gitignore` entries for `artifacts/V-222/{clips,out,work,__pycache__}/`.
  - `.orchestra/tasks/V-222/report.md` and the frame sheets.
- **Local only, not in git:** `artifacts/V-222/out/*.mp4`, `.txt`, `work/` (sheets `sheet-r*.jpg`, `last-r*.jpg`, logs `r-r*.log`), `clips/`, `memes/` (cat-shocked, cat-glasses, grumpy, kot-ryzhii, cat-teacher).
- **Inputs:**
  - `artifacts/task-V-94/lesson1..3/lesson.mp4` (never delete)
  - `artifacts/task-V-107/src/video1678220992.mp4`
  - `artifacts/V-193/rb273e81a6a4a.mp4`
  - `artifacts/task-V-107/words/*.json`
- **Reference docs:**
  - `.orchestra/tasks/V-220/report.md` (what performs well in short videos)
  - `AGENTS.md` / `CLAUDE.md`, items 42, 43, 43а
  - `.orchestra/kb/rilsy-nareznya-zoom.md`
- **Drive:** rclone is `/home/kesha/katya-drive/bin/rclone --config /home/kesha/katya-drive/rclone.conf`. Replace files via `/home/kesha/katya-work/artifacts/V-45/gpatch.sh`, which patches under the same ID.
- This session's cwd is a different worktree. The rilsy path comes from the transcript.

## COMMANDS AND TOOL OUTCOMES
- **Render and check one reel:** `./finish.sh <id>` from `artifacts/V-222`. It runs the build, the safe-zone check, `verify_asr` and the contact sheet (1 frame per second). Remove `work/body-<id>.mp4` before a rebuild, otherwise the old body is reused.
- **Pipeline order:** `./run.sh prep` (clips, words, `reels3.json`), then `./run.sh plan`, then `finish.sh`.
- **Hook rule:** `ssh kesha@localhost` commands must be wrapped as `ssh -o BatchMode=yes kesha@localhost 'choom -n 1000 -- bash -c "cd <dir> && …"'`. The first attempt without `choom` was rejected by a hook. Bash calls over 120 s go through `mcp__orchestra__bg_create`.
- **End card:** `python3 endcard.py <id>`. For r2 it failed once with «AssertionError: не влезает: Забирай подарок». It later reported «карточка-подарок добавлена», so the text was apparently fixed.
- **r4 failure:** `ffmpeg` exit 183 (`died with Signals`) while building r4. Cause unconfirmed; r4 later rendered after a `build_reel2.py` change, so it is not reproduced.
- **Safe-zone result:** the pass-1 values in TASK STATE are from the final logs.
- **Gaps:** I viewed the sheets myself but did not verify the last frames of every reel, and no ears-on listening was done. The in-recording pan in r5 is Katya's own scrolling.

## BLOCKER / NEXT
- **Blocker:** none technical. The orchestrator rejected pass 1.
- **Next executable action:** make the pass-2 edits in `artifacts/V-222/spec.py`, `prep.py` and `build_reel2.py` per DECISIONS. Rebuild with `finish.sh`, then look at each frame of the 1 frame/s sheets for clipped words, overlap and empty frames. Then re-transcribe and replace the Drive files under the same IDs with `gpatch.sh`. Commit, then send DONE to `katya-work-orchestrator` with the paths to the new sheets.
- **Open items for the owner** (contents or paths unknown, so not actionable yet):
  - check `catalog_82.csv` for duplicates and report the count (path UNKNOWN — source gap)
  - remind about Игорь Баженов and «согласование тарифа» before the end of the week
  - include the short comparison table «МИРАЖ-41» vs «ОБСИДИАН-73» in the final message (contents UNKNOWN — source gap)
  - the V-101 question about decorative four-pointed stars
  - whether the old-duplicates «что удаляю» list was sent (UNKNOWN)
