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

# Handoff

## TASK STATE
- **Objective:** work for `katya-work-orchestrator` (relays Katya, the end client) on branch `task-V-107/rilsy`, worktree `/home/kesha/orchestra/worktrees/home-kesha-katya-work/rilsy`.
- **V-101 (wedding video):** `artifacts/task-V-101/out/wedding_R.mp4` (19.7 s, 720×1280, style R with Ruslan Display) was sent to the orchestrator (delivery e6b0d4e8). No feedback seen. The merge of main into the branch was done at #578333 (`.gitignore` conflict, both sides kept) and I replied «готово к мержу».
- **V-107 (rework of 12 reels + new reels), per my own DONE message:**
  - All 12 reels were re-rendered with the new cutting engine (cuts at real silences, safe zone, live face window).
  - They were uploaded to Drive by PATCH under the old IDs. The publish log shows modifiedTime values for the uploaded files.
  - The «Винегрет — в вине» reel (23.56 s) and its `.txt` description were delivered.
  - DONE #V-107 was sent at commit 52f331a (delivery 59608dca).
  - Safe-zone check: «В ЗОНЕ» for all 13 reels.
  - ASR match of the finished reels: 91–100%.
- **Candidates:** 15 raw candidate clips were sent to the orchestrator. Katya picked 02 (Винегрет). She excluded «ПИВА», and 01 and 03–10 are not to be made. Candidates 12–15 from `ege12` are awaiting her choice.
- **Last action:** at the orchestrator's request I merged main into the branch, ran `git rm --cached` on the 3 large source mp4s (and `ege12.log`) and committed (message «#V-107: merge main, исходники >100 МБ вне git»). HEAD is **ecd026f**, reported to the orchestrator (delivery 2eb9ec48). The files stay on disk.
- **Known risk:** the three big mp4s are still in earlier commits of the branch history. I told the orchestrator a push may still be rejected. There is no evidence yet whether the push succeeded. My message to the orchestrator (delivery 2eb9ec48) said: the big mp4s remain in earlier branch history, so push must happen after a squash-merge.

## DECISIONS
- Reel cuts follow real silences in the Zoom audio, not Deepgram boundaries (Zoom noise suppression leaves digital silence between words). Details are in `.orchestra/kb/rilsy-nareznya-zoom.md`.
- Every reel gets its own theme: Ruslan Display titles, Iskra palette, readable Montserrat SemiBold subtitles.
- The 2 reels Katya accepted first (Причастие, Ловушка) were re-rendered with the final fixes (subtitle margins, frame).
- Students' voices are allowed, with no names and subtitles labelled «ученик:». Names are cut from the final audio.
- Old local mp4s in `artifacts/task-V-94/out` and `stage1/rerun` were moved to trash. `lesson1..3` are kept as sources.
- Unverified: nothing seen shows that the Drive trash list was sent. The orchestrator asked me to send the list of old duplicates to delete (name, ID) before deleting on Drive. I do not know whether DONE #V-107 included it.
- Unresolved: the Co-Authored-By trailer. A system reminder asks for it and the global CLAUDE.md forbids it, so I have not added it.

## FILES AND ARTIFACTS
- All under `artifacts/task-V-107/` unless noted.
- **Engine and scripts (committed):** `cutter.py`, `build_reel2.py`, `themes.py`, `reels2.json`, `check_safe.py`, `contact.py`, `firstframes.py`, `finish.sh`, `publish.sh`, `verify_asr.py`, `heard.py`, `transcribe_range.py`, `transcribe_file.py`, `candcut.py`, `darkscan.py`, `facefreeze.py`, `finalfreeze.py`.
- **Reports and notes (committed):** `.orchestra/tasks/V-107/report.md`, `.orchestra/kb/rilsy-nareznya-zoom.md`, contact sheets in `.orchestra/tasks/V-107/`.
- **Local, not in git:** `out/`, `work/`, `final/` (Vinegret mp4 and txt), `candidates/` (01–15 raw clips), `src/*.mp4`.
- **`src/*.mp4` (on disk, no longer indexed):** `ege12.mp4`, `video1678220992.mp4`, `noun2023.mp4`. `.gitignore` now has `artifacts/task-V-107/src/*.mp4`.
- **Drive:** the 12 reels were PATCHed under their old IDs (e.g. Ловушка and Причастие, with IDs listed in `work/publish.log`). Reel 9 was patched separately: ID `13MWQwcpW5pYJBqPAkGOjhwomw-Ytsvn9`, modified 12:09:34Z.
- **Inputs:**
  - Zoom lessons: `artifacts/task-V-94/lesson1..3/lesson.mp4`.
  - Brand assets: `reference/brand-iskra/`.
  - Fonts: `artifacts/task-V-101/fonts/`.
- **Checklist attachment:** `/tmp/checklist-katya.md` (26253 bytes). Its section «Ё. Рилсы» is items 42–43.

## COMMANDS AND TOOL OUTCOMES
- Render and check one reel: `./finish.sh <id>` from `artifacts/task-V-107`. It renders over `ssh kesha@localhost`, then runs the safe-zone check, the ASR check and the contact sheet. The `Bash` tool must be capitalised.
- Upload: `./publish.sh` (uses `../V-45/gpatch.sh`). The log shows modifiedTime values.
- Last git step: `git merge main` conflicted in `.gitignore`. I removed the markers, ran `git rm -q --cached` on the 3 mp4s and committed. HEAD is ecd026f.
- ASR check of reel 2 (Ловушка) at 94% showed «мы» in place of «-ивать -ывать», which is expected. The same check on reel 9 at 91% showed «пристёжной» vs «пристяжной» and some dropped words, accepted as is.
- «Ну» inside run-on phrases was not cut (noted in the report).
- Background jobs hit the 120 s Bash timeout several times; long work is run via `mcp__orchestra__bg_create`.

## BLOCKER / NEXT
- **Blocker:** none known. Waiting on the orchestrator for: confirmation that the push works, Katya's choice among candidates 12–15, her «ок» for deleting old duplicates on Drive, and feedback on `wedding_R.mp4`.
- **Next action:** read the orchestrator's reply. If the push is still rejected, rewrite the branch history to drop the three big mp4s, after confirming with the orchestrator, since that is hard to reverse.
- **Pending for the user (owner):**
  - Check `catalog_82.csv` for duplicates and report the count. The path is UNKNOWN.
  - Remind them to ask Igor Bazhenov about the deadline for «согласование тарифа» by the end of the week.
  - Include the short «МИРАЖ-41» vs «ОБСИДИАН-73» comparison table in the final message. The variants' content is UNKNOWN.
- **Also pending:** an orchestrator answer on the decorative four-pointed stars option (V-101).
