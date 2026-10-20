## TASK STATE
- **Current task: #V-222**, reels from existing lesson recordings, branch `task-V-222/rilsy`. Reporting line is `katya-work-orchestrator` only.
- **Status:**
  - Pass 1 is done and was sent as DONE: 5 reels, commit `b1d421d3`, git clean, Drive folder «Рилсы 18.10» (`1FP8i46XxVJPk9q1AUoLoA52CDqRhozo-`) with 5 mp4 + 5 description txt.
  - The orchestrator rejected pass 1 and asked for a **second pass** (list below). Work on it has **not started**: no evidence of any command run after that message.
- **Pass-2 requirements:**
  - **All reels:**
    - The title plate must not cover the slide or board. Make it smaller, move it higher, or remove it after 3 s.
    - No slide word may be cut by the frame edge. If a line is wider than the frame, zoom on the half being discussed, with whole words.
  - **r1 «Ах! Ура! Мяу!»:**
    - Almost the whole frame is empty dark background with a small cat, which Katya banned («тупо тёмный фон»).
    - The top slide strip is cut off on the left («ерсонажа»).
    - At 5 s and 14 s there is no cat and no subtitle.
    - Use the «Междометие» slide with the character large (it exists from 17 s), held from the start. Cats larger and on top of the slide. No empty frames.
  - **r2 «Благодаря репетитору»:**
    - The table is cut on the left («епри», «ала») and the plate covers the header.
    - At 11–14 s the slide is small and cut.
    - Needs the whole table and the handwritten line «благодаря репетитору» large.
  - **r3 «Доп. курсы»:**
    - The table is cut on the right («части / не вв») and the plate covers «Повторение: какая часть речи».
    - At 5–7 s and 23–26 s the frame sits mid-table showing cell fragments.
    - Keep the line «отчаянный» whole (word and answer) and zoom on it.
  - **r4 «Свеча горела»:**
    - Document text is small. Zoom on the topic line currently named, ≥48 px.
    - At 6–9 s the document has flipped to «Гамлет»: cut it or cover it with a meme.
  - **r5 «Брат с сестрой»:**
    - At 0–7 s the plate covers the card «В школе отменили физкультуру».
    - Edges of cards 3/4 are cut, and «СРЕДИ НАС ШПИОН» is cut at the bottom.
    - Show cards 3 and 4 whole side by side, and the thing being discussed large.
- **Checks and delivery:**
  - Contact sheet at 1 frame/s, inspecting each frame for cut words, overlaps and emptiness.
  - Re-transcription.
  - Replace the files on Drive under the same IDs.
  - DONE with paths to the new sheets.
- **Earlier tasks (this session), for context:**
  - V-173: DONE sent, 3 Nedorosl clips on Drive, «Маша 14.10…» → «видео» (`1Ss2uVVqwYfQpRon0qqplBNRXCQP5UtM4`).
  - V-193: 4 reels (p3 dropped as weak). Pass 3 DONE sent, commit `dddac667`. No reply seen.
  - V-107: waiting for the orchestrator.

## DECISIONS
- V-222 moments (spec in `artifacts/V-222/spec.py`):
  - r1: interjection (lesson1 ~2010–2030 s).
  - r2: «благодаря репетитору» (lesson1 ~935–990 s).
  - r3: «отчаянный» / extra courses.
  - r4: «Свеча горела» (v1678).
  - r5: brother and sister, remote control (Masha 15.10 recording, ~1769–1827 s).
- Layout "F" (full board, band under the subtitles), Ruslan Display subtitles, 3.5 s end card (gift, @iskra_rus_lit), memes `artifacts/V-222/memes/`.
- Student names are masked: the cursor label is painted over in `prep.py`. No student names or faces in frame.
- Don't duplicate «Винегрет», «Цыган на цыпочках» (V-202, other agent) or the four V-193 reels.
- The in-recording pan in r5 is Katya's own scrolling, judged acceptable.
- Open: the Co-Authored-By trailer conflict (system reminder vs global CLAUDE.md). No commits carry one.

## FILES AND ARTIFACTS
- Worktree: `/home/kesha/orchestra/worktrees/home-kesha-katya-work/rilsy`.
- `artifacts/V-222/`:
  - Engine: `build_reel2.py`, `cutter.py`, `themes.py`, `prep.py`, `endcard.py`, `finish.sh`, `run.sh`, `spec.py`, `desc.py`, `reels3.json`, `lessons3.json`, `verify_asr.py`, `check_safe.py`, `contact1.py`, `pitch.py`, `transcribe_file.py`, `dump.py`.
  - Data: `words/`, `tr/`, `memes/`.
  - Git-ignored: `clips/`, `out/`, `work/`.
- Committed `b1d421d3` (engine, spec, report `.orchestra/tasks/V-222/report.md`, contact sheets). Whether later edits were committed: no evidence.
- Sources:
  - `artifacts/task-V-94/lesson1..2/lesson.mp4`
  - `artifacts/task-V-107/src/video1678220992.mp4`
  - `artifacts/V-193/rb273e81a6a4a.mp4`
  - Words: `/home/kesha/katya-work/artifacts/task-V-107/words/*.json`
- Drive: folder «Рилсы 18.10» `1FP8i46XxVJPk9q1AUoLoA52CDqRhozo-` (parent «Рилсы» `1mWgLUeJRjT40FAFey7iiZ9Etsh9evwT1`, rclone remote `iskra:`, `--drive-root-folder-id`). File IDs (PATCH under these):
  - r1 mp4 `1ms9wPD9cvLfaO1ukK6bVEKTzANhz75IT`, txt `1TJvq5ueINLUWADTU37_QPJiFByNf4xjL`
  - r2 mp4 `1riMJbc7p9kdM9Yqw7GaPw2He49ghljXT`, txt `1av2QU1pBTBLgXpSawpNrEdA3RIks4hA5`
  - r3 mp4 `1I1Urnvz6sSnLdwyT6c9Yae1syE38bIVe`, txt `1_IdVZiUbdcN3a_BHQVoGTmSB6CmgZnAv`
  - r4 mp4 `1n095kWpbNHJs2JhrAaxDCOmp62nVPqUp`, txt `1Gl6yRsgDCxA7UbiOHn4a5Y4DU7rY2BnC`
  - r5 mp4 `1HI2C6I6VROqn4SHInnGQg1gHgEGXCS5p`, txt `17RXt6Px3ireISW4a4s8BS2AEh5YOyZyL`
  - Pass-1 durations: r1 29.4 s, r2 27.7 s, r3 29.6 s. Local out/ names «Рилсы 18.10 · N. …».
  - Sources: r1/r2 Zoom 28.09 (r1 at 33:34, r2 at 15:39), r3 Zoom 03.10 (13:30).
- Worktree git path also appears as `/home/kesha/orchestra/worktrees/home-kesha-katya-work/rilsy` (same worktree; scope /home/kesha/katya-work).
- DONE pass 1 delivery_id=f12df25f-b051-440c-a95c-03376929b208 (to katya-work-orchestrator).
- Report V-193 (`.orchestra/tasks/V-193/`) is committed; V-193 Drive IDs are in it.

## COMMANDS AND TOOL OUTCOMES
- Render: `./finish.sh r1 …` (render, `check_safe`, `verify_asr`, contact sheet `work/sheet-rN.jpg`); end card via `python3 endcard.py rN`.
- Last pass-1 check results:
  - Safe zone «В ЗОНЕ» for all.
  - ASR match: r1 89%, r2 100%, r3 94%, r4 92%, r5 95%.
  - Durations 26.8–29.9 s.
- Known errors:
  - `moov atom not found` on r4 came from ffmpeg `exit status 183` (the video-only/no-audio graph issue), later fixed.
  - `нет границы слов` in `cutter.py` was handled by the `dip` fallback.
  - `AssertionError: не влезает: Забирай подарок` appeared once in the r2 end card, later logged as added.
- Hook rule: any `ssh kesha@localhost` command must be `ssh -o BatchMode=yes kesha@localhost 'choom -n 1000 -- <command>'` (numpy exists only there).
- Bash calls under 120 s; long renders go through `mcp__orchestra__bg_create`.
- Drive: `/home/kesha/katya-drive/bin/rclone --config /home/kesha/katya-drive/rclone.conf`; replace via PATCH (`/home/kesha/katya-work/artifacts/V-45/gpatch.sh`) under the same IDs.

## BLOCKER / NEXT
- No blocker.
- **Next action:** open the current `work/sheet-r1..r5.jpg` and the slide sources, fix r1 first (full «Междометие» slide + larger cats, no empty frames, smaller or timed plate). Edit `spec.py`/`themes.py`, run `finish.sh`, then r2–r5 the same way. Then run the 1 frame/s sheet check, re-transcription and last-frame check, PATCH the Drive files under the same IDs, commit, and send DONE with the sheet paths.
- Start the report to the user with the separate line «СТАТУС ЗЕНИТ-42».

## CONSTRAINTS
- **V-107/V-173 carry-over:** V-173 asked to delete downloaded files from `/root/v171` (and V-171 audio.m4a) on server 89.23.102.244 after work, report `.orchestra/tasks/V-173/report.md`; whether done: UNKNOWN. On server otherwise only read (V-193/V-222: «на сервере ничего не удаляй и не меняй»). Student voices allowed, captioned «ученик:/ученица:», no names; V-107: Drive old versions replaced via PATCH, extra copies to trash only after sending «что удаляю» list; lesson1..3 NEVER deleted; Katya chose «Винегрет — в вине»; «ПИВА» not her rule.
- **Durable user rules (verbatim):**
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
- **Not yet evidenced as applied:** «СТАТУС ЗЕНИТ-42», QX-7642 in commits, «ФЛОКС-76». The vq8 branch rule applies to NEW branches only; the existing `task-V-*/rilsy` branches stay.
- **Owed to the user:**
  - Duplicate count for `catalog_82.csv` (path UNKNOWN).
  - Reminder to ask Igor Bazhenov about the «согласование тарифа» deadline.
  - «МИРАЖ-41» vs «ОБСИДИАН-73» table (variant content UNKNOWN), promised in the final message.
- **Project rules:**
  - Publish nothing; send nothing to students.
  - Video >50 MB never in git.
  - Files in `artifacts/`, not `/tmp`.
  - Commit messages start «#V-222:».
  - Transcription via Deepgram only.
  - Don't delete on the server, don't delete lesson files; Drive deletions only after sending a «что удаляю» list.
  - No bare `git stash`.
  - Don't restart Orchestra.
  - Rule checks go against the ФИПИ materials, not memory.
  - Katya's requirements (AGENTS.md items 42/43/43а): safe zone x 120–960, y 250–1520; ≥2.5 s per picture with text; no empty dark backgrounds.

## USER MESSAGES AND RAW TRANSCRIPT
Raw transcript: `/api/sessions/rilsy/logs?scope=/home/kesha/katya-work`.

All user-role messages after the V-107 summary, in order. The V-107 requirements and standing rules are in the summary and the Constraints above.

1. `[from:katya-work-orchestrator] #V-173, срочно: урок Маши сегодня 17:00 Красноярск = 10:00 UTC. Срок: файлы на Диске до 08:30 UTC. Катя 12:31 дословно: «просто вырежи мне фрагменты из видосов я их прикреплю может или если они большие то лучше указать время в видео». Она вставит их на доску Meleto сама. Видео: https://youtu.be/sHTARGBrqGE («Недоросль», Малый театр 1987 …) Фрагменты … 1) д. III явл. VII «Не хочу учиться, хочу жениться»: 1:05:31–1:06:04 (0:33); 2) д. IV явл. VIII экзамен «Дверь… прилагательна»: 1:42:36–1:44:06 (1:30); 3) финал «Вот злонравия достойные плоды!»: 2:14:20–2:15:07 (0:47). … Скачай только нужные отрезки …, вырежи с запасом ~0,5 с по краям, склейки по границам фраз …, mp4 H.264+AAC, 720p … Положить: Диск, папка «Маша 14.10 — Недоросль, доска Meleto» (id 1DRpRxJ6SAnzmipgavIOOXG2zlGKAfyOd) → новая подпапка «видео» … В репо видео не класть … сырьё — в artifacts/V-173/ … На сервере 89.23.102.244 после работы удалить скачанные файлы из /root/v171 (и audio.m4a от V-171 тоже). Отчёт .orchestra/tasks/V-173/report.md …, коммит, DONE мне. Кате ничего не отправлять.` (condensed with ellipses; the full text is in the raw log)

2. `[from:katya-work-orchestrator] #V-193: рилсы из записей сегодняшних уроков (15.10)…` Full text, including the Katya quote and requirements 42–43, is in the raw log. Key: 3–5 best reels, ≤30 s, «Винегрет» benchmark, no student cameras or names, nothing published, Drive folder «Рилсы с уроков 15.10», report `.orchestra/tasks/V-193/report.md`, deadline end of 16.10.

3. `[from:katya-work-orchestrator] Current #V-193: твой ход оборвался на просмотре кадров (s1.png в artifacts/V-193/work) — видимо, перезапуск Orchestra. Продолжи с того места, где остановился; … Готовые куски коммить по мере готовности. Срок — сегодня до 20:00 Красноярск.`

4. `Update your checklist: mark what is done and which step is current.`

5. `[from:katya-work-orchestrator] #V-193: посмотрел contact-all.jpg. Кате в таком виде не отправляю: по п. 42–43 это брак. Нужен ещё проход по всем 5 рилсам, срок прежний — 20:00 Красноярск. 1. Доска мелкая и не читается … 2. Субтитры … мелкие … 3. Плашка курсора … 4. В рилсе 3 убрать «угу» … 5. Прослушай каждый готовый рилс по форме волны и повторной расшифровкой … Замени файлы на Диске под теми же ID. В DONE приложи новый лист кадров по каждому рилсу, кадр каждую секунду.` (condensed)

6. `[system] Orchestra server restarted…` was a system message, not from the user.

7. `[from:katya-work-orchestrator] Current #V-193: ход снова оборвал перезапуск Orchestra. Продолжай проход по 5 рилсам … Готовые рилсы коммить по одному сразу … Срок — 20:00 Красноярск.`

8. `[from:katya-work-orchestrator] #V-193: посмотрел sheet-p1. Нижняя половина кадра по-прежнему пустая бордовая, а сама доска — полоса около 40 % высоты, где одна строка «Я хочу сдать ОГЭ на пятёрку» набрана мелко. Кате так не отдаём. Ещё проход по 4 рилсам … текст доски не мельче субтитров, примерно 70–90 px высоты строки в кадре 1080×1920 … Пустого фона больше 15 % высоты кадра быть не должно … Пришли один лист кадров на каждый рилс, кадр в секунду.` (condensed)

9. `[from:katya-work-orchestrator] #V-222: рилсы из уже имеющихся записей уроков Кати. Катя дословно (18.10, 09:06): «Ты мне рилсов каких-то наделай из того что есть интересных». …` Full text is in the raw log. Key: 3–5 new reels ≤30 s, V-220 benchmark, not duplicating V-202/V-193, items 42/43/43а, end card with the gift and @iskra_rus_lit, Drive subfolder «Рилсы 18.10», DONE table (title, duration, source, Drive ID) plus sheet paths.

10. `[from:katya-work-orchestrator] Current #V-222: я посмотрел листы всех пяти рилсов. Моменты выбраны хорошо, но в таком виде Кате отдавать нельзя: по п. 42 главное в кадре — слайд, крупно и читаемо, ничего не налезает. Нужен второй проход с правками ниже.` The per-reel list is reproduced under TASK STATE → Pass-2 requirements. Closing line: `Проверка та же: лист кадров 1/с — смотри каждый кадр на обрезанные слова, перекрытия и пустоту. Повторная расшифровка, замена на Диске под теми же ID. В DONE — пути к новым листам.`