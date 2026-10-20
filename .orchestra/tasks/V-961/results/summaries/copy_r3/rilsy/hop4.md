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
- Durable standing rules from the user (15 rules). VERBATIM:
  - Summary of the same:
  - Every final report starts with a separate line «СТАТУС ЗЕНИТ-42».
  - The recommended option is marked «ФЛОКС-76» at the start of its line.
  - New branches are named `vq8/<task number>/<short>`.
  - External wait ≤613 s.
  - ≤180k tokens per check.
  - Continue `/srv/work/draft-9226.md`.
  - Export chunk is exactly 2852 records.
  - Backups only to `backup/wl766`.
  - Do not touch `/srv/stage_20`.
  - Reference QX-7642 in commits.
  - No rollback on alpha-8 without asking.
  - Nothing to #prod-91 without a direct «да».
  - The Баженов reminder, the `catalog_82.csv` check and the МИРАЖ-41/ОБСИДИАН-73 table, as listed in the pending items above.
  - No evidence yet that «СТАТУС ЗЕНИТ-42», QX-7642 in commits or «ФЛОКС-76» were applied. Apply them from now on.
- Task rules (CLAUDE.md / AGENTS.md items 42, 43, 43а):
  - The board or slide is large and readable, with Katya's face as a small window in the corner. Zoom only by meaning. Cuts on word boundaries. Pauses and «э-э» cut. No frozen face window.
  - Subtitles word by word, the spoken word highlighted, smooth, centred, in Ruslan-like decorative Cyrillic, pink and brown.
  - Text stays in the Reels safe zone (x 120–960, y 250–1520 on 1080×1920).
  - Palette 732117 / 3D2B1F / FCF9DC, at most three colours. Each reel has its own design. Titles in Ruslan Display.
  - Hook in the first 3 s. A picture with text stays ≥2.5 s. No empty dark or burgundy backgrounds.
  - Gift end card with text exactly centred: «Забирай подарок в телеграм-канале. Там 23 аргумента для итогового сочинения» and @iskra_rus_lit.
  - Any rule shown in a reel is checked against the ФИПИ materials, not from memory.
  - Student voices are allowed. No names and no faces of children, including cursor name tags on the board.
- Process rules:
  - Nothing is published or sent to Katya or students. Reporting goes only to the orchestrator.
  - Work files go in `artifacts/`, not `/tmp`.
  - Commit messages start «#V-222:» (the current task number).
  - The server recordings are read-only.
  - Transcription is Deepgram only.
  - No bare `git stash`. Bash calls under 120 s. Don't restart Orchestra.
  - On Drive a new version is a PATCH under the old ID. Duplicates go to the trash only after sending a «что удаляю» list.
  - The tool name `Bash` is capitalised.
Katya's earlier verbatim wishes: «Некрасивый шрифт и появляется резко все»; «Такой и такие же цвета розовый и коричневый такой»; «делай в моём стиле, но можно делать разные дизайны, формы, шрифты»; «Старые рилсы удаляй, старые версии» (Drive: PATCH under old ID, trash only after a «что удаляю» list name+ID). Katya dislikes the «ПИВА» rule (not hers) — never use it. Katya forbade a «тупо тёмный фон». Orchestrator V-193 #720086: board text line height ≈70–90 px in 1080×1920, empty background ≤15 % of height. V-173 (#662915): «Кате ничего не отправлять».
The last message (#743306) is the final one; the journal ends right after it with no pass-2 work started.
Raw transcript: `/api/sessions/rilsy/logs?scope=/home/kesha/katya-work`.
Earlier messages (Katya's V-101 quotes, orchestrator #578323 through #607097, the 15 standing rules) are verbatim in the previous summary at the top of the transcript. They are carried unchanged. Messages since then, in order:
1. [#662915, 14.10] orchestrator, V-173: «#V-173, срочно: урок Маши сегодня 17:00 Красноярск = 10:00 UTC. Срок: файлы на Диске до 08:30 UTC. Катя 12:31 дословно: «просто вырежи мне фрагменты из видосов я их прикреплю может или если они большие то лучше указать время в видео». Она вставит их на доску Meleto сама. Видео: https://youtu.be/sHTARGBrqGE («Недоросль», Малый театр 1987…). Фрагменты: 1) д. III явл. VII «Не хочу учиться, хочу жениться»: 1:05:31–1:06:04; 2) д. IV явл. VIII экзамен «Дверь… прилагательна»: 1:42:36–1:44:06; 3) финал «Вот злонравия достойные плоды!»: 2:14:20–2:15:07. … Положить: Диск, папка «Маша 14.10 — Недоросль, доска Meleto» (id 1DRpRxJ6SAnzmipgavIOOXG2zlGKAfyOd) → новая подпапка «видео»… В репо видео не класть (gitignore)… На сервере 89.23.102.244 после работы удалить скачанные файлы из /root/v171 (и audio.m4a от V-171 тоже). Отчёт .orchestra/tasks/V-173/report.md, коммит, DONE мне. Кате ничего не отправлять.» (middle part shortened with «…»)
2. [#705039, 15.10] orchestrator, V-193: the task of 3–5 reels from the 15.10 lessons. Katya 22:24: «А теперь нарежь, ээ, рилсы сделает уже прикольные из видосов, которые я на платформе уже сегодня записывала.» Sources on SeedonRuInfra `/opt/urok/data/rec/` (read-only). Rules 42–43. Minors: no student cameras, no names. Deadline end of 16.10. (Shortened.)
3. [#716926, 17.10] orchestrator: «твой ход оборвался на просмотре кадров … Продолжи с того места, где остановился … Срок — сегодня до 20:00 Красноярск.» Plus [#716940] «Update your checklist: mark what is done and which step is current.»
4. [#718536] orchestrator, V-193: the contact sheet is defective under items 42–43. Five points: the board is too small, subtitles are too small, the cursor tag must be removed, remove «угу» in reel 3 (or say honestly that it is weak, then 4 reels), waveform and re-transcription check. Replace files on Drive under the same IDs. Attach a new sheet at one frame per second.
5. [#719871] orchestrator: «ход снова оборвал перезапуск Orchestra. Продолжай проход по 5 рилсам … Готовые рилсы коммить по одному сразу…»
6. [#720086] orchestrator: «Нижняя половина кадра по-прежнему пустая бордовая … Кате так не отдаём. Ещё проход по 4 рилсам»: text height about 70–90 px, empty background ≤15 % of the height, the card enlarged with its marks, and the source resolution reported if pixels are insufficient. One sheet per reel, one frame per second. (Shortened.)
7. [#742560, 18.10] orchestrator, V-222: «рилсы из уже имеющихся записей уроков Кати. Катя дословно (18.10, 09:06): «Ты мне рилсов каких-то наделай из того что есть интересных». 3–5 новых рилсов ≤30 с … ориентир V-220 … не дублировать «Винегрет», «Цыган на цыпочках» (V-202) и 4 рилса V-193 … Требования Кати (AGENTS.md п. 42, 43, 43а) … в конце карточка-подарок … @iskra_rus_lit … Проверка перед DONE: лист кадров по 1 кадру/с и последний кадр каждого рилса; повторная расшифровка. Положи на её Диск … подпапка «Рилсы 18.10»… В DONE: таблица (название, длительность, откуда момент, ID на Диске) + пути к листам кадров. Модель тебе переключена на Opus.» (Shortened.)
8. [#743306] orchestrator, V-222: «я посмотрел листы всех пяти рилсов. Моменты выбраны хорошо, но в таком виде Кате отдавать нельзя: по п. 42 главное в кадре — слайд, крупно и читаемо, ничего не налезает. Нужен второй проход с правками ниже. Общее для всех: плашка заголовка не должна закрывать слайд или доску. Сделай её меньше, подними выше или убери после 3 с, когда крючок уже прочитан. Ни одно слово на слайде не должно обрезаться краем кадра; если строка шире кадра, наезжай на её половину, о которой говорят, но слова целиком.» Then the per-reel items r1–r5 as summarized under TASK STATE. «Проверка та же: лист кадров 1/с — смотри каждый кадр на обрезанные слова, перекрытия и пустоту. Повторная расшифровка, замена на Диске под теми же ID. В DONE — пути к новым листам.»

## TASK STATE
- Objective: reels for `katya-work-orchestrator` (relays Katya, the end client). Worktree `/home/kesha/orchestra/worktrees/home-kesha-katya-work/rilsy`. The branch name changes per task: it was `task-V-193/rilsy`, then `task-V-222/rilsy`.
- **Current task: V-222**, second pass ordered by the orchestrator after it reviewed the contact sheets of all 5 reels. No evidence yet that the second pass has started.
  - Pass 1 was delivered. Commit b1d421d3, DONE sent (delivery f12df25f). Drive folder «Рилсы 18.10» has id `1FP8i46XxVJPk9q1AUoLoA52CDqRhozo-`, with 5 mp4 and 5 txt descriptions. Drive file IDs of the mp4 (replace via PATCH under these IDs): r1 `1ms9wPD9cvLfaO1ukK6bVEKTzANhz75IT`, r2 `1riMJbc7p9kdM9Yqw7GaPw2He49ghljXT`, r3 `1I1Urnvz6sSnLdwyT6c9Yae1syE38bIVe`, r4 `1n095kWpbNHJs2JhrAaxDCOmp62nVPqUp`, r5 `1HI2C6I6VROqn4SHInnGQg1gHgEGXCS5p`. Txt IDs seen: r1 `1TJvq5ueINLUWADTU37_QPJiFByNf4xjL`, r5 `17RXt6Px3ireISW4a4s8BS2AEh5YOyZyL` (others UNKNOWN; list from Drive). Sources: r1/r2 Zoom 28.09 (33:34 / 15:39), r3 Zoom 03.10 13:30, r4 итоговое 1:1 26:46–37:21, r5 own room 15.10 Маши 29:29.
  - Reels: r1 «Ах! Ура! Мяу!» (междометие, lesson1 ~2010–2030 s), r2 «Благодаря репетитору» (lesson1 ~935–1000 s), r3 «Отчаянный / доп. курсы» (v1678), r4 «Свеча горела» (v1678), r5 «Брат с сестрой и пульт» (V-193 recording rb273e81a6a4a, ~1769–1827 s).
  - Lengths in pass 1: 29.4, 27.7, 29.6, 26.8, 29.9 s. ASR match: r1 89 %, r2 100 %, r3 94 %, r4 92 %, r5 95 %. Safe zone «В ЗОНЕ» for all.
- Second-pass requirements (orchestrator, verbatim list below under messages):
  - General: the title plate must not cover the slide. Make it smaller, move it higher, or remove it after 3 s. No word on a slide may be cut by the frame edge. If a line is wider than the frame, zoom on the half being spoken, with whole words.
  - r1: no empty dark background. Show the «Междометие» slide with its character large from the start. Cats larger, on top of the slide. No empty frames, for example at 5 s and 14 s.
  - r2: the whole table visible (it was cut on the left). Plate must not cover the header. The handwritten line «благодаря репетитору» shown large (11–14 s).
  - r3: table was cut on the right. Plate covers the header. Keep the «отчаянный» row whole (word and answer) and zoom on it. Fix 5–7 s and 23–26 s.
  - r4: zoom on the topic line being named, at ≥48 px. At 6–9 s the document has flipped to «Гамлет». Cut that or cover it with a meme.
  - r5: plate covered the «В школе отменили физкультуру» card at 0–7 s. Show cards 3 and 4 whole side by side. Fix the cut «СРЕДИ НАС ШПИОН».
  - Check: contact sheet at 1 frame/s, inspect every frame, re-transcribe, replace on Drive under the same IDs, give paths to the new sheets in DONE.
- Earlier tasks, all reported DONE:
  - V-107: sets 1 and 2, commit 502fa9a.
  - V-173: 3 «Недоросль» clips on Drive in the «видео» folder, id `1Ss2uVVqwYfQpRon0qqplBNRXCQP5UtM4`. Commit edb8ccb. DONE sent as ddaee18e. The server `/root/v171` cleanup was in the order. Whether it was done is not confirmed in the evidence.
  - V-193: 4 reels from Masha's lesson of 15.10, pass 3 commit dddac667, Drive folder `1Sid7qur9hO3ROeEq3H4al7khvMgjVukI`. Reel 3 was dropped as weak. Drive file IDs: `11EO-r-tI49Jq7sf1kGVAzBUaQQlkMeJT`, `1Exxe83ggJy54u54DiOgzimJXBv4xRVzu`, `11zHw4zinyHZmbbHaSWNibQ5zY41i7y3j`, `17DWryHrZhNxIrZr0-UR9NRxGfjyZeB4n`.

## DECISIONS
- Reuse the V-193 engine copied into `artifacts/V-222/`. Layout "F" is the full-frame board, with face window, big Ruslan Display subtitles and a gift end card.
- Cuts follow real silences. Re-transcription uses Deepgram nova-3.
- Names and faces of children never appear in the frame. Student labels are «ученица:».
- V-222 pass 1 added memes (cats, grumpy, etc. in `artifacts/V-222/memes/`), a gift end card (`endcard.py`) and the `@iskra_rus_lit` text.
- Weak candidates are dropped and the orchestrator is told honestly.
- Unresolved: the Co-Authored-By trailer. The global CLAUDE.md forbids it, so it is not added.
- Unresolved: whether the Drive «что удаляю» list for old duplicates was ever sent.

## FILES AND ARTIFACTS
- `artifacts/V-222/` (committed in b1d421d3; large outputs are gitignored):
  - Scripts and specs: `spec.py`, `prep.py`, `build_reel2.py`, `themes.py`, `cutter.py`, `endcard.py`, `desc.py`, `finish.sh`, `run.sh`, `reels3.json`, `lessons3.json`, `words/`, `tr/`, `pitch.py`, `contact1.py`, `check_safe.py`, `verify_asr.py`, `transcribe_file.py`, `memes/`.
  - Gitignored: `clips/`, `out/`, `work/`. The sheets are `work/sheet-r1..r5.jpg` and the last frames are `work/last-*.jpg`. Sheets `sheet-r1..r5.jpg` and `last-r1..r5.jpg` ARE also committed in `.orchestra/tasks/V-222/` (b1d421d3); the pass-1 DONE named those paths, so pass 2 should overwrite them there and cite them.
- `.orchestra/tasks/V-222/report.md` was written and committed.
- Source recordings, all read-only:
  - `artifacts/task-V-94/lesson1..3/lesson.mp4` (keep).
  - `artifacts/task-V-107/src/video1678220992.mp4` (154 MB, gitignored).
  - `artifacts/V-193/rb273e81a6a4a.mp4`.
  - The server copies on 89.23.102.244 `/opt/urok/data/rec/` are not to be touched.
- Drive uploads use `/home/kesha/katya-drive/bin/rclone --config /home/kesha/katya-drive/rclone.conf` with remote `iskra:`. Replacing files under the same ID went through `/home/kesha/katya-work/artifacts/V-45/gpatch.sh`.

## COMMANDS AND TOOL OUTCOMES
- Render, safe-zone check, ASR check and sheet in one go: `./finish.sh <id>` from `artifacts/V-222`. Run long jobs via `mcp__orchestra__bg_create`, because a Bash call over 120 s is backgrounded.
- Any `ssh kesha@localhost` command must start with `choom -n 1000 --`. A PreToolUse hook rejected the form without it.
- `build_reel2.py` needs numpy, which is only on `kesha@localhost`. Delete `work/body-<id>.mp4` before re-rendering, because it is cached.
- A render of r4 once failed with ffmpeg exit 183 / signal. After a filtergraph fix `[0:v]` → `[0:v:0]` (the fix described in the log), r4 rendered.
- A job interrupted by an Orchestra restart is not rerun automatically. After a restart, check the files first.
- `cutter.py` `dip()` raises «нет границы слов» in fluent speech. The workaround is an explicit `start=` in `spec.py`.
- Known ASR artifacts: r1 «междуметее» and «дос конца» in the check, which is a mishearing of the original.

## BLOCKER / NEXT
- Blocker: none known.
- Next action: start pass 2 of V-222 in this order.
  1. Edit shots and layout in `spec.py` and `themes.py`: title plate smaller or removed after 3 s, and zoom windows that keep whole words.
  2. Re-render r1–r5 with `finish.sh`.
  3. Inspect every frame of the 1 fps sheets for cut words, overlap and emptiness.
  4. Re-transcribe.
  5. Replace the files on Drive under the same IDs.
  6. Commit.
  7. Send DONE with the paths to the new sheets.
- Commit each ready reel immediately, since restarts interrupt the work.
- Pending owner items:
  - Check `catalog_82.csv` for duplicates and report the count. Path UNKNOWN — source gap.
  - Remind about asking Игорь Баженов for the deadline on «согласование тарифа» before the end of the week.
  - Include the short «МИРАЖ-41» vs «ОБСИДИАН-73» table in the final message. Contents UNKNOWN — source gap.
  - V-101 questions (four-pointed stars, `wedding_R.mp4`) remain open.
