## TASK STATE
- **Current task: #V-222** (reels from existing lesson recordings), reporting line `katya-work-orchestrator` only. Branch `task-V-222/rilsy`.
- **Phase:** second pass requested. I delivered 5 reels as DONE (commit b1d421d3, delivery_id=f12df25f-b051-440c-a95c-03376929b208), and the orchestrator rejected them for layout. No evidence yet of any work on the second-pass fixes.
- **Earlier tasks, closed:**
  - V-107: HEAD 502fa9a.
  - V-173: 3 *Nedorosl* clips on Drive.
  - V-193: 4 reels, final DONE at commit dddac667.
- **V-222 deliverable as of b1d421d3:** Drive folder «Рилсы 18.10», id `1FP8i46XxVJPk9q1AUoLoA52CDqRhozo-`.
  - The 5 mp4 files and their description txt files are in that folder (txt IDs UNKNOWN). mp4 Drive IDs (replace under the SAME IDs, via PATCH):
    - r1 «Ах! Ура! Мяу! Какая это часть речи?» (Zoom 28.09, 33:34): `1ms9wPD9cvLfaO1ukK6bVEKTzANhz75IT`
    - r2 «Благодаря репетитору я сдал экзамены» (Zoom 28.09, 15:39): `1riMJbc7p9kdM9Yqw7GaPw2He49ghljXT`
    - r3 «Ученик предложил учителю доп. курсы» (Zoom 03.10, 13:30): `1I1Urnvz6sSnLdwyT6c9Yae1syE38bIVe`
    - r4 «Один рассказ — на все темы итогового» (Итоговое 1:1, 26:46–37:21, «Свеча горела»): `1n095kWpbNHJs2JhrAaxDCOmp62nVPqUp`
    - r5 «Брат с сестрой поссорились из-за пульта» (own room 15.10, Маша, 29:29): `1HI2C6I6VROqn4SHInnGQg1gHgEGXCS5p`
  - Sheets/last frames in repo: `.orchestra/tasks/V-222/sheet-r1..r5.jpg`, `last-r1..r5.jpg`; report `.orchestra/tasks/V-222/report.md`. Done in v1: names «Ярик», «Злата», «Влад» cut from audio and subtitles; end card 2.6 s; cursor-name tag in Маша's room erased with background; face window hidden while a student without camera speaks. Not used: 2023 children's voices (no consent), lesson 12 (monologue), group 15.10 (quiet, names audible). Rules checked vs МР ФИПИ-2025 (p.24 «отчаянный», p.26–30). Not listened by ear in v1 (only waveform/ASR) — do listen in v2 if possible.
  - Durations 29.4 / 27.7 / 29.6 / 26.8 / 29.9 s. Safe zone «В ЗОНЕ» for all (x 124–959, y 255–1520). Re-transcription match: r1 89%, r2 100%, r3 94%, r4 92%, r5 95%.
- **Checklist:** last known state 2 of 5 steps complete. It was not updated after the DONE.

## NUMBERS
- See durations/ASR match in TASK STATE; end card 2.6 s; V-222 mp4 safe zone x 124–959, y 255–1520; V-193 commit dddac667; V-222 commits e4974938, b1d421d3.

## DECISIONS
- Engine reused from V-193 (layout F, full-frame board, Ruslan Display subtitles) and copied into `artifacts/V-222/`.
- Memes are cut-out cats, put over the board.
- A gift end card was added to each reel: «Забирай подарок в телеграм-канале. Там 23 аргумента для итогового сочинения» plus @iskra_rus_lit.
- Student voices are labelled «ученик:» or «ученица:»; no names.
- The Deepgram nova-3 word timings in `words/n3abs-*` drive the cuts. `cutter.py` `dip()` was patched to fall back instead of raising.
- The orchestrator's moment selection is accepted ("Моменты выбраны хорошо"). The problem is layout, not the choice of moments.

## FILES, IDS AND ARTIFACTS
Worktree: `/home/kesha/orchestra/worktrees/home-kesha-katya-work/rilsy`, base `artifacts/V-222/`.
- **Committed (e4974938, then b1d421d3):** `spec.py`, `prep.py`, `build_reel2.py`, `cutter.py`, `themes.py`, `endcard.py`, `desc.py`, `finish.sh`, `run.sh`, `reels3.json`, `lessons3.json`, `words/`, `tr/`.
- **Also committed in b1d421d3:** `.orchestra/tasks/V-222/report.md` and the contact sheets.
- **Gitignored:** `artifacts/V-222/clips/`, `out/`, `work/`, `__pycache__/`.
- **Contact sheets, 1 frame/s:** `work/sheet-r1..r5.jpg`. Final frames are `work/last-*.jpg`.
- **Memes:** `artifacts/V-222/memes/`, drawn from V-203, V-194 and V-180 assets.
- **Sources:**
  - `artifacts/task-V-94/lesson1..3/lesson.mp4`.
  - `artifacts/task-V-107/src/video1678220992.mp4`.
  - `artifacts/V-193/rb273e81a6a4a.mp4`.
  - Words files in `artifacts/task-V-107/words/`.
- The `/api/sessions/rilsy/logs` link is below.

## COMMANDS AND TOOL OUTCOMES
- Render: `./finish.sh rN` runs `build_reel2.py reels3.json --only rN` over ssh `kesha@localhost`, then `check_safe.py`, `verify_asr.py` and `contact1.py`.
- **Policy hook:** commands run as `kesha@localhost` must start with `choom -n 1000 --`. Example: `ssh -o BatchMode=yes kesha@localhost "choom -n 1000 -- bash -c 'cd $PWD && ...'"`.
- **Rendering notes:**
  - Bash calls stay under 120 s, so render in the background through `bg_create`.
  - To force a rebuild, delete `work/body-rN.mp4`.
  - Render failures seen: ffmpeg died with exit status 183 on r4 (fixed in `build_reel2.py`); an earlier `endcard.py` run hit `AssertionError: не влезает: Забирай подарок` on r2.
- **Drive:** rclone at `/home/kesha/katya-drive/bin/rclone --config /home/kesha/katya-drive/rclone.conf`. The previous reel pass was replaced via `/home/kesha/katya-work/artifacts/V-45/gpatch.sh`.

## PEOPLE AND AGENTS
- `katya-work-orchestrator` (task giver, only reporting line); Katya (client, publishes herself); video-platforma (V-202, redoing «Винегрет»/«Цыган на цыпочках»); Igor Bazhenov (deadline «согласование тарифа»). Agent: rilsy.

## OPEN ITEMS AND NEXT ACTION
- **Blocker:** none, the orchestrator is waiting on the second pass. Last journal event is the orchestrator's second-pass message; no second-pass work had been started. Pre-DONE v1 log: render job "V-222: r1 r4 r5 пересобраны" etc. all completed.
- **Next action:** start with r1, which has the most severe defects. Look at `work/sheet-r1.jpg`, then fix the layout in `spec.py` and `themes.py` and re-render with `./finish.sh r1`.
- **Fixes the orchestrator asked for:**
  - **All reels:** the title plate must not cover the slide. Make it smaller, move it higher, or drop it after 3 s. No word on a slide may be clipped by the frame edge.
  - **r1:** no empty dark background and no frames without a cat or subtitle. Show the «Междометие» slide with the character large from the start, with bigger cats lying on top.
  - **r2:** show the table whole, with the handwritten «благодаря репетитору» line large, and fix the small, clipped slide at 11–14 s.
  - **r3:** keep the «отчаянный» row whole (word and answer) and zoom on it. The plate must not cover «Повторение: какая часть речи». Fix the table cut at the right edge and the half-cell frames at 5–7 s and 23–26 s.
  - **r4:** zoom on the topic line being named, at ≥48 px. Cut or cover the «Гамлет» page at 6–9 s with a meme.
  - **r5:** the plate must not cover the «В школе отменили физкультуру» card at 0–7 s. Show cards 3 and 4 whole side by side, with no clipped «СРЕДИ НАС ШПИОН», and show the subject of the speech large.
- **Then:** check each 1 fps sheet frame by frame, re-transcribe and compare, and replace the files on Drive under the same IDs. Commit each finished reel straight away (a restart may interrupt the session). Send DONE with the new sheet paths.
- **Owed to the user, still open:**
  - Check `catalog_82.csv` for duplicates and report the count (path UNKNOWN).
  - Remind the user to ask Igor Bazhenov about the «согласование тарифа» deadline.
  - Include the «МИРАЖ-41» vs «ОБСИДИАН-73» comparison table in the final message (variant content UNKNOWN).

## CONSTRAINTS AND BANS
- **Durable user rules:** the 15 verbatim standing rules in the USER REQUIREMENTS section below remain in force (status line «СТАТУС ЗЕНИТ-42», «ФЛОКС-76» marker, branches `vq8/<номер>/<коротко>` for new ones, QX-7642 in commits, etc.).
- **Project rules:**
  - Nothing is published or sent to Katya or students.
  - Video and sources over 50 MB stay out of git.
  - Commit messages start «#V-222:».
  - No names or faces of students.
  - Anything stated as a rule must be checked against the FIPI documents.
  - Don't restart Orchestra.
  - No bare `git stash`.
  - Hook-visible and system updates may arrive mid-task.
- **Unresolved:** a Co-Authored-By trailer is requested by one reminder but forbidden by global CLAUDE.md. No commits carry one.
- **Pronouns:** they/them unless stated.

## OWNER & USER REQUIREMENTS (verbatim)
Raw transcript: `/api/sessions/rilsy/logs?scope=/home/kesha/katya-work`.

**1. Standing rules from the user (carried in the first summary):**
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

**2. Task messages from `katya-work-orchestrator`, in arrival order.**

V-107 rules (earlier handoff, exact text unavailable): cuts on word boundaries, no pauses >0.4 s; student voices OK, caption «ученица:»/«ученик:», no names; Drive: new version = PATCH under old ID, send «что удаляю» (name, ID) list BEFORE deleting on Drive; lesson1..3 NEVER deleted; own design per reel; do not use «ПИВА».

**Earlier tasks (closed; essentials only):**
- V-173 (14.10): cut 3 *Nedorosl* clips, Drive folder «Маша 14.10 — Недоросль, доска Meleto» (id 1DRpRxJ6SAnzmipgavIOOXG2zlGKAfyOd) → «видео». Rules kept: «Кате ничего не отправлять»; videos not in repo; srv `root@89.23.102.244` (SeedonRuInfra) — touch nothing foreign, delete own downloads.
- V-193 (15–17.10): reels from lesson recordings in /opt/urok/data/rec/ on SeedonRuInfra: «Записи только скачивай. На сервере ничего не удаляй и не меняй: это единственные копии её уроков.» Rules п. 42–43: board/slide large and readable (text ≥ subtitle size, ~70–90 px line in 1080×1920), face as small corner window, no empty background >15% of frame, word-by-word subtitles centered with highlighted word, safe zone (not top ~14%, not bottom ~20%, not right edge), each reel own design, Ruslan Display titles, palette 732117/3D2B1F/FCF9DC, cuts on silence + re-transcription check (Deepgram only), «Ничего не публиковать и никому не отправлять, публикует только Катя.», students minors: no faces, no names in subtitles/captions (cut/mute spoken names), voices OK. Orchestrator also required: «Готовые рилсы коммить по одному сразу, чтобы следующий перезапуск ничего не съел.» KB: .orchestra/kb/rilsy-nareznya-zoom.md.

**V-222 (18.10 02:10):**
«#V-222: рилсы из уже имеющихся записей уроков Кати.

Катя дословно (18.10, 09:06): «Ты мне рилсов каких-то наделай из того что есть интересных».

Результат: 3–5 новых рилсов ≤30 с из записей, которые у нас уже есть (Zoom-записи в artifacts прошлых задач, своя комната /opt/urok/data/rec/ на SeedonRuInfra — только читать, твои V-193; ищи по всем, не только по 15.10). Выбирай самые живые моменты, а не «кусок объяснения». Ориентир того, что залетает, — исследование V-220 (.orchestra/tasks/V-220/report.md, раздел 4 и выводы): ученик угадывает / ошибается смешно, живой диалог с панчлайном, загадка с ответом, «учитель против…». Эталон — «Винегрет — в вине» (п. 42): законченная мысль от вопроса до панчлайна, юмор, запоминалка.

Не дублировать: «Винегрет» и «Цыган на цыпочках» сейчас переделывает video-platforma (V-202), а твои 4 рилса V-193 («Ну, сдайся!», «Шарики…», «Спать — это отдых», «Мне — не подлежащее») уже есть — новые моменты, не они.

Требования Кати (AGENTS.md — читай целиком п. 42, 43, 43а; главное): склейки точно по словам, паузы и «э-э» вырезаны, окно лица не зависает; главное в кадре — слайд/доска крупно и читаемо, её лицо маленьким окном; наезд по смыслу; текст в безопасной зоне Reels; субтитры пословные, звучащее слово выделено, плавно, по центру, её образец шрифта/цветов; рилсы разные по оформлению; крючок в первые 3 секунды; динамика — смена плана 1–3 с, мемы/картинки к словам, НО каждый план держится столько, чтобы его успели прочитать (её 08:54 про «Винегрет»: «слишком быстро всё мелькает, ничего не понятно» → ≥2,5 с на картинку с текстом); пустых тёмных/бордовых фонов нет; в конце — карточка-подарок «Забирай подарок в телеграм-канале. Там 23 аргумента для итогового сочинения» и @iskra_rus_lit (адрес новый!), текст ровно по центру, не прилипает к краю. Голоса учеников можно, имён и лиц учеников нет. Всё по русскому/литературе — сверено с МР ФИПИ/навигатором (если в рилсе правило — проверь его по документу, не по памяти). Опиши каждый рилс текстом с хештегами для копирования.

Проверка перед DONE: лист кадров по 1 кадру/с и последний кадр каждого рилса — посмотри сам; повторная расшифровка — нет обрубленных слов. Положи на её Диск в папку рилсов (новая подпапка «Рилсы 18.10»), ничего не публикуй, ученикам не отправляй. В DONE: таблица (название, длительность, откуда момент, ID на Диске) + пути к листам кадров. Модель тебе переключена на Opus.»

**V-222 (18.10, latest, after the first DONE):**
«Current #V-222: я посмотрел листы всех пяти рилсов. Моменты выбраны хорошо, но в таком виде Кате отдавать нельзя: по п. 42 главное в кадре — слайд, крупно и читаемо, ничего не налезает. Нужен второй проход с правками ниже.

Общее для всех: плашка заголовка не должна закрывать слайд или доску. Сделай её меньше, подними выше или убери после 3 с, когда крючок уже прочитан. Ни одно слово на слайде не должно обрезаться краем кадра; если строка шире кадра, наезжай на её половину, о которой говорят, но слова целиком.

r1 «Ах! Ура! Мяу!»: почти весь кадр — пустой тёмный фон с маленьким котом, а Катя прямо запретила «тупо тёмный фон». Полоска слайда сверху обрезана слева («ерсонажа»). На 5 и 14 с в кадре нет ни кота, ни субтитра. Сделай её слайд «Междометие» с персонажем крупно (с 17 с он уже есть) и держи его с самого начала, а коты пусть будут крупнее и лежат поверх слайда. Пустых кадров быть не должно.
r2 «Благодаря репетитору»: таблица слайда обрезана слева («епри», «ала»), плашка закрывает шапку. На 11–14 с слайд мелкий и тоже обрезан. Нужна таблица целиком и рукописная строка «благодаря репетитору» крупно.
r3 «Доп. курсы»: таблица обрезана справа («части / не вв»), плашка закрывает «Повторение: какая часть речи». На 5–7 и 23–26 с кадр стоит на середине таблицы, видны обрывки ячеек. Держи в кадре строку «отчаянный» целиком (слово и ответ) и наезжай на неё.
r4 «Свеча горела»: текст документа мелкий. Наезжай на строку темы, которую сейчас называют, крупно (≥48 px). На 6–9 с документ перелистнут на «Гамлета»: вырежи это или закрой мемом.
r5 «Брат с сестрой»: на 0–7 с плашка закрывает карточку «В школе отменили физкультуру». Края карточек 3/4 обрезаны, «СРЕДИ НАС ШПИОН» снизу срезан. Покажи карточки 3 и 4 целиком рядом, а то, о чём говорят, — крупно.

Проверка та же: лист кадров 1/с — смотри каждый кадр на обрезанные слова, перекрытия и пустоту. Повторная расшифровка, замена на Диске под теми же ID. В DONE — пути к новым листам.»