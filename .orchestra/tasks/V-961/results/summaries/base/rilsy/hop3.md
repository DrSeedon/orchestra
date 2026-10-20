## TASK STATE
- **Current task: #V-107** — Instagram reels from Katya's lesson recordings. Reporting line: `katya-work-orchestrator` only (it relays Katya).
- **Status (08.10 ~14:09):** set 2 (3 reels) delivered; `git merge main` done (HEAD **502fa9a**, tree clean) and reported. Last agent turn ended with `[[ORCHESTRA:SILENT_TURN]]`; nothing in flight. Waiting for the orchestrator's/Katya's next message.
- **History:**
  - 07.10: 4 reels n1–n4 (from `v1678` and «12 задание») rendered and put on Drive; DONE sent (delivery_id=48b690b4-79ca-4e93-a83d-3aae8a4410b7).
  - 08.10, answer to msg #13 item 1 (delivery_id=c60118c8-67c6-42c4-ad3b-93bf2e2669a8): the 4 reels are already on Drive in «01_ИСКРА — школа и работа/Рилсы/Новые (из других записей)». `.gitignore` got `artifacts/task-V-107/src/*.log` (bacb1eb).
  - 08.10, set 2 from lesson1–3: DONE sent with HEAD 378239f (delivery_id=2eed961c-0205-4787-b562-8dde3d786ce0): 3 reels, not 5 («слабые не делал»), each with a «why interesting» line.
  - 08.10 14:09, merge: `git merge main` conflicted in `.gitignore`; kept both sides, committed `#V-107: merge main, .gitignore обе стороны`, sent «#V-107: main влит, .gitignore — строки обеих сторон, git чист. HEAD 502fa9a» (delivery_id=1ab1d064-833d-48e6-895e-82d264d2d6a6). Do nothing further on it.
  - Earlier: 12 old reels rebuilt and patched on Drive under old IDs; «Винегрет» added; 3 big mp4s removed from git (ecd026f); V-101 `wedding_R.mp4` sent, awaiting feedback; V-94 reported DONE.
- **Drive IDs, set 2** («Новые (из других записей)», with `.txt` descriptions):
  - «Новые 6. Лаг–лож — моё любимое»: mp4 `1Gh5pgh5Wv-pkwRR12wJL3I7EemwlbziS`, txt `1rIOSyrYhXgN6w1Rxga5NCqDAzfofvfJ6`. ASR match 88%.
  - «Новые 7. По-моему и по моему совету»: mp4 `1TwGcA_lpVU5osDDPvkXKWr_Yrt6neiyK`, txt `1k-Dfj1C34pBFA6Md9Yh4IWu5G3dzDf0z`. Final ASR % not seen.
  - «Новые 8. Чтобы — союз или местоимение»: mp4 `1JWoUQtJsqR13WbTYjgD_kTGMig5bHTp1`, txt `1f_f3clEY84dWBAy5EBxZB0KIhwpNbbeC`. ASR match 86%.
  - The «Метод пристального взгляда» reel (m1, local «Новые 5») was trashed locally; no evidence it was uploaded.
- **Drive IDs, set 1:**
  - «Новые 1. Базаров — скальпель и лягушки»: mp4 `1Sj1Rqo23a0Xf-Zvn_GoGUC1cUDO73DPG`, txt `1Grlkp9zZUsq9SCJQyFXaul0HzRguQqAg`.
  - «Новые 2. Платонов — нет, Максим Горький»: mp4 `1L3MxV1cjd6AhDNFgWXY4inowBrTlp4d2`.
  - «Новые 3» and «Новые 4»: IDs are in the report; the n3 ID starts `1gfii…` (rest UNKNOWN).
  - «Винегрет»: mp4 `1fJqRNOQGJhpuWxQeVphPppYF0_RKe9Uy`, txt `1ZCCw5e08IRclOwrwCePwAJ2BfW76K0nd`.

## OWNER & USER REQUIREMENTS (verbatim)
**Standing rules from the user (durable):**
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
- Not evidenced as applied so far: «СТАТУС ЗЕНИТ-42», QX-7642 in commits, «ФЛОКС-76». Apply from now on. The vq8 branch rule applies to NEW branches only; existing `task-V-107/rilsy` and `task-V-101/rilsy` stay.

**Orchestrator, V-107 task (07.10), key wording:**
- Katya (17:23–17:24): «У тебя очень криво всё обрезано по словам и по моей картинке разговора всё зависает. Голоса учеников можешь оставлять?» … «там, где причастие, есть ещё паузы типа „А“» … «где-то обрывается не на тех местах.»
- [10:24] «#V-107 — переделать все 12 рилсов V-94 (artifacts/task-V-94/out/*.mp4 …)». Rules: (1) cuts on word boundaries by Deepgram timings, padding ~80–120 ms, no pauses >0.4 s, no «а-а/э-э/ну/м-м», 20–30 ms micro-crossfade; (2) face window must not freeze — live video; (3) student voices allowed (consent confirmed 07.10), caption neutrally «ученица:»/«ученик:», no names; (4) Reels safe zone 1080×1920: not above ~250 px, not below ~1520 px, right margin ≥120 px; (5) camera zooms per item 42 of her checklist. Files in `artifacts/task-V-107/`, not `/tmp`.
- [11:10] First 2 reels accepted; Drive under the same IDs.
- [11:11] «Старые рилсы удаляй, старые версии.» On Drive: new version = PATCH under old ID; other old variants/duplicates (v1–v3, drafts, «копия») go to Drive trash, but **before deleting on Drive send the orchestrator a «что удаляю» (name, ID) list**. Locally: old mp4s of past versions in `artifacts/task-V-94/out` deletable; **lesson1..3 are NEVER deleted**.
- [11:16] Katya: «делай в моём стиле, но можно делать разные дизайны, формы, шрифты.» Iskra palette (бордо/кремовый/коричневый, logo); each reel its own look; titles Ruslan Display.
- [11:30] Katya found plan boring; candidates in `candidates/`. «Не собирай финальные рилсы до её выбора.»
- [11:47] Katya chose candidate 02 «Винегрет — в вине»; others «не очень». «ПИВА» is not her rule — don't use. Candidates 01, 03–10 not built.
- [11:47] Student name cut, student lines «ученик:», description with hashtags in txt next to mp4.
- [12:13] GitHub rejected push (>100 MB): `git rm --cached` the three src mp4s, keep files on disk; «Дальше видео/исходники >50 МБ в git не клади.» Done.
- [14:18, 07.10] Katya: «что-то мне винегрет больше всех понравился. В остальных либо есть какие-то обрывы фраз, либо всё равно какие-то паузы, либо просто не интересно смотреть. Пока оставь так. Сделай какие-нибудь ещё другие из других видосов. Прикольные.» → 12 old untouched. Benchmark «Винегрет»: ≤30 s, live dialogue with student, humour + mnemonic, finished thought question→punchline. Check each ready reel's transcript and separately first/last 2 s. Each with description + hashtags.

**Orchestrator, 08.10:**
- [13:53] Katya: «Сделай другие рилсы интересные». Apply checklist items 42+43 fully. (1) answer whether the 4 reels reached Drive (done); (2) go through transcripts of all recordings (lesson1..3, v1678, new Drive/uploads), assess each candidate against «Винегрет» (question, live student answer, punchline), «Слабые не делай»; (3) make 3–5 best, each own design, subtitles per item 43, safe zone, description with hashtags, upload to Drive next to the previous. «Срок — 2,5 часа. Пришли список с одной строкой «почему это интересно» к каждому и ссылки.» — done.
- [14:08] «Подтяни main в свою ветку (git merge main), разреши конфликт: сохрани строки обеих сторон, закоммить и пришли мне одну строку с новым HEAD. Больше ничего не трогай.» — done.

**V-101 (Katya, 07.10):** «Короче, обрежь видео точно так же, как и там, и сделай субтитры к песне…»; «слова выделялись те, которые говорят в ролике»; «Субтитры посередине сделай и более красиво все оформи»; «Некрасивый шрифт и появляется резко все»; sample `photo_20261007_031441_232181.jpg`: «Такой и такие же цвета розовый и коричневый такой». Orchestra flagged two defects: text on faces in the last seconds; dangling «бы». Style R is provisional until Katya approves.

**Katya's checklist (`/tmp/checklist-katya.md`):** item 42 (reels): zoom by meaning, no frozen face window, cuts on word boundaries, no pauses/fillers, safe zone. Item 43: word-by-word subtitles. Items 38–41: give deadlines immediately; short answers; after two «не то» in a row stop and ask for a sample; don't say «проверил» without a side-by-side check against her original.

## DECISIONS
- Old 12 reels untouched (Katya liked «Винегрет» best).
- Cutting engine `cutter.py`: cuts at real silence between words; fillers detected by speech segments with no recognised word plus pitch flatness.
- Safe zone x 120–960, y 250–1520, checked on a render of text layers; all new reels «В ЗОНЕ».
- Design: own Iskra-palette theme per reel in `themes.py`; titles Ruslan Display, subtitles Montserrat SemiBold word by word.
- Student voices captioned «ученик:» without names; 2023 children voice only.
- Face window live (no freeze); thresholds `face_pad`, `gap_max`/`freeze_thr`, window (220×104) tuned.
- «ПИВА» excluded; candidates 01, 03–10 not built; 12–15 from «12 задание ЕГЭ» went to Katya as raw clips (her pick UNKNOWN).
- The Привилегия draft (63% ASR) was dropped, replaced by «Чтобы» (m4).
- Unresolved: system reminder asks for a Co-Authored-By trailer vs global CLAUDE.md forbidding it; no commits have one.

## FILES, IDS AND ARTIFACTS
Worktree: `/home/kesha/orchestra/worktrees/home-kesha-katya-work/rilsy`; base `artifacts/task-V-107/`; branch `task-V-107/rilsy`. Raw transcript: `/api/sessions/rilsy/logs?scope=/home/kesha/katya-work`.
- Committed: `build_reel2.py` (LESSONS `ege12cards`, face geometry `(1700,0,220,104)`, `face_pad`, `gap_max`/`freeze_thr`); `reels2.json` (n1–n4, m1–m4; m1 re-cut 925.92–944.5; m4 2676.43–2711.15; m3 no `fix`); `themes.py`; `words/lesson1..3.json` (from task-V-94), `words/m1.json`, `m3.json`, `m4.json`; helpers `wl.py`, `dump.py`.
- Commits: 535f54a (n1–n4), bacb1eb (.gitignore logs), 378239f (set 2), 502fa9a (merge main, HEAD, clean), ecd026f (3 big mp4s removed).
- Git-ignored, not committed: `out/` (final mp4/txt), `work/`, `src/*.mp4` (`ege12.mp4` 116 MB, `noun2023.mp4` 93 MB, `video1678220992.mp4` 154 MB), `candidates/`.
- No evidence of a push; the three big files remain in earlier commits.
- Render: `./finish.sh <ids>` in background jobs; ASR check `heard.py` (machine-only, joins not judged by ear).

## NUMBERS
HEAD 502fa9a; ASR: Лаг–лож 88%, Чтобы 86%, rejected Привилегия 63%; big mp4s 116/93/154 MB (limit 100 MB on GitHub; keep >50 MB out of git).

## CONSTRAINTS AND BANS
- Video/sources >50 MB never in git; files in `artifacts/task-V-107/`, not `/tmp`.
- Drive updates = PATCH under old IDs; rejected old versions deleted (Drive deletions only after sending the «что удаляю» list); `lesson1..3` never deleted.
- Commit messages start «#V-107:» or «#V-101:».
- Bash calls under 120 s; tool name `Bash`; no bare `git stash`; don't restart Orchestra; don't publish to social networks; omit Zoom passcodes.
- If a push is rejected: rewrite unpushed branch history only after confirming with the orchestrator.
- Plus all standing user rules above (no rollback on alpha-8, nothing to #prod-91 without «да», don't touch /srv/stage_20, etc.).

## PEOPLE AND AGENTS
- `katya-work-orchestrator` (relays Katya; sole reporting line). Katya (client). Igor Bazhenov (deadline for «согласование тарифа»). Agent: `rilsy`.

## OPEN ITEMS AND NEXT ACTION
- Blocker: none. Next: read the orchestrator's reply; if Katya picks among 12–15 or asks for more reels, build with the same engine (`reels2.json` → `finish.sh`), start report with «СТАТУС ЗЕНИТ-42».
- V-101 feedback on `wedding_R.mp4` pending.
- Orchestrator's answer on the four-pointed stars option pending.
- Drive deletion: need «что удаляю» (name, ID) list first; nothing known to delete.
- Owed to the user: check `catalog_82.csv` for duplicates and report the count (path UNKNOWN); remind to ask Igor Bazhenov about the «согласование тарифа» deadline (by end of week); include the «МИРАЖ-41» vs «ОБСИДИАН-73» comparison table in the final message (variant content UNKNOWN).
