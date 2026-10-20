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
## CONSTRAINTS AND BANS / OWNER & USER REQUIREMENTS (verbatim)
- Durable from the user (verbatim; no evidence they have been applied — apply from now on: «СТАТУС ЗЕНИТ-42» line first in final reports, «ФЛОКС-76» marker, QX-7642 in commits; new branches only `vq8/<номер>/<коротко>`, current branch is pre-existing):
- Katya's requirements (items 42–43/43а, from orchestrator): zoom only by meaning, slide/board large and readable with her face as a small corner window; cuts exactly on words, pauses/«э-э» cut, no face-window freeze; text in Reels safe zone (not top ~14%, bottom ~20%, right edge); word-by-word subtitles, spoken word highlighted, smooth, centred, her font/colours (pink/brown; Iskra palette 732117 / 3D2B1F / FCF9DC, ≤3 colours); titles in Ruslan Display; each reel has own design; hook in first 3 s; plan change 1–3 s but ≥2,5 с на картинку с текстом; no empty dark/burgundy backgrounds; end card «Забирай подарок в телеграм-канале. Там 23 аргумента для итогового сочинения» + @iskra_rus_lit (new address), text exactly centred; Katya forbade «тупо тёмный фон»; rule claims checked against МР ФИПИ; description with hashtags per reel; transcription Deepgram only; don't trust Deepgram word-end timings; KB `.orchestra/kb/rilsy-nareznya-zoom.md`; V-220 report `.orchestra/tasks/V-220/report.md`.
- Older V-107 state: HEAD 502fa9a pushed? UNKNOWN; three big src mp4s (ege12 116 MB, video1678 154 MB, noun2023 93 MB) still in branch history (squash-merge/history rewrite is hard to reverse — confirm with orchestrator first). Old V-107 Drive reels: PATCH under old ID, old duplicates to trash only after sending «что удаляю» list (name, ID); don't delete `lesson1..3`. V-101 pending: decorative four-pointed stars question, feedback on `wedding_R.mp4`.
- Task rules: no video over 50 MB in git; nothing published or sent to Katya (the orchestrator is the only line); students' names and faces out of frame; the safe zone is x 120–960, y 250–1520; Bash calls under 120 s; no bare `git stash`; the tool name is `Bash`, capitalised; do not restart Orchestra; commit messages start with «#V-222:».
- For read-only server work on SeedonRuInfra, never delete or change anything there.
## OWNER & USER REQUIREMENTS — messages (kept in short; earlier V-101/#578323–#607097 messages and the 15 standing rules were in the previous summary — UNKNOWN beyond what is listed here)
Raw transcript: `/api/sessions/rilsy/logs?scope=/home/kesha/katya-work`.
- [#742560, 2026-10-18T02:10, orchestra] #V-222 order: «Ты мне рилсов каких-то наделай из того что есть интересных» (Katya). 3–5 new reels ≤30 с from existing recordings (Zoom in artifacts, `/opt/urok/data/rec/` on SeedonRuInfra read-only). Живые моменты, не «кусок объяснения»; ориентир — V-220 report; эталон «Винегрет — в вине»; «слишком быстро всё мелькает» → ≥2,5 с на картинку с текстом; end card; description with hashtags per reel; Drive subfolder «Рилсы 18.10»; «ничего не публиковать, ученикам не отправлять». DONE must have a table (название, длительность, откуда момент, ID на Диске) + paths of frame sheets. Model switched to Opus.
- [#743306, 02:52, orchestra] Pass-2 order: «Моменты выбраны хорошо, но в таком виде Кате отдавать нельзя: по п. 42 главное в кадре — слайд, крупно и читаемо, ничего не налезает.» Per-reel list is in OPEN ITEMS. «Проверка та же: лист кадров 1/с — смотри каждый кадр на обрезанные слова, перекрытия и пустоту. Повторная расшифровка, замена на Диске под теми же ID. В DONE — пути к новым листам.»
- Earlier closed tasks' lessons (V-193 rework): board must be large (~70–90 px line height in 1080×1920, ≤15% empty background), student cursor label painted over, subtitles large, centred, word-by-word; if the source is too low-res, say how many pixels the source has. #V-173 required deleting downloaded files from `/root/v171` on 89.23.102.244 (no evidence done).
- Hook feedback: ssh to kesha@localhost must start with `choom -n 1000 --`.

## TASK STATE
- Current objective: #V-222 for `katya-work-orchestrator`, on branch `task-V-222/rilsy` in the rilsy worktree `/home/kesha/orchestra/worktrees/home-kesha-katya-work/rilsy`. The task is 3–5 new reels of ≤30 s from existing lesson recordings. The reference is «Винегрет», with items 42, 43 and 43а and a gift end-card.
- Phase: pass 1 is delivered. The orchestrator rejected it as unfit for Katya and ordered **pass 2**. Pass 2 has not been started (no evidence of any action on it).
- Pass 1 outcome: 5 reels r1–r5, committed as b1d421d3, DONE sent (delivery f12df25f). Drive folder «Рилсы 18.10» has ID `1FP8i46XxVJPk9q1AUoLoA52CDqRhozo-`. Its parent is `1mWgLUeJRjT40FAFey7iiZ9Etsh9evwT1`. Each reel has a `.txt` with a description and hashtags.
- Pass-1 reels (name / length / source): 1 «Ах! Ура! Мяу!» 29,4 с — Zoom 28.09 «Части речи» 33:34; 2 «Благодаря репетитору я сдал экзамены» 27,7 с — Zoom 28.09 15:39; 3 «Ученик предложил учителю доп. курсы» 29,6 с — Zoom 03.10 13:30; 4 «Один рассказ — на все темы итогового» 26,8 с — итоговое 1:1 26:46–37:21; 5 «Брат с сестрой поссорились из-за пульта» 29,9 с — своя комната 15.10 урок Маши 29:29.
- Pass-1 render checks: all five «В ЗОНЕ» (safe zone); ASR match r1 89%, r2 100%, r3 94%, r4 92%, r5 95%. Durations were 29.4, 27.7, 29.6, 26.8 and 29.9 s per the ffprobe output, matched to files in `out/` order, so the mapping is not verified.
- Earlier tasks, all closed:
  - #V-173: 3 «Недоросль» clips are on Drive in the «видео» subfolder (ID `1Ss2uVVqwYfQpRon0qqplBNRXCQP5UtM4`). Commit edb8ccb, DONE sent. Server cleanup of `/root/v171` was part of the order; no evidence it was done.
  - #V-193: 4 reels from the 15.10 lessons (p3 dropped as weak). Drive folder `1Sid7qur9hO3ROeEq3H4al7khvMgjVukI`, commit dddac667, DONE sent.
  - #V-107 sets 1 and 2 and the merges: see the earlier summary. HEAD 502fa9a on `task-V-107/rilsy` at that time.

## DECISIONS
- The 5 moments are picked and kept for pass 2. The orchestrator said they were chosen well.
  - r1: «Ах! Ура! Мяу!» (lesson1, ~2010–2030 s, interjection).
  - r2: «Благодаря репетитору…» (lesson1, ~935–1000 s).
  - r3: «Отчаянный» and extra courses for the teacher.
  - r4: «Свеча горела» (video1678).
  - r5: brother and sister over the remote (V-193 recording rb273e81a6a4a, ~1769–1827 s).
- Not to duplicate: «Винегрет» and «Цыган на цыпочках» (V-202 owns them), and the four V-193 reels.
- Cuts follow real silences, not Deepgram boundaries. Transcription is Deepgram only.
- Layout "F" (full-screen board) is used, with memes (cats) and a gift end-card of ~3.5 s.
- Names and faces of students must not appear. The student cursor label is painted over.
- Student rule for rule claims: check them against the FIPI methodological recommendations (`ru_mr_2025.pdf` in `.orchestra/tasks/28-program/sources`).
- Unresolved: the Co-Authored-By trailer is not added (global rule forbids it).

## FILES, IDS AND ARTIFACTS
Under `artifacts/V-222/`:
- Committed in b1d421d3: `spec.py`, `prep.py`, `build_reel2.py`, `cutter.py`, `themes.py`, `check_safe.py`, `verify_asr.py`, `contact1.py`, `endcard.py`, `desc.py`, `finish.sh`, `run.sh`, `pitch.py`, `fmt.py`, `reels3.json`, `lessons3.json`, `words/`, `tr/`.
- Untracked by `.gitignore`: `clips/`, `out/` (5 mp4 plus `.txt`), `work/` (sheets, logs), `memes/`.
- Report: `.orchestra/tasks/V-222/report.md`, committed.
- Sources (read-only): `artifacts/task-V-94/lesson1..3/lesson.mp4`, `artifacts/task-V-107/src/video1678220992.mp4`, `artifacts/V-193/rb273e81a6a4a.mp4`.
- The sticker source paths for the memes are in `artifacts/V-203/assets/cut/`, `V-194/src/memes/` and `V-180/stickers/`; prepared copies are in `memes/`.

## COMMANDS (part of FILES, IDS AND ARTIFACTS)
- Render and check one reel: `./finish.sh <id>` from `artifacts/V-222`. It runs the build, safe-zone check, ASR verification and a 1 frame/s contact sheet (`work/sheet-<id>.jpg`). Remove `work/body-<id>.mp4` first to force a rebuild.
- `./run.sh prep` rebuilds clips and masks; `./run.sh plan <ids>` builds cut plans. Long jobs go through `mcp__orchestra__bg_create`.
- **Hook rule:** any `ssh kesha@localhost` command must start with `choom -n 1000 --`. Form: `ssh -o BatchMode=yes kesha@localhost "choom -n 1000 -- bash -c '...'"`.
- The ffmpeg filter graph crashed on r4 once (exit 183, signal). A rebuild with `rm -f work/body-r4.mp4` then worked.
- Drive upload and replacement: `/home/kesha/katya-drive/bin/rclone --config /home/kesha/katya-drive/rclone.conf` to `iskra:`, with `--drive-root-folder-id`. For V-193, replacement under the same ID used `/home/kesha/katya-work/artifacts/V-45/gpatch.sh`. Drive file IDs in «Рилсы 18.10» (replace under these IDs via PATCH, don't create new files): mp4 r1 `1ms9wPD9cvLfaO1ukK6bVEKTzANhz75IT`, r2 `1riMJbc7p9kdM9Yqw7GaPw2He49ghljXT`, r3 `1I1Urnvz6sSnLdwyT6c9Yae1syE38bIVe`, r4 `1n095kWpbNHJs2JhrAaxDCOmp62nVPqUp`, r5 `1HI2C6I6VROqn4SHInnGQg1gHgEGXCS5p`; txt r1 `1TJvq5ueINLUWADTU37_QPJiFByNf4xjL`, r2 `1av2QU1pBTBLgXpSawpNrEdA3RIks4hA5`, r3 `1_IdVZiUbdcN3a_BHQVoGTmSB6CmgZnAv`, r4 `1Gl6yRsgDCxA7UbiOHn4a5Y4DU7rY2BnC`, r5 `17RXt6Px3ireISW4a4s8BS2AEh5YOyZyL`. Sheets/last frames already in `.orchestra/tasks/V-222/` (sheet-r1..r5.jpg, last-r1..r5.jpg, report.md); new pass-2 sheets must go there too (don't overwrite blindly; give new paths in DONE).

## OPEN ITEMS AND NEXT ACTION
- Blocker: none. This is a rework order from the orchestrator.
- Next single action: start pass 2 on r1–r5 per the orchestrator's list, then re-render, view the 1/с sheets frame by frame, re-run ASR, replace the files on Drive under the same IDs, commit, and send DONE with paths to the new sheets. Items per reel:
  - All: the title plate must not cover the slide. Make it smaller, higher, or remove it after 3 s. No word on a slide may be cut by the frame edge; if a line is wider than the frame, zoom on the half being discussed, with whole words.
  - r1: remove the empty dark background. Use the "Междометие" slide with the character large from the start. Cats larger, on top of the slide. No empty frames (none at 5 s and 14 s). Fix the clipped top strip («ерсонажа»).
  - r2: show the whole table (not clipped on the left: «епри», «ала»). The plate must not cover the header. Show the handwritten line «благодаря репетитору» large at 11–14 s.
  - r3: the table is clipped on the right. The plate covers «Повторение: какая часть речи». Keep the «отчаянный» line whole (word and answer) and zoom on it. Fix 5–7 s and 23–26 s, where cell fragments show.
  - r4: text ≥48 px, zoom on the topic line being named. Cut or cover with a meme the segment at 6–9 s where the document is on «Гамлет».
  - r5: the plate covers the «В школе отменили физкультуру» card at 0–7 s. Show cards 3 and 4 whole side by side, and «СРЕДИ НАС ШПИОН» whole. Show what is being discussed large.
- Open items from the first summary, still unanswered: Drive trash list «что удаляю» for old duplicates (unclear whether it was sent), `catalog_82.csv` duplicate count (path unknown), the Баженов reminder, the «МИРАЖ-41» vs «ОБСИДИАН-73» table (contents unknown), V-101 questions. I have no evidence these were done.

## NUMBERS
- Pass-1 lengths 29,4 / 27,7 / 29,6 / 26,8 / 29,9 с; ASR 89/100/94/92/95%; end card ~3.5 s; safe zone x 120–960, y 250–1520; text ≥48 px (r4); ≥2,5 с per text picture; commit b1d421d3; delivery f12df25f.

## PEOPLE AND AGENTS
- `katya-work-orchestrator` / `orchestra` (task giver, only line to Katya; sends via mcp__orchestra__send_message); Katya (customer, owner of rules 42–43); video-platforma (V-202 owns «Винегрет», «Цыган на цыпочках»); this agent = session `rilsy`.
