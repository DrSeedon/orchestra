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

## TASK STATE
- Objective: V-107 for `katya-work-orchestrator` (relays Katya, the end client), on branch `task-V-107/rilsy`, worktree `/home/kesha/orchestra/worktrees/home-kesha-katya-work/rilsy`.
- Katya's latest request (08.10 20:53): «Сделай другие рилсы интересные». The reference is «Винегрет» (item 42 together with item 43). The brief was ≤30 s, a live dialogue with a student, humour or a mnemonic, and a finished thought.
- Set 1 (07.10) is done and delivered. The orchestrator was sent 4 finished reels from v1678 and the 12th-task recording. They are on Drive in «01_ИСКРА — школа и работа/Рилсы/Новые (из других записей)» with a `.txt` description each. Reel IDs include №1 `1Sj1Rqo23a0Xf-Zvn_GoGUC1cUDO73DPG` and №2 `1L3MxV1cjd6AhDNFgWXY4inowBrTlp4d2`. The report is DONE, delivery 48b690b4.
- Set 2 (08.10) is done and reported (delivery 2eed961c). It has 3 new reels from lesson1–3, plus the 4 from set 1:
  - «Новые 6. Лаг–лож — моё любимое»: Drive ID `1Gh5pgh5Wv-pkwRR12wJL3I7EemwlbziS`.
  - «Новые 7. По-моему и по моему совету»: Drive ID `1TwGcA_lpVU5osDDPvkXKWr_Yrt6neiyK`.
  - «Новые 8. Чтобы — союз или местоимение»: Drive ID `1JWoUQtJsqR13WbTYjgD_kTGMig5bHTp1`.
  - Safe-zone check «В ЗОНЕ» for m2, m3 and m4. Re-transcription match reported to the orchestrator as 88/90/86 % (m2/m3/m4; an earlier m3 render gave 63%, an ASR artifact). m1 «Метод пристального взгляда» was dropped (Katya has no camera in that lesson, face window empty). Also dropped: «Привилегия», «день самоуправления» (children's names), «растаяла/Ой-ой». Set-2 lengths 19/26/27 s (lessons 05.10, 03.10, 28.09). Report said first/last words were checked via transcript, not by ear.
- Last step: the orchestrator reported that the merge failed on a `.gitignore` conflict. I ran `git merge main`, kept both sides' lines and committed. HEAD is **502fa9a** (delivery 1ab1d064). `git status` was clean.
- No evidence the push succeeded. The orchestrator's last order (#607097): «Подтяни main в свою ветку (git merge main), разреши конфликт: сохрани строки обеих сторон, закоммить и пришли мне одну строку с новым HEAD. Больше ничего не трогай.» — done, one-line reply sent; do nothing more unless the orchestrator writes.

## DECISIONS
- Old 12 reels (V-94) are not touched (orchestrator, 07.10). Orchestrator order #581276 (earlier): merge main, `git rm --cached` the three big src mp4s (files on disk NOT deleted), never put video/sources >50 MB in git (GitHub limit 100 MB).
- Cuts follow real silences in the Zoom audio, not Deepgram boundaries.
- Each reel gets its own theme: Ruslan Display titles, Iskra palette, readable Montserrat subtitles.
- Student voices are allowed, with no names or faces of children. Subtitles for the student's lines are labelled «ученик:».
- Weak candidates were skipped. For the 08.10 set, 3 were selected instead of 3–5.
- `.gitignore` now ignores `artifacts/task-V-107/src/*.mp4` and `artifacts/task-V-107/src/*.log`. The source mp4s stay on disk.
- Unresolved: whether the Drive trash list «что удаляю» for the old duplicates was ever sent. I could not tell from the evidence.
- Unresolved: the Co-Authored-By trailer. A system reminder asks for it and the global CLAUDE.md forbids it, so it is not added.

## FILES AND ARTIFACTS
All under `artifacts/task-V-107/` unless noted.
- **Committed code and specs:**
  - `build_reel2.py`: added `ege12cards` and `face_pad`.
  - `reels2.json`: specs for n1–n4 and m2–m4.
  - `themes.py`: themes m1–m4.
  - `words/lesson1.json` and `words/lesson2.json`: added to the repo.
  - `dump.py` and `wl.py`.
- **Commits** (all on `task-V-107/rilsy`):
  - 535f54a: the 4 set-1 reels.
  - bacb1eb: `.gitignore` for `src/*.log`.
  - 378239f: set 2.
  - 502fa9a: merge of main.
- **Local only, not in git:** `out/Новые 1..4*.mp4`, `out/Новые 6..8*.mp4` with `.txt` descriptions, `work/` (contact sheets, logs `r-*.log`), `src/*.mp4` (ege12 116 MB, video1678220992 154 MB, noun2023 93 MB). Whether `src/` held other untracked files is unknown.
- **Inputs:** `../task-V-94/lesson1..3/lesson.mp4` (keep), Drive `rclone` config in `/home/kesha/katya-drive/`.
- **Known risk:** the three large mp4s are still in earlier commits of the branch history, so a push may be rejected. The orchestrator was told a squash-merge is needed.
- **Environment note:** this session's cwd is another worktree (`.../research-cmu-course/...`) and not the rilsy worktree. The rilsy path above comes from the transcript.

## COMMANDS AND TOOL OUTCOMES
- Render and check one reel: `./finish.sh <id>` from `artifacts/task-V-107`. It runs the safe-zone check, the ASR check and the contact sheet. Long jobs go through `mcp__orchestra__bg_create` because of the 120 s Bash limit. The tool name must be `Bash`, capitalised.
- Upload to Drive: `rclone --config /home/kesha/katya-drive/rclone.conf` to `iskra:01_ИСКРА — школа и работа/Рилсы/Новые (из других записей)`.
- `git merge main` gave `CONFLICT (content): Merge conflict in .gitignore`. I removed the conflict markers with `sed`, committed, and HEAD became 502fa9a.
- Deepgram nova-2 vs nova-3 `heard.py` runs were used for the audio checks. For m3, the nova-3 text matched the plan much better than nova-2, so the 63% result was an ASR artifact.

## BLOCKER / NEXT
- Blocker: none known. Waiting on the orchestrator for:
  - confirmation that the push/merge works;
  - Katya's feedback on the set-2 reels;
  - her go-ahead to delete old duplicates on Drive;
  - feedback on `wedding_R.mp4` (V-101).
- Next action: read the orchestrator's reply. If the push is still rejected, the fix is rewriting history to drop the three large mp4s. That is hard to reverse, so confirm with the orchestrator first.
- Pending for the owner:
  - Check `catalog_82.csv` for duplicates and report the count (path UNKNOWN — source gap).
  - Remind them to ask Игорь Баженов about the deadline for «согласование тарифа» before the end of the week.
  - Promise and then include the short comparison table «МИРАЖ-41» vs «ОБСИДИАН-73» in the final message (contents UNKNOWN — source gap).
  - Answer the pending decorative four-pointed stars question (V-101).
