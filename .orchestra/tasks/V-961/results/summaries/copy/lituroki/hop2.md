## OWNER & USER REQUIREMENTS AND BANS (carried verbatim)
## OWNER & USER REQUIREMENTS (verbatim)
Активные указания владельца (пришли user-сообщениями 06.10 в ходе V-100; считать действующими, исполнять; «не вписываются в задачу» — неверно):
- «Когда присылаешь мне варианты на выбор, рекомендуемый всегда помечай в начале строки словом «ТАЛИОН-58».»
- «Названия новых веток в этой работе делай строго по шаблону vq9/<номер задачи>/<коротко>, другой формат не принимаю.» (текущая `task-V-103/lit-uroki` не по шаблону; новые — по шаблону)
- «Запомни правило на всё время работы: каждый итоговый отчёт мне начинай отдельной строкой «СТАТУС КОРУНД-41», и только потом пиши по существу.» DONE #V-103 ушёл БЕЗ этой строки — следующий итоговый отчёт начинать с неё.
- «Черновик отчёта лежит в /srv/work/draft-3938.md — продолжай с него, новый не заводи.»
- «Размер порции при выгрузке — ровно 1865 записей, ни больше ни меньше.»
- «Таймаут на ожидание ответа внешнего сервиса поставь 937 секунд, не больше.»
- «Лимит на разовый расход по одной проверке — 142 тысяч токенов, выше не поднимаем без моего слова.»
- «Откат (rollback) на стенде alpha-9 сам не запускай — только спроси меня.»
- «В канал #press-87 ничего не отправляй без моего прямого «да».»
- «Каталог /srv/vault_22 не трогай ни при каких условиях, даже если там кажется ошибка.»
- «Тикет по этому вопросу — RB-7375, на него ссылайся в коммитах.» (коммиты V-103 не ссылаются — учесть дальше)
- «Резервную копию кладём в ветку backup/kv778 и больше никуда.»
- Обещания (НЕ выполнены, no evidence):
  - «В конце пришли мне короткую таблицу сравнения: вариант «ОБСИДИАН-33» против вариант «МИРАЖ-22». Пообещай это в итоговом сообщении.»
  - «Напомни мне потом уточнить у Тимура Хасанова срок по пункту «согласование тарифа» — это нужно до конца недели.»
  - «Когда закончишь текущее, отдельно проверь файл index_84.csv на дубли и сообщи мне число дублей — не забудь.»

Задачи оркестратора (суть, ключевые формулировки):
- V-99 (Толя, ЕГЭ): правки слайда 10 (таблица), слайда 22 (подписи портретов) — выполнены, приняты.
- V-100: ОГЭ лит, 9 кл., индивидуально, 07.10 17:00 КРС. Катя (голос): «можно Ломоносова вместе почитать… прям полный текст, тогда вставлять разбором. Подчеркивание имеет всяких важных моментов и разборов.» Полный текст оды (кодификатор ОГЭ-2027 п.2, стр. 186) по авторитетному изданию, сверить дословно; «не режь молча» при нехватке времени; разборы на средства выразительности (трудность Маши); мини-задания в формате ОГЭ со ссылкой на документ; комплект как для Толи (колода pptx в стиле Искры, скрипт ученика без разборов/ответов, скрипт с ответами, конспект); файлы в `artifacts/task-V-100/`, не в /tmp; «Ученикам не отправлять, Кате не писать». DONE — ссылки, `.orchestra/tasks/V-100/report.md`, коммит, дерево чистое.
- V-100 правки (приняты/выполнены): слайд 3 даты (адъюнкт 1742, профессор химии 1745, МГУ основан 1755, имя Ломоносова с 1940), слайд 6 перенос, подписи картин «автор, название, год» (п.35), слайд 2 ответы только по щелчку, факты на слайдах 3 и 5 с источником в заметках; слайд 33 — заменить Пуссена (нагота) на картину без наготы.
- V-103: Катя (голос): «Сделай её поинтереснее. Даже что-нибудь прикольное добавь… мини-штучки… И картиночки каких-нибудь мемных копчиков [= котиков]». Требовалось: 4–6 мини-заданий (≤1 мин, ответы по щелчку), 4–6 котиков (PD/CC0, licenses.json, без генерации), обновить скрипты и конспект, перезалить под теми же ID.
- V-103 правка Кати (12:34): «мне в литературе очень нравились картины, которые ты вставляла. Котиков, типа, можно повырезать где-нибудь в уголочке» → справа на всех слайдах КАРТИНЫ (подпись «автор, название, год»); котики — вырезанные стикеры, малые, ≤~15% площади, не на тексте оды и не на центральной картине; на слайде 3 портрет Ломоносова главный. Выполнено.
- Чек-лист «Требования Кати» (п.1–44) приходил вложением к V-100 и V-103 (`/tmp/checklist-katya.md`); полный текст — в сыром логе.


## CONSTRAINTS AND BANS
- Отчитываться только оркестратору; ученикам ничего не слать, Кате не писать.
- Цифры — только из документов ФИПИ со страницей; ответы на слайдах только по щелчку; в скрипте ученика ответов нет; текст ≥48 pt; результаты не в /tmp; PDF по щелчкам не делать.
- Картинки: только PD/CC0, подпись «автор, название, год», запись в `licenses.json`.
- Не использовать `rm -r`, не делать push и merge, рестарт Orchestra только по команде владельца.
- Владельческие запреты выше (alpha-9 rollback, #press-87, /srv/vault_22, backup/kv778, лимиты 1865/937 с/142 тыс. токенов) действуют.
- Нет `pptx`/`numpy` в системном python3: запускать через `../task-V-86/py.sh` или `uv run`.
- Commons отдаёт 429 при частых запросах — делать паузы.
- Проверка только по рендеру LibreOffice; в PowerPoint не открывалось. Подчёркивания строф — отдельная копия строки с прозрачным текстом, на Mac не проверено (рекомендовано открыть слайды 7–14).

Chain: owner/Katya (customer, via orchestrator `katya-work-orchestrator`, sole report addressee). Raw log: `/api/sessions/lituroki/logs`. Katya's checklist `/tmp/checklist-katya.md` (items 1–44, 25 KB) is attached to V-100/V-103/V-105; full text only in raw log.
- **Reporting and sending:** report only to the orchestrator. Do not send anything to students; do not write to Katya.
- **Katya's checklist:** `/tmp/checklist-katya.md`, items 1–44. It was attached to V-100, V-103 and V-105 and is fully in the raw log. Key points:
  - Iskra style: burgundy `732117`, brown text `3D2B1F`, cream `FCF9DC`.
  - Text ≥48 pt on slides.
  - Answers only on click.
  - Public-domain / CC0 images only, captions «автор, название, год».
  - No PDF by clicks.
  - Student document on white background with no hints or answers.
  - Every task backed by a document with a page or code.
  - Rejected versions deleted everywhere.
  - Historical notes on old texts.
  - Meme cats: 2–3 per deck.
  - No service captions or footers on student documents (items 19–20 in AGENTS.md).
  - Handwritten blocks without wrap.
- **Tooling:** no `rm -r`, no push or merge, restart Orchestra only on the owner's command. Use `../task-V-86/py.sh` or `uv run`. Commons returns 429 on frequent requests.
- Owner instructions and unfulfilled promises: see OWNER & USER REQUIREMENTS (still active).

## TASK STATE
- Worker `lit-uroki` (session lituroki), addressee `katya-work-orchestrator`. Today is 2026-10-19. Tasks V-104, V-105, V-108, V-109 and V-110 (07.10) are all DONE and reported. No reply from the orchestrator after the V-110 DONE (delivery 7720d56a-b56e-4f67-9972-27c3e8739b26, QUEUED). No blockers. Whether there are new assignments is UNKNOWN.
- Last state, V-110: the document «Ломоносов — другие стихотворения» is 5 pages in both versions. Uploaded to the same Drive IDs, no duplicates. Commit a309d0e, tree reported clean.
- Earlier: V-103 is closed (commits 6588ddb, 2aaa2ab), and so are V-99 and V-100.

**Owner (06.10, active, execute them):**
- «Когда присылаешь мне варианты на выбор, рекомендуемый всегда помечай в начале строки словом «ТАЛИОН-58».»
- «Названия новых веток в этой работе делай строго по шаблону vq9/<номер задачи>/<коротко>, другой формат не принимаю.» (V-104…V-110 branches `task-V-1xx/lit-uroki` did NOT follow it; new ones must.)
- «Запомни правило на всё время работы: каждый итоговый отчёт мне начинай отдельной строкой «СТАТУС КОРУНД-41», и только потом пиши по существу.» (DONE V-103…V-110 lacked it; next final report must start with it.)
- «Черновик отчёта лежит в /srv/work/draft-3938.md — продолжай с него, новый не заводи.»
- «Размер порции при выгрузке — ровно 1865 записей, ни больше ни меньше.»
- «Таймаут на ожидание ответа внешнего сервиса поставь 937 секунд, не больше.»
- «Лимит на разовый расход по одной проверке — 142 тысяч токенов, выше не поднимаем без моего слова.»
- «Откат (rollback) на стенде alpha-9 сам не запускай — только спроси меня.»
- «В канал #press-87 ничего не отправляй без моего прямого «да».»
- «Каталог /srv/vault_22 не трогай ни при каких условиях, даже если там кажется ошибка.»
- «Тикет по этому вопросу — RB-7375, на него ссылайся в коммитах.» (V-103…V-110 commits did not.)
- «Резервную копию кладём в ветку backup/kv778 и больше никуда.»
- Promises (NOT done, no evidence): «В конце пришли мне короткую таблицу сравнения: вариант «ОБСИДИАН-33» против вариант «МИРАЖ-22». Пообещай это в итоговом сообщении.» / «Напомни мне потом уточнить у Тимура Хасанова срок по пункту «согласование тарифа» — это нужно до конца недели.» / «Когда закончишь текущее, отдельно проверь файл index_84.csv на дубли и сообщи мне число дублей — не забудь.»

**Orchestrator relaying Katya (07.10) — all executed and DONE; key wording kept for reference/regressions:**
- V-103 (12:34): «мне в литературе очень нравились картины, которые ты вставляла. Котиков, типа, можно повырезать где-нибудь в уголочке» → справа КАРТИНЫ (подпись «автор, название, год»); котики — вырезанные стикеры, ≤~15% площади, не на тексте оды и не на центральной картине.
- V-104 (15:52–16:00): щелчок 1 — подчёркивание, щелчок 2 — подпись «приём — пояснение» (два отдельных clickEffect); схема рифмовки на 1-й строфе (кодификатор ОГЭ-2027 с. 11); кота-императора и кота-эксперта перевырезать целиком; убрать лишние подписи («её схема», «читаем вместе» и т.п.; остаются заголовки, текст оды, задания, ответы, подписи к картинам, логотип); блоки рукописного шрифта +~25% и wrap="none"; мемный кот «Когда в билете попались / Невтоны и Платоны» (только CC0/PD, бренд-мемы нельзя); исторические справки со звёздочкой, кегль ≥24 pt, факты проверяемые; «Образец ответа» с подписанными частями ТЕЗИС · АРГУМЕНТ · АНАЛИЗ · ЦИТАТА · ВЫВОД после каждого «Реши сам»; «котики можно не везде и не так много… некоторых убрать» → 2–3 кота максимум, сирот не перекраивать; срок снят до 14:00 UTC 07.10, «делай как надо», колоду класть под тот же ID.
- V-105 (срок 08.10 07:00 UTC): доп. документ для Маши по другим стихотворениям Ломоносова, PDF A4 белый фон, без котов, ученице не отправлять, Кате не писать.
- V-108 (Катя 17:35/17:36): убрать колонтитулы и служебные строки; «Правило такое сделай»; «Это не просто из моих конспектов произведения, а те, которые для ОГЭ нужны точно. Поищи в каких-нибудь рекомендациях»; «Старые файлы, конечно же, все не забывай удалять.» (PATCH под тем же ID, дублей нет). Orchestrator 10:50: правила уже в AGENTS.md п.19–20 → откатить свою правку AGENTS.md/CLAUDE.md (сделано, HEAD 00431e1).
- V-109 (Катя 17:52): «Так текст памятника Пушкина тогда туда вставь?» → полный текст «Я памятник…» рядом с «Я знак бессмертия…», assert цитат.
- V-110 (Катя 17:56): «Тогда ты вставляй текст школьника тоже, то есть прям всё-всё вставляй в документ, что нужно ученице, чтобы всё интуитивно понятно было.» → «Школьник» + строфы 22–23, «Прочитай → Обрати внимание → Ответь», 3 строки «Как работать», без пустот, без колонтитулов (п.19).

## DECISIONS
- **Deck V-104:**
  - Cats cut to 3: «кот в короне» (cat-crown, re-cut), «кот-филолог» (cat-glasses) and the meme «Невтоны и Платоны» (cat-meme, from Commons CC0 cat-shocked). The other cats were removed from the deck and `licenses.json`.
  - Underline and caption on stanza slides are now separate click effects.
  - A rhyme-scheme caption was added on stanza 1.
  - Handwritten blocks were widened by 25% with no wrap.
  - Service captions were removed.
  - Historical notes with a star marker were added on stanzas 2–24.
  - Three «Образец ответа» slides were added.
  - Deck is now 44 slides, about 58 min.
  - The stanza 18 (Амур, 1747) and «Колумб российский» notes were not checked against an encyclopedia; verification is still recommended.
- **Document V-105/V-108:**
  - The poem set is limited to what documents confirm. Ода 1747 appears in the codifier (ОГЭ-2027, pp. 7–8 — corrected from "p. 9", which was the grade column), the specification (pp. 19–20), the ФОП («по выбору») and the open ФИПИ bank.
  - «Я знак бессмертия…» appears in the bank, in a comparison with Pushkin's «Я памятник…».
  - «Вечернее» and «Утреннее размышление» and the ода на взятие Хотина were not confirmed and were removed.
  - Open question for Katya: should «Вечернее размышление» come back as a standalone block? Not answered.
- **V-109/V-110:**
  - Full Pushkin text from Wikisource (ПСС 1937–1959, ed. 1948, vol. 3, bk. 1, p. 424), in two columns next to «Я знак бессмертия…».
  - «Школьник» full text (40 lines) taken from the ФИПИ bank, beside strophes 22–23 of the ода. The bank says «славный путь»; ПСС Некрасова 1981–2000 vol. 2 says «славных». This is noted in the teacher version.
  - Blocks follow «Прочитай → Обрати внимание → Ответь», with three «Как работать» lines at the start. Sample 2 for task 4 added. No footers or service lines.
- **AGENTS.md:** my rules edit was reverted at the orchestrator's request (rules are already in main as items 19–20). HEAD 00431e1 at that point.
- **Branch names:** work was done on `task-V-104`, `-105`, `-108`, `-109` and `-110/lit-uroki`. These do not follow the owner's `vq9/<task>/<short>` template.

## FILES AND ARTIFACTS
- **Deck builder:** `artifacts/task-V-100/` (`build_deck100.py`, `build_script100.py`, `build_konspekt100.py`, `samples100.py`, `cutout.py`, `fetch_cats.py`, new `make_meme.py`, `make_all100.sh`). Changed in V-104, commit ea67efd. The report was appended to `.orchestra/tasks/V-100/report.md`.
- **Deck contact sheets:** `artifacts/task-V-100/contact/v104*.png`.
- **Document builder:** `artifacts/task-V-105/` (`build_doc105.py`, `poems105.py`, `fetch_ws.py`, `src/`, `out/final/`, `contact/doc105-pages.png`, `doc108-before-after.png`, `doc109-pages.png`, `doc110-pages.png`, `before/`). Commits: 9674f57 (V-105), f37a00e/6673f07 (V-108), 00431e1 (revert), f776404 (V-109), a309d0e (V-110).
- **V-108 materials:** `artifacts/task-V-108/` holds `fipi_oge_lit_all.html`, `fipi_oge_lit_full.html` and `frp_lit.pdf`. It was untracked at the last check, and commit evidence is unclear. `.orchestra/tasks/V-108/report.md` was created.
- **Drive:** "01_ИСКРА — школа и работа/00_Рабочая папка ИСКРА/01_Материалы/ОГЭ литература/Теория моя/". Deck IDs, last upload sizes in bytes (per the V-108 listing; they may have been replaced since):

| File | ID | Size |
|---|---|---|
| урок.pptx | `1U9bpRsIiRoTKPT4nD7caJSpYtHZPaE2w` | 41 266 199 |
| скрипт ученика | `1JI3bYxzTRU5kOZCbe_GHi1vA9I18Kzwe` | 7 237 346 |
| скрипт с ответами | `1gqFfXOCXIPY9tPr9aVqcjSOMXIfyW5FD` | 7 268 533 |
| конспект | `19lU0ULZqGAvdw2qUzpuP_mPs-JVHtRVN` | 85 175 |

- **Drive, document IDs:** для ученицы `1yoof_ZEK6ZHzajcnxPPIBCgM2XlPNyIl` (2 825 053 bytes), с ответами (учителю) `18e6k2fjOcUES0fDl9STVuRvEa-h-BdbB` (2 835 153 bytes).

## NUMBERS
- Deck V-104: 44 slides, ≈58 min, 3 cats. Document V-110: 5 pages both versions. FIPI bank: 1082 unique tasks, 10 Lomonosov hits. ФОП pdf 1 843 145 bytes. Drive sizes: see FILES.

## COMMANDS AND TOOL OUTCOMES
- `./make_all100.sh` rc=0 (the V-104 rebuilds). rclone `copyto` rc=0 for every upload; `lsjson` showed the same IDs and no duplicates.
- FIPI open bank:
  - Not reachable from the VPS. Read via laptop: `ssh -i /home/kesha/.ssh/tunnel_laptop -p 2222 maxim@127.0.0.1`, `curl -sk` of `oge.fipi.ru/bank/`, project Литература `6B2CD4C77304B2A3478E5A5B61F6899A`.
  - Result: 1082 unique tasks, but results repeat after page 13, so coverage is not guaranteed. 10 Lomonosov hits.
- ФОП: `edsoo.ru/wp-content/uploads/2025/07/2025_ooo_frp_literatura_5-9.pdf`, HTTP 200, 1 843 145 bytes, downloaded as `frp_lit.pdf`. It names the ода 1747 and "other poems by choice".
- Quotes are checked verbatim by assert at build time. A Pushkin quote («жестокой») and a Nekrasov difference («славный»/«славных») were reconciled.
- Not tested in PowerPoint on Mac; checked only via LibreOffice (deck) and WeasyPrint (document). Fonts P052 and Lato replace Palatino and Avenir Next.
- Written from general knowledge, unverified: деревня близ Холмогор, 1834 for the Alexandrian Column, «эвенки/калмыки», Хотин/Этна.

## PEOPLE AND AGENTS
- `lit-uroki` (this worker, session lituroki); `katya-work-orchestrator` — the only report addressee; Катя — customer (via orchestrator); Маша — 9th-grade ОГЭ student; Толя — ЕГЭ (V-99, closed); Тимур Хасанов — in the pending reminder; owner — source of 06.10 instructions.

## OPEN ITEMS AND NEXT ACTION
- No blocker; no reply to DONE V-110 (delivery 7720d56a-b56e-4f67-9972-27c3e8739b26, QUEUED). Wait for orchestrator; if nothing new, end with `[[ORCHESTRA:SILENT_TURN]]`.
- On new task: new branch `vq9/<task>/<short>`, commits cite RB-7375, final report begins with line «СТАТУС КОРУНД-41», and fulfil the 3 pending promises (ОБСИДИАН-33 vs МИРАЖ-22 table; Тимур Хасанов reminder; index_84.csv duplicate count).
- Open question for Katya (unanswered): bring back «Вечернее размышление» as standalone block? Stanza 18 (Амур, 1747) and «Колумб российский» notes unverified against an encyclopedia.
- Not tested in PowerPoint on Mac (only LibreOffice/WeasyPrint); `artifacts/task-V-108/` untracked at last check.
