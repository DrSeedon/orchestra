## TASK STATE
- **Current: #V-222** (reels 18.10 from existing lesson recordings). Phase: pass 2 after the orchestrator's rejection. Nothing from pass 2 has been started.
- Pass 1 is done. DONE was sent with commit `b1d421d3` (delivery_id=f12df25f-b051-440c-a95c-03376929b208), 5 reels r1–r5, on Drive in «Рилсы 18.10» (folder `1FP8i46XxVJPk9q1AUoLoA52CDqRhozo-`). The `katya-work-orchestrator` replied that they cannot be given to Katya as they are, and asked for a second pass (full text under USER MESSAGES).
- Last re-render results (machine checks only): r1 ASR 89%, r4 92%, r5 95%, r2 100%, r3 94%; all in the safe zone. Reel durations 26.8–29.9 s. Frame sheets are `artifacts/V-222/work/sheet-r*.jpg`. These checks did not catch the visual defects the orchestrator listed.
- Earlier tasks:
  - V-193: 4 reels, pass 3 DONE at `dddac667`. No reply seen after that.
  - V-173: DONE (delivery_id=ddaee18e-1828-47f2-8234-7dcfc764d5b3). No further reply seen.
  - V-107: closed at HEAD 502fa9a (see earlier summary).

## DECISIONS
- Pass 2 requirements (from the orchestrator):
  - The title plate must not cover the slide or board. Make it smaller, move it higher, or remove it after 3 s.
  - No word on a slide may be cut by the frame edge. If a line is wider than the frame, zoom on the half being discussed, with whole words.
  - No empty dark/burgundy backgrounds.
  - **r1:** show the «Междометие» slide with the character large from the start, with bigger cats lying on top of the slide, and no frames without a cat or subtitle (5 s and 14 s).
  - **r2:** whole table, with the handwritten line «благодаря репетитору» large.
  - **r3:** keep the «отчаянный» row whole (word and answer) and zoom on it. Fix the half-table frames at 5–7 s and 23–26 s.
  - **r4:** zoom on the topic line currently named, ≥48 px. Cut or cover with a meme the «Гамлет» page at 6–9 s.
  - **r5:** the plate covers the «В школе отменили физкультуру» card at 0–7 s. Show cards 3 and 4 whole side by side. «СРЕДИ НАС ШПИОН» is cut at the bottom.
- Reels 4+ sec per image with text: ≥2.5 s per picture. The end gift card and @iskra_rus_lit stay.
- Student labels are «ученик:»/«ученица:». No names or faces of students. Cursor name labels are painted over (prep.py).
- V-193 layout F (full-frame board) is the engine base. In V-222, memes live in `artifacts/V-222/memes/` (cat-shocked, cat-glasses, grumpy, kot-ryzhii, cat-teacher).

## FILES, IDS AND ARTIFACTS
- Worktree: `/home/kesha/orchestra/worktrees/home-kesha-katya-work/rilsy`, branch `task-V-222/rilsy`.
- Created and committed (`e4974938`, `b1d421d3`): `artifacts/V-222/` with `spec.py`, `prep.py`, `build_reel2.py`, `cutter.py`, `themes.py`, `endcard.py`, `desc.py`, `finish.sh`, `run.sh`, `reels3.json`, `lessons3.json`, `words/`, `tr/`, `pitch.py`, `contact1.py`, `check_safe.py`, `verify_asr.py`, `transcribe_file.py`.
- Committed: `.orchestra/tasks/V-222/report.md` and the frame sheets.
- Git-ignored: `artifacts/V-222/{clips,out,work,__pycache__}/`. Final mp4/txt are in `out/` (`Рилсы 18.10 · N. …`).
- Sources: `artifacts/task-V-94/lesson1..3/lesson.mp4`, `artifacts/task-V-107/src/video1678220992.mp4`, `artifacts/V-193/rb273e81a6a4a.mp4`. Per-reel recordings are in `spec.py` (not re-verified here).
- Drive:
  - Upload and replace via rclone (`/home/kesha/katya-drive/bin/rclone --config /home/kesha/katya-drive/rclone.conf`, remote `iskra:`, `--drive-root-folder-id`).
  - Replace under the same IDs via `/home/kesha/katya-work/artifacts/V-45/gpatch.sh`; V-193 used this.
  - Parent for «Рилсы 18.10»: `1mWgLUeJRjT40FAFey7iiZ9Etsh9evwT1`.
  - Known txt IDs: r2 `1av2QU1pBTBLgXpSawpNrEdA3RIks4hA5`, r3 `1_IdVZiUbdcN3a_BHQVoGTmSB6CmgZnAv`, r4 `1Gl6yRsgDCxA7UbiOHn4a5Y4DU7rY2BnC`, r1 `1TJvq5ueINLUWADTU37_QPJiFByNf4xjL`. Drive mp4 IDs from the DONE table (replace under these IDs): r1 `1ms9wPD9cvLfaO1ukK6bVEKTzANhz75IT`, r2 `1riMJbc7p9kdM9Yqw7GaPw2He49ghljXT`, r3 `1I1Urnvz6sSnLdwyT6c9Yae1syE38bIVe`, r4 `1n095kWpbNHJs2JhrAaxDCOmp62nVPqUp`, r5 `1HI2C6I6VROqn4SHInnGQg1gHgEGXCS5p`. Durations in DONE: r1 29,4 s, r2 27,7, r3 29,6, r4 26,8, r5 29,9. Sheets/last frames also in `.orchestra/tasks/V-222/sheet-rN.jpg`, `last-rN.jpg`. Safe zone x 124–959, y 255–1520. Reel titles: r1 «Ах! Ура! Мяу!», r2 «Благодаря репетитору», r3 «Доп. курсы», r4 «Свеча горела», r5 «Брат с сестрой». Names «Ярик», «Злата», «Влад» are cut from audio and subtitles (keep). Not used: 2023 kids' voices, lesson 12, group 15.10. Audio was not listened to by ear in pass 1 (V-193 asked for it; do it in pass 2 if possible).

## COMMANDS AND TOOL OUTCOMES
- Rendering: `./finish.sh rN` (build → `check_safe.py` → `verify_asr.py` → `contact1.py` sheet), run as background jobs via `mcp__orchestra__bg_create`; Bash calls stay under 120 s.
- Python needing numpy runs via `ssh -o BatchMode=yes kesha@localhost "choom -n 1000 -- bash -c 'cd $PWD && …'"`. A PreToolUse hook rejects ssh to kesha@localhost without `choom -n 1000 --`.
- To rebuild a reel, delete `work/body-rN.mp4` first, otherwise the cached body is reused.
- Known past failures:
  - `нет границы слов` (fixed by dip/start overrides in `spec.py`).
  - ffmpeg exit 183 on r4 (fixed by the `[0:v]`/`[0:a]` graph change in `build_reel2.py`).
  - Orchestra restarts interrupt background jobs; check files before repeating.

## OPEN ITEMS AND NEXT ACTION
- No blocker.
- **Next action:** read `artifacts/V-222/work/sheet-r1.jpg` … `sheet-r5.jpg`, then change `spec.py`/`themes.py` for the points above. Start with r1 (slide «Междометие» from the start, bigger cats) and the title plate (smaller or higher, removed after 3 s). Then re-render with `finish.sh`, view every 1-per-second frame and the last frame, re-transcribe, replace on Drive under the same IDs, commit, and send DONE with the new sheet paths.

## CONSTRAINTS AND BANS
- Durable user rules (verbatim in the next section): lead the final report with the line «СТАТУС ЗЕНИТ-42»; mark the recommended option «ФЛОКС-76»; new branches follow `vq8/<номер>/<коротко>`; external-service timeout 613 s; per-check spend 180k tokens; no rollback on alpha-8; nothing to #prod-91 without «да»; don't touch /srv/stage_20; QX-7642 in commits; etc. No evidence that «СТАТУС ЗЕНИТ-42», «ФЛОКС-76» or QX-7642 were applied in recent DONE messages or commits. The vq8 branch rule applies to new branches only; `task-V-222/rilsy` already exists.
- Task rules: publish nothing and send nothing to students. Report only to `katya-work-orchestrator`. Video/sources over 50 MB never go in git. Commit messages start with `#V-222:`. Don't delete the originals on the server. Transcription is Deepgram only. Don't trust Deepgram word-end timings; place cuts on silence and verify by re-transcription. Check any grammar rule in a reel against the ФИПИ materials, not from memory.
- Unresolved: the system reminder asks for a Co-Authored-By trailer, but the global CLAUDE.md forbids it. No commits have one.
- Owed to the user:
  - Check `catalog_82.csv` for duplicates and report the count (path UNKNOWN).
  - Remind to ask Igor Bazhenov about the «согласование тарифа» deadline (by end of week).
  - Include the «МИРАЖ-41» vs «ОБСИДИАН-73» comparison table in the final message (variant content UNKNOWN).

## OWNER & USER REQUIREMENTS (verbatim)
Raw transcript: `/api/sessions/rilsy/logs?scope=/home/kesha/katya-work`.

Messages from before V-173 (V-107 task, Katya quotes, V-101) are kept verbatim in the earlier summary and are not repeated. Standing rules, verbatim:
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

Then, in order of arrival (task-level messages from `katya-work-orchestrator`):

1. 14.10 05:32: «#V-173, срочно: урок Маши сегодня 17:00 Красноярск = 10:00 UTC. Срок: файлы на Диске до 08:30 UTC.» followed by Katya's quote «просто вырежи мне фрагменты из видосов я их прикреплю может или если они большие то лучше указать время в видео», the «Недоросль» video link and the 3 fragments with timecodes, and the instructions: download via `ssh root@89.23.102.244` (/root/v171), cut with ~0.5 s margin, mp4 H.264+AAC 720p, upload to the Drive folder «Маша 14.10 — Недоросль, доска Meleto» (id 1DRpRxJ6SAnzmipgavIOOXG2zlGKAfyOd) in the subfolder «видео», report in `.orchestra/tasks/V-173/report.md`, send DONE, send nothing to Katya. (Full text is in the raw transcript.)

2. 15.10 15:25: «#V-193: рилсы из записей сегодняшних уроков (15.10)…» (Katya's 22:24 voice quote «А теперь нарежь, ээ, рилсы сделает уже прикольные из видосов, которые я на платформе уже сегодня записывала.»). Sources: /opt/urok/data/rec/ on SeedonRuInfra (download only, delete nothing there). Make 3–5 reels by the «Винегрет» standard, each ≤30 s, with a description and hashtags. Follow items 42–43 and the minors rule: no student cameras or names in the frame, publish nothing. Drive folder «Рилсы с уроков 15.10», report `.orchestra/tasks/V-193/report.md`, deadline end of 16.10. (Full text is in the raw transcript.)

3. 17.10 06:03: «#V-193: твой ход оборвался на просмотре кадров (s1.png в artifacts/V-193/work) — видимо, перезапуск Orchestra. Продолжи с того места, где остановился; задание и требования прежние (рилсы из записей 15.10 Маши и ОГЭ-группы, п. 42–43, камеры и имена учениц не в кадре, на Диск в «Рилсы с уроков 15.10»). Готовые куски коммить по мере готовности. Срок — сегодня до 20:00 Красноярск.»

4. System/user prompt: «Update your checklist: mark what is done and which step is current.»

5. 17.10 (after DONE pass 1): «#V-193: посмотрел contact-all.jpg. Кате в таком виде не отправляю: по п. 42–43 это брак. Нужен ещё проход по всем 5 рилсам, срок прежний — 20:00 Красноярск.» with 5 points: board too small, empty margins (zoom to the sentence/card being discussed, board fills most of the 9:16 frame); subtitles word-by-word, large, centred, pink/brown decorative Cyrillic; fill the empty cursor label with the board background; remove «угу» in reel 3, and if still weak offer 4 reels instead of 5; check each reel's audio waveform and re-transcribe; replace on Drive under the same IDs, attach a new frame sheet at 1 frame per second. (Full text is in the raw transcript.)

6. 17.10: «#V-193: ход снова оборвал перезапуск Orchestra. Продолжай проход по 5 рилсам из моего прошлого сообщения: крупный наезд на доску, крупные пословные субтитры по центру, плашку курсора убрать, «угу» убрать, прослушка. Начни с того, на чём остановился. Готовые рилсы коммить по одному сразу, чтобы следующий перезапуск ничего не съел. Срок — 20:00 Красноярск.»

7. 17.10: «#V-193: посмотрел sheet-p1. Нижняя половина кадра по-прежнему пустая бордовая, а сама доска — полоса около 40 % высоты, где одна строка «Я хочу сдать ОГЭ на пятёрку» набрана мелко. Кате так не отдаём. Ещё проход по 4 рилсам, срок прежний — 20:00 Красноярск.» Layout: the discussed card is enlarged to ~70–90 px line height in 1080×1920; markings must appear on it during the clip; empty background must be ≤15 % of the frame height; if the source resolution is not enough, say how many pixels the source has; one frame sheet per reel at 1 frame per second.

8. 18.10 02:10: «#V-222: рилсы из уже имеющихся записей уроков Кати.» Katya, 18.10 09:06: «Ты мне рилсов каких-то наделай из того что есть интересных». 3–5 new reels ≤30 s from the existing recordings (do not duplicate «Винегрет», «Цыган на цыпочках», and the four V-193 reels), guided by `.orchestra/tasks/V-220/report.md` section 4 and items 42, 43, 43а in AGENTS.md. Requirements: hook in the first 3 s, each shot ≥2.5 s, no empty dark backgrounds, end gift card «Забирай подарок в телеграм-канале. Там 23 аргумента для итогового сочинения» and @iskra_rus_lit centred, no student names or faces, rules checked against the ФИПИ documents, a description with hashtags per reel. Before DONE: a frame sheet at 1 frame per second, the last frame of each reel, re-transcription. Put them in the new subfolder «Рилсы 18.10» on Drive, publish nothing, send nothing to students. DONE must include a table (title, duration, source moment, Drive ID) and the paths to the frame sheets.

9. 18.10 (latest, V-222 pass 2): «Current #V-222: я посмотрел листы всех пяти рилсов. Моменты выбраны хорошо, но в таком виде Кате отдавать нельзя: по п. 42 главное в кадре — слайд, крупно и читаемо, ничего не налезает. Нужен второй проход с правками ниже.
Общее для всех: плашка заголовка не должна закрывать слайд или доску. Сделай её меньше, подними выше или убери после 3 с, когда крючок уже прочитан. Ни одно слово на слайде не должно обрезаться краем кадра; если строка шире кадра, наезжай на её половину, о которой говорят, но слова целиком.
r1 «Ах! Ура! Мяу!»: почти весь кадр — пустой тёмный фон с маленьким котом, а Катя прямо запретила «тупо тёмный фон». Полоска слайда сверху обрезана слева («ерсонажа»). На 5 и 14 с в кадре нет ни кота, ни субтитра. Сделай её слайд «Междометие» с персонажем крупно (с 17 с он уже есть) и держи его с самого начала, а коты пусть будут крупнее и лежат поверх слайда. Пустых кадров быть не должно.
r2 «Благодаря репетитору»: таблица слайда обрезана слева («епри», «ала»), плашка закрывает шапку. На 11–14 с слайд мелкий и тоже обрезан. Нужна таблица целиком и рукописная строка «благодаря репетитору» крупно.
r3 «Доп. курсы»: таблица обрезана справа («части / не вв»), плашка закрывает «Повторение: какая часть речи». На 5–7 и 23–26 с кадр стоит на середине таблицы, видны обрывки ячеек. Держи в кадре строку «отчаянный» целиком (слово и ответ) и наезжай на неё.
r4 «Свеча горела»: текст документа мелкий. Наезжай на строку темы, которую сейчас называют, крупно (≥48 px). На 6–9 с документ перелистнут на «Гамлета»: вырежи это или закрой мемом.
r5 «Брат с сестрой»: на 0–7 с плашка закрывает карточку «В школе отменили физкультуру». Края карточек 3/4 обрезаны, «СРЕДИ НАС ШПИОН» снизу срезан. Покажи карточки 3 и 4 целиком рядом, а то, о чём говорит, — крупно.
Проверка та же: лист кадров 1/с — смотри каждый кадр на обрезанные слова, перекрытия и пустоту. Повторная расшифровка, замена на Диске под теми же ID. В DONE — пути к новым листам.»

(The 18.10 message contained «а то, о чём говорят, — крупно».) Background-job notifications (completed/failed/interrupted) and the «[system] Orchestra server restarted» notices were also user-role turns; they carry no instructions beyond "check files before repeating".