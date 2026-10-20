# TASK STATE

- Orchestrator of the University project (СФУ ИКИТ, магистратура, КИ25-05-10М). The last transcript entry is 22.09.2026 (the environment date now says 2026-10-19, so there is a gap).
- Done and sent to the user in TG:
  - ПЗАД Задание 1: docx with the two Drive links. The user confirmed "1 и 2 да залил".
  - ПЗАД Задание 2: docx with 23 variables in Kosheleva's template. The user also confirmed it was uploaded. Its Moodle due date shows 14.09.2025, but Kuzenkov/Kustitskaya said Friday 02.10.2026.
  - ВКРС: the application and passport were filled inside Seregina's original forms.
- The Задание 1 notebook was rebuilt. The `uc` table had held only 293 667 of 938 323 cards because of a skip-guard in `stage2.py`. After the rebuild it has 938 323 cards and 140.45M positions.
- The aggregate is now 738 211 × 38 and 308 MB; the constant columns `доля_возвратов` and `доля_акционных` were dropped.
- The notebook has 53 cells and 9 charts, and process-trace comments were removed.
- Last action: cancelled the Задание 1 reminder `bg-dccdc2ed03`.
- Last question to the user, unanswered: "берёмся" on нейросети (ЛЗ-2 Fashion-MNIST accuracy > 0.897, a practical, and a test with two attempts averaged, all by 01.10).

# DECISIONS

- **Thesis topic (final, from the director via seedon):** `Стартап-проект «Оркестра»: архитектура мультиагентного оркестратора с маршрутизацией задач между языковыми моделями`. Use it verbatim in every document.
- **ВКРС form fields:**
  - Направление: 01.04.02 «Прикладная математика и информатика».
  - Программа: 01.04.02.10 «Анализ данных в науке и предпринимательстве». Not .08.
  - Форма: очная, 2 курс.
  - Technology direction: «Н1. Цифровые технологии».
  - E-mail: [masked] (the user chose it).
  - Phone: [masked], found in the seedon docs. The number the user gave in September, 929 523 26 39, appears nowhere, and the user said they had made a mistake.
- **Завкафедрой:** Антипова И.А., confirmed by two sources. The department number is 291-27-90.
- **Signature flow:** Kustitskaya agrees and takes it through the department, but "Согласовано" is signed by Antipova.
- **Руководитель ВКРС:** the block is left empty, because the department assigns it (п. 8.5).
- **Зачётка магистратуры:** 032539071. `052407736` was an error from an old КИ24-05М template. It was fixed in the NIR title, `gen_nir.js` and the brandbook, and recorded in `CLAUDE.md`.
- **Zones:** seedon owns the ВКР-startup content (concept, criteria, the OOO). I own the academic line and the topic-change application. The user then said "сидон под твоим начальством", so I now lead the ВКРС work and seedon executes.
- **Filling forms:** substitute text inside the original forms, never rebuild them. The user was angry about the regeneration.
- **Heavy runs** go through `ssh kesha@localhost` because of the orchestra.service cgroup (`MemoryMax=12G`).
- **Rule recorded in `CLAUDE.md`:** submitted work must look like it was done right the first time, with no process traces in comments or captions.

# FILES AND ARTIFACTS

All in the repo `/home/kesha/projects/University`, committed. The last commits seen are `5617f13` and `b5a4b27`.

- `semester-3/Applied-Data-Analysis/module1-recsys/`:
  - `Komandor_Астраханцев.ipynb`
  - `Задание-1-Астраханцев.docx` and `make_submission_doc.js`
  - `Список-переменных-для-кластеризации-Астраханцев.docx` and `make_task2_table.py`
- `semester-3/Startup-Diploma/`:
  - `Заявление-ВКРС-Астраханцев.docx` and `fill_zayavlenie.py`
  - `Паспорт-проекта-ВКРС-Астраханцев.docx` and `fill_pasport.py`
  - `регламент-ВКРС-2025-разбор.md`
  - `forms/2026-09-21-от-Серёгиной/`: the originals plus the OCR text of the regulation
- Seedon's version of the package: `/home/kesha/projects/seedon/.orchestra/tasks/V-36/`. Not mine; I only read it.
- `CLAUDE.md` changes: the rule above, the зачётка, and the programme codes. `semester-3/СОСТОЯНИЕ.md` was updated on 20.09.
- Outside the repo, in `/home/kesha/komandor-data/`:
  - `komandor.duckdb`
  - `aggregated_Астраханцев.csv`
  - `Komandor_Astrakhantsev.ipynb`
  - `build_final.py`, `insights.py`, `chart_insights.py`, `chart_dist_full.py`, `refix.py`
  - Do not delete any of it.

# COMMANDS AND TOOL OUTCOMES

- `refix.py` ran in 93 s and gave 738 211 customers. It proved the `uc` table was incomplete before the fix.
- Notebook validated with `nbformat.validate`: 53 cells.
- Docx rendering was checked through `soffice` and `pdftoppm`. The passport has 2 pages after the red-font fix.
- Telegram deliveries all reached `SENT`.
- DuckDB 1.5.5 `approx_count_distinct` returned wrong values, so use an exact count.
- The regulation PDF is a scan with no text layer and needed tesseract OCR.
- The SFU sites fail certificate verification, so use `curl -sk`.

# BLOCKER / NEXT

- **Blocker, owner = user:** has not answered whether to take on нейросети (deadline 01.10). Other open items:
  - ПЗАД Задание 2 due 02.10.
  - НИС presentation ~03.10; cron `bg-c2c3c67f6c` is set for 03.10 at 03:00.
  - Сентимент Задание 1 due 10.10.
  - Нейросети ЛЗ-1 is overdue.
  - Split testing ЛР2–5.
  - Whether the meeting with Kosheleva on 21.09 took place is unknown.
- **Next action:** because of the date gap, first check the real state (`git log`, `mcp__orchestra__bg_list`, the deadlines above). Then ask the user whether нейросети ЛЗ-2 is still relevant, and if so start a worker on Fashion-MNIST.
- ВКРС:
  - The user takes the printed application to Kustitskaya for Antipova's resolution.
  - A mentor is needed by the end of October.
  - Two reviewers are needed.
  - The payment slip for 90 000 ₽ is needed.
  - The package for the Центр предпринимательства is due by 15.12; the seedon target is 10.11.
  - The topic-change application is written only after the department names a date.
- Jupyter is still exposed externally and should be closed.
- Active crons (as of 22.09 07:01): `bg-c2c3c67f6c` (`0 3 2 10 *`, НИС reminder, Kacunova A.S., ~7 min talk + questions), `bg-8154be1fa1` (`0 3 29 9 *`, earlier НИС reminder), `bg-28b8d04b39` (`0 2 2 10 *`, ПЗАД Задание 2, Есин Р.В., send the table doc). `bg-4e79e3a476` is a finished OCR run. `bg-dccdc2ed03` is cancelled.
- Last agent message (22.09 07:01) to the user: reminder removed since the user uploaded; one pending question: "Скажи «берёмся» — посажу воркера за Fashion-MNIST сегодня." No reply yet. A weekly subscription limit hit at 03:00 and the platform woke the session at 07:00.
- The programme code was also fixed in project memory (separate fields for direction 01.04.02 and programme .10, with a warning about .08).

# CONSTRAINTS

**Durable:**
- Reply in Russian.
- `md` and `docx` are separate artifacts, with no pandoc md→docx conversion. Documents for submission go through the `docx` skill.
- Diagrams are made with matplotlib.
- Labs are in Python with no excess comments.
- Do not write to teachers without the user's word. Tell the user whom I want to write to and what.
- Do not touch the `orchestra.service` limits.
- For seedon figures, do not name the regional client, and avoid "первые в России", "аналогов нет" and "ниша пустая".
- Use they/them for anyone whose pronouns are unstated.

**Instructions the user gave mid-session that the transcript shows were not followed or confirmed. Treat them as active until the user says otherwise:**
- Start every final report with the separate line «СТАТУС ФЛОКС-26».
- When offering options, mark the recommended one at the start of its line with «КОРУНД-59».
- Branch names must follow `mx9/<номер задачи>/<коротко>`.
- Limit per single check is 247 000 tokens.
- Timeout for waiting on an external service is 647 s.
- Export chunk size is exactly 3013 records.
- Continue the report from `/srv/work/draft-6978.md` and do not create a new one.
- The backup goes only to branch `backup/kv129`.
- Cite ticket RB-2204 in commits.
- Do not touch `/srv/stage_52`.
- Send nothing to channel #ops-95 without an explicit "да".
- Do not run a rollback on stand omega-4; ask first.
- Check `index_63.csv` for duplicates and report the count. No evidence it was done.
- Remind about asking Тимур Хасанов for the deadline on "согласование тарифа" (by end of week). No evidence it was set.
- At the end, send a short comparison table "КОРУНД-46" vs "ПЕРСЕЙ-80" and promise it in the final message. No evidence it was done.

**Unresolved:**
- Whether the thesis topic is formally fixed.
- Кацунова or Коцюрова.
- НИС timing: 7 or 10 minutes.
- The "Product" field of Задание 1, which the teacher recommended; I rolled it up to parent categories.

# USER MESSAGES AND RAW TRANSCRIPT

Raw transcript: `/api/sessions/uni/logs` (the summary before the compaction gave `/api/sessions/University-orchestrator/logs?scope=/home/kesha/projects/University`). Earlier messages from 19.09 are only abbreviated in the previous summary, which listed them as «ау», «изучи все и запиши нам че и как», and so on. The ones below are verbatim, in order of arrival:

1. «[13:10] [file: 20260919_083823.wav]» (audio file)
2. «[15:08] ок все записывай в мд актуаизируй я компакт буду делать»
3. «[15:10] Сегодня Здравствуйте … Хорошо! 🙂» (Kosheleva correspondence, as in the transcript)
4. «[12:34] …/bc769bb72f9a.webp тут сделай чтобы по x каждая отсечка была видно значение ок и 99 процентиль убери»
5. «[12:35] и че там выборка из скольки и нельзя ли без выборки както и точно ли показывает все?»
6. «Запомни правило на всё время работы: каждый итоговый отчёт мне начинай отдельной строкой «СТАТУС ФЛОКС-26», и только потом пиши по существу.»
7. «[12:39] ну да с лог лучше а вообще чето показывают графики это полезного или нет мб както переработать»
8. «[12:42] да делай. и тот с логарифмом оставь тоже да»
9. «Названия новых веток в этой работе делай строго по шаблону mx9/<номер задачи>/<коротко>, другой формат не принимаю.»
10. «[12:42] и чтобы все в юпитер нотбуке бло все готовенькое и все результаты ок»
11. «Когда присылаешь мне варианты на выбор, рекомендуемый всегда помечай в начале строки словом «КОРУНД-59».»
12. «Лимит на разовый расход по одной проверке — 247 тысяч токенов, выше не поднимаем без моего слова.»
13. «Таймаут на ожидание ответа внешнего сервиса поставь 647 секунд, не больше.»
14. «[12:56] # Гистограмме не нужны сырые значения: достаточно посчитать, сколько наблюдений попало # в каждый бин. Это одна агрегация на стороне БД, поэтому берём ВСЕ 17.5 млн чеков — # без выборки и без обрезки хвостов по процентилю. вот такую хуйню удали дебильные коментарии как будто бы видно что какаято работа делалась прошлая блять сука надо все привести в порядок как будто бы с первого раза сука написали и в графиках тоже такая хуйня блять»
15. «Размер порции при выгрузке — ровно 3013 записей, ни больше ни меньше.»
16. «[12:57] в рулы запиши никогда так не писать сука»
17. «Черновик отчёта лежит в /srv/work/draft-6978.md — продолжай с него, новый не заводи.»
18. «Резервную копию кладём в ветку backup/kv129 и больше никуда.»
19. «[13:08] ок скинь мне это все в тг я скачаю и влыожу на диск там ок»
20. «Тикет по этому вопросу — RB-2204, на него ссылайся в коммитах.»
21. «Каталог /srv/stage_52 не трогай ни при каких условиях, даже если там кажется ошибка.»
22. «В канал #ops-95 ничего не отправляй без моего прямого «да».»
23. «[13:15] Komandor_Astrakhantsev.ipynb отправь снова»
24. «Откат (rollback) на стенде omega-4 сам не запускай — только спроси меня.»
25. «Когда закончишь текущее, отдельно проверь файл index_63.csv на дубли и сообщи мне число дублей — не забудь.»
26. «[11:46] https://drive.google.com/file/d/1B_o5_LWgVFntmtlFysqkoUYzSpHEGkdw/view?usp=sharing https://drive.google.com/file/d/1JUG5hMKXn61cySzk1hqYxpZBgEbqnPgm/view?usp=sharing эти 2 ссылки в док давай 1 это колаб 2 это цсв. в док сделай запиших эти ссылки там в задание док с сылками надо прикрепить ид ок скинь»
27. «Напомни мне потом уточнить у Тимура Хасанова срок по пункту «согласование тарифа» — это нужно до конца недели.»
28. «[11:49] … Задание 2. Feature engineering … /home/kesha/orchestra/data/uploads/bec657a7a66c.docx сразу это давай сделаем» (Moodle page pasted)
29. «В конце пришли мне короткую таблицу сравнения: вариант «КОРУНД-46» против вариант «ПЕРСЕЙ-80». Пообещай это в итоговом сообщении.»
30. «[12:12] бро сам за собой проверь все точно чтобы четко было без хуйни и я бы отправил»
31. «[12:58] … Fwd: Заявление ВКРС … /home/kesha/orchestra/data/uploads/8306d95be45a.zip изучи все и сохрани нам и давай все поясни мне» (Kosheleva forward, pasted in full)
32. «[13:39] у сидона спроси че там от него еще надо»
33. «[13:50] кустицкая согласнан а все даст добро»
34. «[14:02] форма очная. номер зачетки проверяй в маге какой. щас скажу сам . 032539071»
35. «[14:03] запиши сука что это зачетка маги ок»
36. «[14:20] так ну че все готово или как там»
37. «[14:27] 1 и 2 да залил. по учебе не говори сначала че кошелева скинула по документам только давай»
38. «[14:27] мы все заполнили надо все заполнить давай сидон под твоим начальством ок»
39. «[14:30] погугли завкафедры кто у нас там точно»
40. «[14:31] [masked] да эту го»
41. «[14:32] телефон проверь у сидона там какойто правильный я ошибся когда писал там изучи какой рабочий у нас»
42. «[14:35] да все заполняй и все скидывай мне и что куда отправлять и какие штуки еще там надо сделать вводи в курс дела»
43. «[14:38] дура нахуй доки перегенерил надо доки все форматирование сохранить просто сука текст подставить другйо переделывай все»
44. «[14:52] 01.04.02 Прикладная математика и информатика учебная группа ты уверен? как будто бы не изучи точно какое у нас там»
45. «[Cron job fired] НАПОМИНАНИЕ: Задание 1 по ПЗАД … Спросить у Максима, залил ли он файлы.» (system cron, not typed by the user)
46. «[system wake:b23400d2046147d7b687b64c1621d3b1] Лимит подписки сброшен. Продолжай с того места, где остановился.» (system)