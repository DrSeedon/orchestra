## TASK STATE
- **Current task: #V-107**, rework of the Instagram reels cut from Katya's Zoom lesson recordings. Reporting line is `katya-work-orchestrator` only.
- **Status:** a DONE report was sent (delivery_id=59608dca-faa1-47e0-844f-caac1c7b0cfe). It covers 12 reels rebuilt, patched on Drive under the old IDs, plus the new reel «Винегрет — в вине». Branch `task-V-107/rilsy`.
- **Last action:** git cleanup the orchestrator asked for. `git merge main` hit a `.gitignore` conflict; I kept both sides, ran `git rm --cached` on the three large `src/` mp4s (files kept on disk) and committed. **HEAD ecd026f**, reported to the orchestrator (delivery_id=2eb9ec48-5bfd-4e34-b37b-aaf912f4b5cf). I also told them the three big files remain in earlier commits of the branch, so a push may still be rejected. Their reply is not seen.
- **Earlier today (still on record):**
  - V-101 `wedding_R.mp4` was sent and I am waiting for feedback.
  - A merge of main into the branch was done for the `.gitignore` conflict and I answered «готово к мержу».
  - V-94 was reported DONE.
- **Not verified in the visible output:**
  - Resolved: the DONE report lists all 12 reels as patched on Drive under old IDs (incl. Шпион 1xplM8WyhOI2j7bPV4YzP_ASKau38LE3c, Ослик 1HAWYZLWshQH-Al4ql9D-OzaSfuO4YYCy, Проверь себя 13MWQwcpW5pYJBqPAkGOjhwomw-Ytsvn9). Винегрет mp4 1fJqRNOQGJhpuWxQeVphPppYF0_RKe9Uy, описание .txt 1ZCCw5e08IRclOwrwCePwAJ2BfW76K0nd (папка «Задание 9 (урок 03.10)»).
  - Reel 9 was patched manually: id `13MWQwcpW5pYJBqPAkGOjhwomw-Ytsvn9`.
  - ASR check of the finished reels: 86–100% match (worst: Ослик 86%, Мак 88%, Проверь себя 91%, Шпион 92%). Only machine-checked, joins not judged by ear. Unconfirmed: «Одного» in Шпион; «Ну» inside fused phrases not cut (Словно 9,0 и 17,3 с; Деепричастие 10,9 с); owner of voice «Е, да» in Проверь себя; Drive file name «Ловушка ЕГЭ. Опоздать или опаздать.mp4» differs from the local name.

## DECISIONS
- **Cutting engine:** `cutter.py` cuts at real silence between words, since Zoom audio has digital silence of −60…−85 dB. Deepgram word timings alone were not exact. Fillers are cut by detecting speech segments with no recognised word and checking pitch flatness.
- **Safe zone:** x 120–960, y 250–1520, verified by rendering only the text layers on black. All 13 reels are reported «В ЗОНЕ».
- **Design:** each reel gets its own theme in the Iskra palette (`themes.py`). Titles use Ruslan Display. Subtitles use Montserrat SemiBold, word by word.
- **Student voices** are kept and captioned «ученик:» without names.
- **Katya's choices:**
  - She accepted the first two reels (Причастие, Ловушка).
  - She chose candidate 02 «Винегрет», which is built.
  - Other candidates (01, 03–10) are not to be built.
  - «ПИВА» is excluded because it is not her rule.
  - Candidates 12–15 from «12 задание ЕГЭ» were sent as raw clips and are awaiting her pick.
- **Provisional (V-101):** style R (Ruslan Display 86, brown/pink) is provisional until Katya approves.
- **Unresolved conflict:** a Co-Authored-By trailer requested by the system reminder versus the global CLAUDE.md, which forbids it. Commits so far have none.

## FILES AND ARTIFACTS
All paths are under `/home/kesha/orchestra/worktrees/home-kesha-katya-work/rilsy/`.
- `artifacts/task-V-107/`:
  - Committed scripts and data: `cutter.py`, `build_reel2.py`, `themes.py`, `reels2.json`, `finish.sh`, `publish.sh`, `check_safe.py`, `contact.py`, `verify_asr.py`, `heard.py`, `candcut.py`, `transcribe_range.py`, `transcribe_file.py`, `firstframes.py`, `dark-lesson*.json`.
  - Git-ignored (local only): `out/` (final reels plus `Задание 9 (03.10) 10. Винегрет — в вине.txt`, the description with hashtags), `final/`, `work/`, `candidates/` (raw clips 01–15), `src/*.mp4` (`ege12.mp4`, `noun2023.mp4`, `video1678220992.mp4`, kept on disk).
- `.orchestra/tasks/V-107/report.md`, contact sheets `.orchestra/tasks/V-107/contact-*.jpg`, KB note `.orchestra/kb/rilsy-nareznya-zoom.md` and its index line. These are committed (last commits 52f331a, ecd026f).
- **Drive:** the 12 reels are patched under their old IDs via `artifacts/V-45/gpatch.sh`. The folder «01_ИСКРА — школа и работа/Рилсы» was listed with IDs.
- **Local cleanup done:** old mp4s in `artifacts/task-V-94/out` and `stage1/rerun` were trashed (24 files, 80 MB). `lesson1..3` sources were kept.
- **V-101:** `artifacts/task-V-101/out/wedding_R.mp4` (19.7 s, 720×1280), render command `python3 build.py --style R --out out/wedding_R.mp4` with `venv/bin/python`.

## BLOCKER / NEXT
- **Blocker:** none known. The orchestrator's answer on the push and on the history problem is pending.
- **Next action:** read the orchestrator's reply. If the push still fails because of the three files in earlier commits, rewrite the history of the unpushed branch (e.g. rebase or filter) only after confirming with the orchestrator.
- **Open items:**
  - Drive deletion list: the DONE report already told the orchestrator «Что удалять на Диске: ничего» (recursive listing of «Рилсы» shows no duplicates/v1–v3/копии). Nothing to delete unless the orchestrator says otherwise; any future Drive deletion requires the «что удаляю» (name, ID) list first (orchestrator, 07.10 11:11).
  - Await Katya's pick among candidates 12–15.
  - Await V-101 feedback on `wedding_R.mp4`, and the orchestrator's answer on the four-pointed stars option.
- **Pending from the user:**
  - Check `catalog_82.csv` for duplicates and report the count (path UNKNOWN).
  - Remind the user to ask Igor Bazhenov about the deadline for «согласование тарифа» (by end of week).
  - Put the «МИРАЖ-41» vs «ОБСИДИАН-73» comparison table in the final message (content of the variants UNKNOWN).

## CONSTRAINTS
- **Standing rules from the user (verbatim, durable):**
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
- **Not evidenced as applied so far:** «СТАТУС ЗЕНИТ-42», QX-7642 in commits, «ФЛОКС-76». Apply them from now on. The vq8 branch rule applies to new branches only; the existing `task-V-107/rilsy` and `task-V-101/rilsy` stay.
- **Task rules:**
  - Video and sources over 50 MB stay out of git.
  - Files go in `artifacts/task-V-107/`, not `/tmp`.
  - Drive updates go as PATCH under the old IDs.
  - Rejected old versions are deleted.
  - `lesson1..3` are never deleted.
  - Commit messages start «#V-107:» or «#V-101:».
  - Bash calls stay under 120 s.
  - No bare `git stash`.
  - Don't restart Orchestra.
  - Don't publish anything to social networks.
  - Zoom passcodes are omitted.
  - The Bash tool name is capitalised.
- **From Katya's checklist (full text at `/tmp/checklist-katya.md`, 26 KB):**
  - Item 42 (reels): zoom by meaning, the slide stays readable, her face is a small window, cuts on word boundaries, no pauses or fillers, no frozen face window, student voices allowed, text inside the Reels safe zone.
  - Item 43: word-by-word subtitles in the pink and brown style.
  - Items 38–41: give deadlines immediately; short answers; after two «не то» in a row stop and ask for a sample; don't say «проверил» until a side-by-side check against her original.

## USER MESSAGES AND RAW TRANSCRIPT
Raw session transcript: `/api/sessions/rilsy/logs?scope=/home/kesha/katya-work`.

Messages arrived from `katya-work-orchestrator` (relaying Katya) and are listed here in order of arrival. The standing owner rules above came from the user in the earlier summary.

**V-101 (earlier, from the summary):**
- Katya 07.10 09:50: «Короче, обрежь видео точно так же, как и там, и сделай субтитры к песне, ну, типа, к звуку, чтобы красиво это выглядело прям вообще очень.»
- Katya 09:56: «Нет, я хочу, чтобы, типа, слова выделялись те, которые говорят в ролике.»
- Katya 09:57: «Нет, я же 2-ой ролик отправила. Там просто нужно обрезать точно так же, как и в видео.»
- Katya 10:01: «Субтитры посередине сделай и более красиво все оформи»
- Katya 10:13: «Некрасивый шрифт и появляется резко все»
- Katya 10:14 (sample `photo_20261007_031441_232181.jpg`): «Такой и такие же цвета розовый и коричневый такой»
- Orchestrator, two defects: text on faces in the last seconds; the dangling «бы».

**Messages in this segment:**
1. [10:23] «Current #V-101: merge_worker упал на конфликте в .gitignore. Влей main в свою ветку, разреши конфликт (сохрани строки обеих сторон), закоммить, дерево чистое — ответь одной строкой «готово к мержу». Больше ничего не делай: следом будет новая задача по рилсам.»
2. [10:24] «#V-107 — переделать все 12 рилсов V-94 (artifacts/task-V-94/out/*.mp4, сборщики и записи уроков у тебя в task-V-94).»
   - Katya (07.10, 17:23–17:24, voice): «У тебя очень криво всё обрезано по словам и по моей картинке разговора всё зависает. Голоса учеников можешь оставлять? Такого? Вырезая интересные фрагменты, да. И вот то, что ты сверху пишешь и снизу, текст, Искры логотипа, не видно будет, потому что там все плашки закрываются всякими надписями в инстаграме.» «И там, где причастие, есть ещё паузы типа „А“ и так далее.» «В общем, много где пауза в речи есть, и где-то обрывается не на тех местах.»
   - Requirements:
     1. Cuts on word and phrase boundaries by Deepgram word timings, padding ~80–120 ms, no clipped words or syllables. Start and end on a finished thought. Remove pauses >0.4 s, «а-а/э-э/ну/м-м» and repeats with a 20–30 ms audio micro-crossfade, no clicks. Check every join by ear or spectrogram.
     2. Her face window must not freeze. Find where the freeze comes from (freeze-*.png, tpad). Use live video; if the source really freezes, cut that piece or show the slide large without the window.
     3. Student voices allowed (consent confirmed by Katya 07.10 13:41). Add lively fragments (answers, reactions, laughter, «а, понял!»). Caption the student neutrally («ученица:»), no names.
     4. Instagram Reels safe zone 1080×1920: all text, subtitles and the ИСКРА logo inside it. Not above ~250 px at the top, not below ~1520 px, right margin ≥120 px. Check with frames carrying the Reels UI mask.
     5. Camera zooms and the rest per item 42 of her checklist (attached, «Рилсы» section updated today).
     - First 2 reels (Причастие, Ловушка) for approval, then the other 10. Files in `artifacts/task-V-107/`, not `/tmp`. Drive «Рилсы» replaced under the same IDs after her «ок». Deadline 08.10 07:00 UTC (14:00 КРС).
3. [10:29] «Current #V-107: Катя (17:28): «Там ещё всякие разные же можно нарезать рилсы, там же и несколько видео скидывала с разных уроков.» → после переделки 12 сделай новые рилсы из ВСЕХ записей её уроков, которые у нас есть (три Zoom-урока в task-V-94 + любые другие её записи уроков: /home/kesha/orchestra/data/uploads/*.mp4|*.mov|*.MOV за сентябрь–октябрь, кроме свадебного IMG_4771/IMG_1368, и на её Диске — поищи «Zoom», «запись урока»). Составь список найденных записей (файл, дата, тема, длительность) и план 6–10 новых рилсов разных форматов (ловушка, проверь себя, шпион, правило за 20 с, живой момент с учениками, мини-разбор сочинения и т.п.) — пришли мне список и план одним сообщением до сборки. Все новые правила (склейки по словам, без пауз, безопасные зоны, голоса учеников можно) — те же.»
4. [10:43] «Current #V-107: твой ход оборвал рестарт Orchestra. Продолжай с места остановки (сначала проверь git status и что уже есть в artifacts/task-V-107/). Порядок прежний: 2 рилса на показ (Причастие, Ловушка) → остальные 10 → список записей и план новых рилсов.»
5. [11:10] «Current #V-107: Катя (18:10): «Да, мне нужны ещё рилсы.» → 2 показанных принимаются; положи их на Диск под прежними ID. Дальше: (1) остальные 10 тем же движком, на Диск под прежними ID; (2) новые рилсы из всех записей уроков — сначала пришли мне список записей и план 6–10 новых рилсов (одним сообщением), не жди меня для пункта 1. Срок пункта 1 — 08.10 07:00 UTC.»
6. [11:11] «Current #V-107: Катя (18:11): «Старые рилсы удаляй, старые версии.» → На Диске в «Рилсы» (все подпапки): каждая новая версия — PATCH под прежним ID; все прочие старые варианты/дубли (v1–v3, черновики, «копия», предыдущие имена) — в корзину Диска. Локально: старые mp4 прошлых версий в artifacts/task-V-94/out и промежуточные ролики — удалить (п.34), оставить только финальные новые и исходные записи уроков (lesson1..3 — НЕ удалять, это исходники). Перед удалением на Диске пришли мне список «что удаляю» (имя, ID) одним сообщением вместе с отчётом по 10 рилсам; локально можно сразу.»
7. [11:16] Katya (18:16): «делай в моём стиле, но можно делать разные дизайны, формы, шрифты. Вот шрифт мне новый понравился.» → Iskra palette (бордо/кремовый/коричневый, логотип) stays, but each reel has its own look (plate shapes, layout, accents); titles Ruslan Display; subtitles readable; contact sheet of first frames must show all 12 differ; same safe zones.
8. [11:30] Katya (18:30) found plan N1–N9 boring → new plan: search for «интересное» (laughter, jokes, ага-моменты, student errors, etymology stories, hook phrases) in all 3 lessons, IMG_0798 promo, old Drive recordings (noun 2023, «12 задание ЕГЭ» 2024, video1678220992.mp4; children of 2023 — voice only, no faces). Send 8–10 candidates (hook, why, source+timecode, raw 15–25 s clip in `artifacts/task-V-107/candidates/`). «Не собирай финальные рилсы до её выбора.»
9. [11:47] «Current #V-107: Катя выбрала кандидата 02 «Винегрет — в вине» (18:44 «Супер этот» → 18:47 «Где про винегрет»). Собери из него готовый рилс по всем правилам (склейки по тишине, без пауз, безопасная зона, своё оформление в палитре Искры, заголовок Ruslan Display, пословные субтитры, имя ученика вырезать, реплики ученика «ученик:») + описание с хештегами в txt рядом. Остальные кандидаты пока не делай — она может выбрать ещё. Пришли путь к mp4 сразу, как будет готов (до остальных 12).»
10. [11:47] «Current #V-107: Катя (18:47): «Остальные не очень, но можно взять ещё из того видео, где про правило ПИВА, но это не моё правило, поэтому его лучше не брать, а взять что-нибудь другое.» → Из записи «12 задание ЕГЭ русский. Теория» (02.2024) найди 2–3 других сильных момента (не «ПИВА»: её собственные объяснения, приёмы, юмор — например «Ой-ой-ой-ой. Больше не буду» 6:34, если он к месту), пришли сырые фрагменты 15–30 с в candidates/ с крючками — она выберет. Винегрет — в работе как договорились. Остальных кандидатов 01, 03–10 не делаем.»
11. [12:13] «Current #V-107: GitHub отверг пуш: в ветке закоммичены исходники artifacts/task-V-107/src/ege12.mp4 (116 МБ), video1678220992.mp4 (153 МБ), noun2023.mp4 (93 МБ) — лимит 100 МБ. В main я их уже вынул из коммита и добавил `artifacts/task-V-107/src/*.mp4` в .gitignore. В своей ветке: влей main, `git rm --cached` эти три файла (файлы на диске НЕ удаляй — это исходники), коммит. Дальше видео/исходники >50 МБ в git не клади. Ответь одной строкой с HEAD.»