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
- Generation spend: $0. Image source order: Katya's files, then public domain, then generation (limit $1/day).

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

USER MESSAGES AND RAW TRANSCRIPT
Raw transcript: `/api/sessions/oge-russkiy/logs?scope=/home/kesha/katya-work`
1. [from:katya-work-orchestrator] Current #V-8: Катя забраковала колоду, её слова дословно: «Очень мелкий шрифт много текста много цветов нет картинок». Тебя перевели на Opus. Колоду надо пересобрать визуально, а не подкрутить. Контактный лист текущей версии: /tmp/v8-c.png, /tmp/v8-d.png.

Что должно получиться:
1. Шрифт. Основной текст не мельче 24 pt, заголовки от 36 pt, ключевые числа от 60 pt. Подписи-источники внизу можно мельче. Мелкий кегль на рендере = брак.
2. Текст. На слайде одна мысль и не больше ~25–30 слов. Всё, что не влезает, разносится на отдельные слайды (их может стать 30–40) или уходит в заметки докладчика. Таблицы на 8 строк, стены из 5 карточек и списки по 6 пунктов переделать в крупную инфографику.
3. Цвет. Максимум 2 акцентных цвета плюс фон и текст, взять из её мастер-макета. Никаких радуг «одна карточка — свой цвет».
4. Картинки. На каждом содержательном слайде крупная картинка или крупная инфографика, минимум треть площади. Порядок источников: (а) её файлы — мастер /home/kesha/katya-work/artifacts/task-6/inbox/Мастер-макет ИСПР.pptx (15 макетов, собирай слайды на них), её презентация «9 задание ЕГЭ.pptx» и photo_*.jpg там же; (б) общественное достояние с лицензией в licenses.json; (в) генерация — лимит $1 в сутки на весь проект.
5. Числа не трогать: они уже сверены с ФИПИ (38 баллов, 13 заданий, 235 мин, ГК 3/2/1/0, СК2 до 4).

Проверка: pptx + PDF, ты смотришь КАЖДЫЙ полноразмерный рендер. В отчёт приложи контактный лист и для каждого слайда минимальный кегль и число слов. Закоммить и доложи DONE.
2. [from:katya-work-orchestrator] Current #V-8: колода принята, осталась одна фактическая правка, слайд 12. По обобщённому плану СПЕЦ задание 9 — «грамматическая синонимия словосочетаний», 11 — «выразительные средства», 12 — «лексический анализ слова». Поэтому плитки «8–9 нормы» и «11–12 выразительность» неверны. Раздели так: 8 — нормы, 9 — словосочетания, 10 — смысл текста, 11 — выразительность, 12 — лексика. Если нужно, можно 7 плиток. Пересобери pptx и PDF, посмотри рендер слайда 12, закоммить и доложи DONE. Остальное не трогай.
3. [from:katya-work-orchestrator] Current #V-8: Катя прислала правки к новой колоде, её слова дословно: «Нет наглядности прям скриншотов из демоверсий и мини заданий плюс можно их ЕГЭ русского презентации взять ту схему разделов языкознания постепенно появляющуюся и мини задания надо на активность ученика чтоб не просто слушала в двух форматах так же делай и там на одном алгоритме немного наложился текст на круг».

Что нужно сделать, стиль и правила кегля/слов/палитры остаются прежними:
1. Скриншоты из демоверсии ОГЭ-2027 (PDF в artifacts/oge-russkiy/inbox/). На слайды заданий 1, 2–12 и 13 поставь настоящие вырезки из демоверсии: формулировку задания, кусок текста, бланк. Кадрируй крупно, чтобы читалось с экрана. Это фрагменты официального документа ФИПИ, источник подписать.
2. Мини-задания на активность ученика в двух форматах: (а) быстрый вопрос с ответом, который появляется по клику на том же слайде; (б) мини-задание в формате ОГЭ на вырезке или по мотивам демоверсии: ученик решает сам, ответ на следующем клике или слайде. По одному-два задания на каждый блок: изложение, 2–12, сочинение, грамотность. Ответы — только по ключам демоверсии или бесспорные, спорные классификационные ключи не делать.
3. Схема разделов языкознания с постепенным появлением. Взять из колоды ЕГЭ: сборщик .orchestra/tasks/V-3/build_deck.py, слайды 3–14 с поэлементным появлением, отчёт .orchestra/tasks/V-7/report.md. Выход: artifacts/struktura-ege/out/struktura-ege-2027.pptx. Вставить в колоду ОГЭ как вводный блок «из чего состоит язык → что проверяет ОГЭ», в палитре ИСПР.
4. На круговых алгоритмах текст наезжает на круг: слайд 7 («Пишем ключевые слова» у шага 2), проверь также слайд 19. Подписи вынести так, чтобы между ними и кругом был зазор.
5. Анимации проверить на уровне XML pptx (в PDF их не видно). В PDF отдельными страницами дать финальное состояние каждого слайда с появлением.

Выход: pptx + PDF. Посмотри каждый рендер, обнови контактный лист и отчёт, закоммить и доложи DONE. Ориентир — 2 часа.
4. [from:katya-work-orchestrator] Current #V-8: Катя уточнила пункт 2: «в двух форматах» — это pptx и PDF. Жёсткого деления мини-заданий на два типа нет, они могут быть разными: вопрос с ответом по клику, задание на вырезке из демо, «найди ошибку», «выбери вариант» и т. п. Выбирай формат, который подходит к блоку. Остальное задание прежнее.
5. [from:katya-work-orchestrator] #V-8, новая правка от Кати, дословно: «По итоговому тоже примеры». Речь об итоговом собеседовании (сейчас слайды 40–42). Сделай этот блок так же, как части 1–3.
- Крупные вырезки из демоверсии итогового собеседования 2027: текст для чтения вслух, задание пересказа с цитатой, карточка беседы и вопросы к ней, описание фото или монолог.
- 2–3 мини-задания с ответом по щелчку. Например: сколько баллов за чтение при 2 ошибках, куда вставить цитату, сколько минут на подготовку. Ключи бери только из критериев и документов ФИПИ по собеседованию.
- Остальные правила те же: кегль, слова, палитра, анимации проверить через check_anim.py.
- Если демоверсии собеседования-2027 нет в inbox, скачай с fipi.ru. Если не получится, возьми последний доступный год и напиши на слайде, какой именно.
На выходе pptx и PDF. Посмотри новые страницы в полном размере, закоммить, доложи DONE. Ориентир — 1 час.