**TASK STATE**
- Objective: deck «Структура ОГЭ по русскому языку 2027» for Katya (pptx 16:9 + PDF), task #V-8, built on her ISPR master layout.
- Latest status: the interview block «Итоговое собеседование» (slides 40–51) was built with demo crops and click-reveal mini tasks. The deck is now 51 slides, 51 PDF pages. Commit 1a6a611 was reported and DONE was sent to `katya-work-orchestrator` (delivery `da9b02a6-b043-4039-83e7-35fb3af08485`, state QUEUED).
- Waiting for the orchestrator's or Katya's reply. No evidence of any newer request.

**DECISIONS**
- The 2nd build replaced the 1st (23 slides) entirely, at Katya's request. Rules are unchanged:
  - main text ≥ 48 pt in the file (24 pt on a normal slide), ≤ 25–30 words per slide
  - only the master palette
  - one idea per slide
  - the build script fails on any violation
  - $0 spent on generation
- FIPI numbers (38 points, 13 tasks, 235 min, ГК 3/2/1/0, СК2 up to 4) are not to be changed.
- Slide 12 was split per the СПЕЦ general plan: 8 norms, 9 phrases, 10 text meaning, 11 expressiveness, 12 lexis.
- Interview block: the demo for 2027 was already in inbox. The "retelling with a quote" task does not exist in 2027 — task 2 is «Беседа по тексту» with five questions. The mini task «where to insert the quote» was skipped because no key exists in the documents.
- Interview mini tasks and their keys:
  - a mispronounced word → 0 points on Ч3 (slide 44)
  - preparation time 5 min (slide 46)
  - monologue minimum 10 sentences, no more than 3 min (slide 47)
  - slide 47 stands before the monologue card so the answer is not visible in advance.

**FILES AND ARTIFACTS**
- `.orchestra/tasks/V-8/build_deck.py`: rewritten and patched several times, committed.
- `.orchestra/tasks/V-8/report.md`: updated; per-slide table, sections «Правка после приёмки» and «Третья сборка», committed. Whether it was updated for the interview block: no evidence.
- `.orchestra/tasks/V-8/check_anim.py`: created (checks animation XML), committed.
- `.orchestra/tasks/V-8/contact-sheet.png` and `.orchestra/kb/master-ispr-kolody.md`: created, committed.
- `.orchestra/kb/README.md` and `CHANGELOG.md`: modified, committed.
- Deck outputs, all outside git:
  - `artifacts/oge-russkiy/out/struktura-oge-russkiy-2027.pptx`
  - `artifacts/oge-russkiy/out/struktura-oge-russkiy-2027.pdf`
  - `artifacts/oge-russkiy/out/contact-sheet.png`
  - `artifacts/oge-russkiy/work/render/p-*.png`
- Also present:
  - `artifacts/oge-russkiy/inbox/` (FIPI PDFs and txt)
  - `artifacts/oge-russkiy/work/img/licenses.json`
  - `artifacts/oge-russkiy/work/img/pd/` (Perov, Bogdanov-Belsky ×2, Gorky, chronicle, dictionaries, Shishkin)
  - `artifacts/oge-russkiy/work/img/katya/` (level, scales, `scheme/*`)
- Commits in order reported: 2a9b55e (rebuild on master), d0812c9 and d22f2c0 (slide 12), 7a8b0ba (demo crops, mini tasks, scheme, circle gaps), 1a6a611 (interview block).

**COMMANDS AND TOOL OUTCOMES**
- Build: `/tmp/venv-pptx/bin/python .orchestra/tasks/V-8/build_deck.py`. Last output was `OK … (51 слайдов)`.
- Render: `ssh -o BatchMode=yes kesha@localhost 'bash /tmp/v8r/render.sh'`. Last output was 51 pages and 1920×1080 pt. `/tmp/v8r/` may vanish, and `render.sh`, `sheet.py`, `fonts.conf` live only there.
- `check_anim.py` passed on the interview block; click slides 36, 44, 46, 48 reported "щелчков 1, порядок ok".
- I viewed slides 43–49 at full size, and the rest via the contact sheet.
- Not verified: no evidence the animations were played in real PowerPoint/Keynote. The PDF uses Montserrat instead of Avenir Next.

**BLOCKER / NEXT**
- No blocker. Next action: wait for feedback from `katya-work-orchestrator`. If asked to change anything, edit `build_deck.py`, rebuild, render, view the changed pages at full size, refresh the contact sheet and report, commit, then send DONE.
- Open caveats:
  - three "choose an option" slides have answer tiles at 22 % of the area, below the one-third target
  - the FIPI documents are marked «ПРОЕКТ»

**CONSTRAINTS**
- Nothing is published or sent to anyone (durable).
- Every number comes from FIPI documents, not from memory (durable).
- Heavy LibreOffice work goes through ssh to `kesha@localhost`, with ASCII file names (durable).
- Image order: Katya's files → Wikimedia PD with a license in `licenses.json` → generation (project limit $1/day, avoid).
- Mini-task keys come only from FIPI keys or criteria; no disputable classification tasks.
- Use they/them for anyone whose pronouns are unknown.

**USER MESSAGES AND RAW TRANSCRIPT**
Raw session transcript: `/api/sessions/SESSION/logs?scope=SCOPE` (SESSION and SCOPE values not available in context).

1. [#422824]
> #V-8. Сделай с нуля колоду «Структура ОГЭ по русскому языку 2027» (pptx 16:9 + PDF для телефона) для Кати — репетитора, которая будет показывать её ученикам 9 класса и родителям.
>
> Запрос Кати дословно: «А теперь сделай по фипи и тд презентацию по структуре ОГЭ по русскому используй картинки инфографику мои графические элементы».
>
> **Образец — колода #V-4 по ОГЭ-литературе, которую Катя уже приняла.** Прочитай `.orchestra/tasks/V-4/report.md` и `.orchestra/tasks/V-4/build_deck.py`, посмотри рендеры `artifacts/oge-literatura/work/render/p-*.png`. Тот же стиль, палитра, фирменная графика из `reference/brand-iskra/` (логотип, цифры, круг из пяти следов и др.), тот же уровень проверки (постраничный рендер и просмотр каждой страницы глазами, скрипт падает на ненайденном ресурсе). Переиспользуй код V-4.
>
> **Источники — только официальные документы ФИПИ ОГЭ-2027 по русскому:** `/tmp/fipi/ru_9_2027/Русский язык ОГЭ 2027/` (ДЕМО, СПЕЦ, КОДИФ; .txt рядом в `/tmp/fipi/ru_9_2027/`) и `/tmp/fipi/ru_9_2027/Итоговое собеседование 2027/` (допуск к ОГЭ — один-два слайда). /tmp может исчезнуть — сразу скопируй их в `artifacts/oge-russkiy/inbox/`. Каждое число, критерий, время, количество заданий — со ссылкой на раздел/таблицу документа; ничего по памяти. Если документы помечены «ПРОЕКТ» — оговорка на титуле. «Что изменилось в 2027» — только по тексту спецификации.
>
> **Ожидаемое содержание:** экзамен в числах, карта частей (изложение, тестовая часть, сочинение), каждое задание/блок с примером из демоверсии, критерии и баллы (как в документе), где теряют баллы и обнуления, время, что можно брать с собой, перевод в отметки если он есть в документах, чек-лист, финал. Инфографика — диаграммы баллов и времени, схемы, иконки. Порядок картинок: её графика → общественное достояние (Wikimedia PD, лицензии в licenses.json) → генерация (лимит проекта 1 $ в сутки на всех; лучше обойтись без неё).
>
> Тяжёлые рендеры LibreOffice запускай через `ssh -o BatchMode=yes kesha@localhost '...'`, имена файлов для soffice — ASCII.
>
> Выход: `artifacts/oge-russkiy/out/struktura-oge-russkiy-2027.pptx` и `.pdf` (вне git), скрипт и отчёт в `.orchestra/tasks/V-8/` (в git). Отчёт как у V-4: структура колоды по слайдам с источниками, картинки с лицензиями, траты на генерацию, что проверено. Ничего никуда не публикуй и не отправляй. Закоммить и сообщи мне DONE с путями. Катя ждёт, ориентир — около 2 часов; не укладываешься — скажи сразу.

2. [#423078]
> [from:katya-work-orchestrator] Current #V-8: посмотрела все 23 рендера и сверила с СПЕЦ. Отдавать Кате пока нельзя, нужны правки. Коммиты не трогай, просто сделай новые поверх.
>
> 1. **Фактическая ошибка на слайде 16.** Задания 2–7 — это шесть заданий по 7 минут, итого 42, а не 35 (СПЕЦ, обобщённый план: 7/7/7/7/7/7). Сумма 90+42+10+33+60 = **235**, то есть совпадает с общим лимитом. Исправь столбик, подпись «228», assert в скрипте и отчёт.
> 2. **Заголовочные овалы.** На всех содержательных слайдах текст заголовка начинается на левой кромке овала или за ней. Нужно, чтобы текст стоял внутри овала с полями, как в V-4, где ширина считается по шрифту.
> 3. **Титул.** Логотип «ИСКРА» наезжает на угол рамки. Слайд 23: подпись внизу налезает на логотип.
> 4. **Пустота и мелкий кегль.** Карточки на слайдах 5, 8, 12, 17, 21 наполовину пустые, текст примерно 9–10 pt. Пустые карточки Катя уже браковала (`.orchestra/kb/avito-kartochki-brak.md`). Нужен текст 13–15 pt, как в V-4, а карточки подогнать под содержимое или заполнить по делу.
> 5. **Картинки.** Катя прямо просила «картинки, инфографику». Сейчас из графики только фирменные элементы. Добавь иллюстрации из общественного достояния (Wikimedia, PD-old/PD-Art, лицензии в licenses.json), вот где они напрашиваются:
>    - портрет Горького к тексту для заданий 10–13;
>    - пейзаж леса (например, Шишкин) к тексту о лесе;
>    - миниатюра из летописи к заданиям 2–4, где речь о летописи;
>    - на слайде «что взять с собой» вместо круга из следов, который не несёт смысла, — изображение словаря или иконки.
>    Генерацию не используй.
>
> Потом пересобери, отрендери, просмотри каждую страницу и пришли мне DONE.

3. [#424261]
> [from:katya-work-orchestrator] Current #V-8: Катя забраковала колоду, её слова дословно: «Очень мелкий шрифт много текста много цветов нет картинок». Тебя перевели на Opus. Колоду надо пересобрать визуально, а не подкрутить. Контактный лист текущей версии: /tmp/v8-c.png, /tmp/v8-d.png.
>
> Что должно получиться:
> 1. Шрифт. Основной текст не мельче 24 pt, заголовки от 36 pt, ключевые числа от 60 pt. Подписи-источники внизу можно мельче. Мелкий кегль на рендере = брак.
> 2. Текст. На слайде одна мысль и не больше ~25–30 слов. Всё, что не влезает, разносится на отдельные слайды (их может стать 30–40) или уходит в заметки докладчика. Таблицы на 8 строк, стены из 5 карточек и списки по 6 пунктов переделать в крупную инфографику.
> 3. Цвет. Максимум 2 акцентных цвета плюс фон и текст, взять из её мастер-макета. Никаких радуг «одна карточка — свой цвет».
> 4. Картинки. На каждом содержательном слайде крупная картинка или крупная инфографика, минимум треть площади. Порядок источников: (а) её файлы — мастер /home/kesha/katya-work/artifacts/task-6/inbox/Мастер-макет ИСПР.pptx (15 макетов, собирай слайды на них), её презентация «9 задание ЕГЭ.pptx» и photo_*.jpg там же; (б) общественное достояние с лицензией в licenses.json; (в) генерация — лимит $1 в сутки на весь проект.
> 5. Числа не трогать: они уже сверены с ФИПИ (38 баллов, 13 заданий, 235 мин, ГК 3/2/1/0, СК2 до 4).
>
> Проверка: pptx + PDF, ты смотришь КАЖДЫЙ полноразмерный рендер. В отчёт приложи контактный лист и для каждого слайда минимальный кегль и число слов. Закоммить и доложи DONE.

4. [#424567]
> [from:katya-work-orchestrator] Current #V-8: колода принята, осталась одна фактическая правка, слайд 12. По обобщённому плану СПЕЦ задание 9 — «грамматическая синонимия словосочетаний», 11 — «выразительные средства», 12 — «лексический анализ слова». Поэтому плитки «8–9 нормы» и «11–12 выразительность» неверны. Раздели так: 8 — нормы, 9 — словосочетания, 10 — смысл текста, 11 — выразительность, 12 — лексика. Если нужно, можно 7 плиток. Пересобери pptx и PDF, посмотри рендер слайда 12, закоммить и доложи DONE. Остальное не трогай.

5. [#424695]
> [from:katya-work-orchestrator] Current #V-8: Катя прислала правки к новой колоде, её слова дословно: «Нет наглядности прям скриншотов из демоверсий и мини заданий плюс можно их ЕГЭ русского презентации взять ту схему разделов языкознания постепенно появляющуюся и мини задания надо на активность ученика чтоб не просто слушала в двух форматах так же делай и там на одном алгоритме немного наложился текст на круг».
>
> Что нужно сделать, стиль и правила кегля/слов/палитры остаются прежними:
> 1. Скриншоты из демоверсии ОГЭ-2027 (PDF в artifacts/oge-russkiy/inbox/). На слайды заданий 1, 2–12 и 13 поставь настоящие вырезки из демоверсии: формулировку задания, кусок текста, бланк. Кадрируй крупно, чтобы читалось с экрана. Это фрагменты официального документа ФИПИ, источник подписать.
> 2. Мини-задания на активность ученика в двух форматах: (а) быстрый вопрос с ответом, который появляется по клику на том же слайде; (б) мини-задание в формате ОГЭ на вырезке или по мотивам демоверсии: ученик решает сам, ответ на следующем клике или слайде. По одному-два задания на каждый блок: изложение, 2–12, сочинение, грамотность. Ответы — только по ключам демоверсии или бесспорные, спорные классификационные ключи не делать.
> 3. Схема разделов языкознания с постепенным появлением. Взять из колоды ЕГЭ: сборщик .orchestra/tasks/V-3/build_deck.py, слайды 3–14 с поэлементным появлением, отчёт .orchestra/tasks/V-7/report.md. Выход: artifacts/struktura-ege/out/struktura-ege-2027.pptx. Вставить в колоду ОГЭ как вводный блок «из чего состоит язык → что проверяет ОГЭ», в палитре ИСПР.
> 4. На круговых алгоритмах текст наезжает на круг: слайд 7 («Пишем ключевые слова» у шага 2), проверь также слайд 19. Подписи вынести так, чтобы между ними и кругом был зазор.
> 5. Анимации проверить на уровне XML pptx (в PDF их не видно). В PDF отдельными страницами дать финальное состояние каждого слайда с появлением.
>
> Выход: pptx + PDF. Посмотри каждый рендер, обнови контактный лист и отчёт, закоммить и доложи DONE. Ориентир — 2 часа.

6. [#424762]
> [from:katya-work-orchestrator] Current #V-8: Катя уточнила пункт 2: «в двух форматах» — это pptx и PDF. Жёсткого деления мини-заданий на два типа нет, они могут быть разными: вопрос с ответом по клику, задание на вырезке из демо, «найди ошибку», «выбери вариант» и т. п. Выбирай формат, который подходит к блоку. Остальное задание прежнее.

7. [#425016]
> [from:katya-work-orchestrator] #V-8, новая правка от Кати, дословно: «По итоговому тоже примеры». Речь об итоговом собеседовании (сейчас слайды 40–42). Сделай этот блок так же, как части 1–3.
> - Крупные вырезки из демоверсии итогового собеседования 2027: текст для чтения вслух, задание пересказа с цитатой, карточка беседы и вопросы к ней, описание фото или монолог.
> - 2–3 мини-задания с ответом по щелчку. Например: сколько баллов за чтение при 2 ошибках, куда вставить цитату, сколько минут на подготовку. Ключи бери только из критериев и документов ФИПИ по собеседованию.
> - Остальные правила те же: кегль, слова, палитра, анимации проверить через check_anim.py.
> - Если демоверсии собеседования-2027 нет в inbox, скачай с fipi.ru. Если не получится, возьми последний доступный год и напиши на слайде, какой именно.
> На выходе pptx и PDF. Посмотри новые страницы в полном размере, закоммить, доложи DONE. Ориентир — 1 час.