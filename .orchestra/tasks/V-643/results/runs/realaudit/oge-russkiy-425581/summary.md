TASK STATE
- Task: #V-8, the deck «Структура ОГЭ по русскому языку 2027» built on Katya's ISPR master. Worker oge-russkiy, branch `task-V-8/oge-russkiy`.
- Phase: the last round (interview block) is finished, committed as 1a6a611 and reported DONE to katya-work-orchestrator. The delivery was QUEUED. No reply from the orchestrator yet.
- Rounds and their status:
  1. Full rebuild to 33 slides. Accepted.
  2. Fix of slide 12 (8 tiles). Merged to main as 0b740ea.
  3. Demo crops, mini-tasks, linguistics scheme, circle label fix. Commit 7a8b0ba.
  4. Interview block with demo crops and 3 mini-tasks. Commit 1a6a611.
- Current deck: 51 slides, PDF 51 pages. Minimum font 48 pt, at most 25 words per slide. check_anim.py: 14 animated slides, 29 clicks, 110 targets, 0 errors.

DECISIONS
- Canvas is 26.67×15″, so all font sizes are doubled: body ≥48 pt, titles 80 pt, key numbers ≥120 pt. Word limit is ≤30 per slide, source footer excluded. The builder fails if a rule is broken.
- Palette:
  - BORDO 732117
  - TINT E8D3BE
  - CREAM FCF9DC
  - INK 3D2B1F
- Fonts are Palatino / "Avenir Next Regular". The render substitutes P052 / Montserrat via /tmp/v8r/fonts.conf.
- Layout 6 «Правило + примеры» is used as a blank slide with showMasterSp=0. The logo is the master blob with alphaModFix 29742.
- Animations are hand-written `p:timing` XML with the Appear effect, one click per group. The PDF shows the final state of each animated slide.
- Mini-task answer keys come only from FIPI demo tables and criteria.
- The 2027 interview has no «пересказ с цитатой» task. Task 2 is «Беседа по тексту» with 5 questions, and the quote is in question 5. So I made no «куда вставить цитату» mini-task.
- Generation spend: $0 (round-1 instruction «Генерацию не используй» superseded by round-2 image order with $1/day limit; none used). Image source order: Katya's files, then public domain, then generation (limit $1/day).

FILES AND ARTIFACTS
- `.orchestra/tasks/V-8/build_deck.py` — the builder.
  - Adds DEMO_CROPS / demo_crop() for both demo PDFs, fit_pic, anim, choice.
  - Adds the scheme slides, the interview block and the text-fit checks.
  - Committed.
- `.orchestra/tasks/V-8/check_anim.py` — created, committed.
- `.orchestra/tasks/V-8/report.md` — updated through round 4, including the 51-slide table. Committed.
- `.orchestra/tasks/V-8/contact-sheet.png` — committed.
- `.orchestra/kb/master-ispr-kolody.md` and the index line in `.orchestra/kb/README.md` — committed.
- `CHANGELOG.md` — entries for the three V-8 rounds added. Committed.
- Gitignored outputs: `artifacts/oge-russkiy/out/{struktura-oge-russkiy-2027.pptx,.pdf,contact-sheet.png,slide-stats.json}`.
- Gitignored work files: `artifacts/oge-russkiy/work/render/p-01..51.png`, `artifacts/oge-russkiy/work/img/{demo/*,katya/*,katya/scheme/*,pd/*,licenses.json}`.
- Sources:
  - `artifacts/oge-russkiy/inbox/Русский язык ОГЭ 2027/РУ-9 ОГЭ 2027_ДЕМО.pdf`
  - `artifacts/oge-russkiy/inbox/Итоговое собеседование 2027/РУ-9_ДЕМО_итоговое_собеседование.pdf`
  - Master: `/home/kesha/katya-work/artifacts/task-6/inbox/Мастер-макет ИСПР.pptx`
  - EGE scheme source: `/home/kesha/katya-work/artifacts/struktura-ege/inbox/struktura-ege-2025-original.pptx`, slide 4.
- Nothing was published or sent to Katya.

COMMANDS AND TOOL OUTCOMES
- Build: `/tmp/venv-pptx/bin/python .orchestra/tasks/V-8/build_deck.py` → `OK: … (51 слайдов)`.
- Animation check: `/tmp/venv-pptx/bin/python .orchestra/tasks/V-8/check_anim.py artifacts/oge-russkiy/out/struktura-oge-russkiy-2027.pptx` → exit 0.
- Render: `ssh -o BatchMode=yes kesha@localhost 'bash /tmp/v8r/render.sh'` → PDF 51 pages, 1920×1080 pt.
- Contact sheet: `/tmp/venv-pptx/bin/python /tmp/v8r/sheet.py /tmp/v8r/sheet.png`.
- These /tmp scripts may not survive. The logic for recreating the render is in the V-8 report and the KB.
- ODP conversion (round 3) showed LibreOffice parses the animations: 101 anim:set, 26 on-click.

BLOCKER / NEXT
- No blocker. Next action: wait for the orchestrator's or Katya's feedback on the round-4 DONE. Merging is the orchestrator's job.

CONSTRAINTS
- Worker rules:
  - Edit only inside the worktree.
  - Commit before reporting DONE. Commit messages start with `V-8:` and end with the Co-Authored-By line.
  - Report through mcp__orchestra__send_message.
  - Do not push. Do not restart Orchestra.
- Do not publish or send anything to Katya without explicit approval.
- Do not change FIPI numbers: 38 points, 13 tasks, 235 min, ГК 3/2/1/0, СК2 max 4. All FIPI 2027 documents are drafts («ПРОЕКТ»).
- Only Opus or Luna workers. Image generation ≤ $1/day.
- Look at every new or changed full-size render before reporting.

OWNER & USER REQUIREMENTS (verbatim, all from katya-work-orchestrator relaying Katya)
- Original #V-8 (13:40 23.09): Katya's request: «А теперь сделай по фипи и тд презентацию по структуре ОГЭ по русскому используй картинки инфографику мои графические элементы». Deck «Структура ОГЭ по русскому языку 2027», pptx 16:9 + PDF for phone, for Katya (tutor) showing to 9th graders and parents. «Источники — только официальные документы ФИПИ ОГЭ-2027 по русскому» (ДЕМО, СПЕЦ, КОДИФ, plus Итоговое собеседование — допуск к ОГЭ). «Каждое число, критерий, время, количество заданий — со ссылкой на раздел/таблицу документа; ничего по памяти.» «Если документы помечены «ПРОЕКТ» — оговорка на титуле.» «Что изменилось в 2027» — только по тексту спецификации. Sources copied to artifacts/oge-russkiy/inbox/ (originally /tmp/fipi/ru_9_2027/).
- «Тяжёлые рендеры LibreOffice запускай через ssh -o BatchMode=yes kesha@localhost '...', имена файлов для soffice — ASCII.»
- Output: artifacts/oge-russkiy/out/struktura-oge-russkiy-2027.pptx and .pdf (outside git); script and report in .orchestra/tasks/V-8/ (in git). Report like V-4: structure by slides with sources, images with licenses, generation spend, what was checked. «Ничего никуда не публикуй и не отправляй.» Commit and report DONE with paths.
- Round 1 fixes (done): tasks 2–7 = 6×7 = 42 min, sum 90+42+10+33+60 = 235; title ovals; logo; empty cards; PD images (no generation at that stage).
- Katya rejected deck: «Очень мелкий шрифт много текста много цветов нет картинок». Rebuild visually on master ISPR (15 layouts): body ≥24 pt, titles ≥36, key numbers ≥60 (doubled on 26.67×15″ canvas); one idea per slide, ≤~25–30 words, overflow to separate slides or speaker notes; tables/card walls → large infographic; max 2 accent colors + background + text from her master; a large picture/infographic (≥1/3 area) on each content slide; image order: her files (master, «9 задание ЕГЭ.pptx», photo_*.jpg) → public domain with licenses.json → generation (limit $1/day for whole project). «Числа не трогать» (38 баллов, 13 заданий, 235 мин, ГК 3/2/1/0, СК2 до 4). Check: look at EVERY full-size render; report includes contact sheet, per-slide min font and word count.
- Slide 12 fix (round 2, done, merged): «8 — нормы, 9 — словосочетания, 10 — смысл текста, 11 — выразительность, 12 — лексика». «Остальное не трогай.»
- Katya round 3: «Нет наглядности прям скриншотов из демоверсий и мини заданий плюс можно их ЕГЭ русского презентации взять ту схему разделов языкознания постепенно появляющуюся и мини задания надо на активность ученика чтоб не просто слушала в двух форматах так же делай и там на одном алгоритме немного наложился текст на круг». Clarified: «в двух форматах» = pptx и PDF; mini-tasks are not rigidly two types (question with click answer, crop task, «найди ошибку», «выбери вариант»). Demo crops on tasks 1, 2–12, 13 with source caption; mini-tasks 1–2 per block (изложение, 2–12, сочинение, грамотность), answers only from demo keys or indisputable, «спорные классификационные ключи не делать»; linguistics scheme with gradual appearance from EGE deck (V-3 build_deck.py slides 3–14, V-7 report, artifacts/struktura-ege/out/struktura-ege-2027.pptx) as intro block; fix text overlapping circle on slides 7 and 19; check animations at XML level; PDF shows final state of animated slides.
- Katya round 4: «По итоговому тоже примеры» — interview block done same way (demo crops, 2–3 click mini-tasks, keys only from FIPI docs; if no 2027 demo, download from fipi.ru or state the year on slide). «Посмотри новые страницы в полном размере, закоммить, доложи DONE.»
- Original instruction: «Коммиты не трогай, просто сделай новые поверх.» (add new commits, do not rewrite).

RAW TRANSCRIPT: `/api/sessions/oge-russkiy/logs?scope=/home/kesha/katya-work`
- Deck slide numbering: interview block = slides 40–51 (43,45,48,49 crops; 44,46,47 mini-tasks). Delivery id da9b02a6-b043-4039-83e7-35fb3af08485 (QUEUED). Earlier commit for round 2: 0b740ea; round 3: 7a8b0ba.
- Worker rules (Do not push / only Opus or Luna) come from session setup, not journal; keep.
