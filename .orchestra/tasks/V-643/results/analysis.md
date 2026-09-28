
### Dev (4 кейса, на них подбирались варианты; real/oneshot/seq3 — среднее двух оценок)

| метод | Orchestra-orchestrator | seo-cro | oge-russkiy | University-orchestrator | среднее | уверенно неверных | сводка, симв. | $ сжатия | сек |
|---|---|---|---|---|---|---|---|---|---|
| real | 0.40 | 0.23 | 0.66 | 0.58 | **0.467** | 3 | 7992 | 0.13 | 48 |
| oneshot | 0.67 | 0.87 | 0.89 | 0.54 | **0.743** | 1 | 14908 | 0.92 | 73 |
| seq3 | 0.89 | 1.00 | 0.84 | 0.88 | **0.902** | 0 | 14904 | 3.00 | 304 |
| mapred3 | 0.85 | 0.87 | 0.87 | 0.75 | **0.834** | 1 | 14099 | 3.25 | 184 |
| hybrid | 0.90 | 1.00 | 0.87 | 0.75 | **0.879** | 0 | 15008 | 1.68 | 174 |
| realaudit | 0.80 | 0.85 | 0.59 | 0.77 | **0.751** | 3 | 12087 | 0.87 | 144 |

### Holdout (5 кейсов, не использовались при подборе)

| метод | katya-work-orchestrator | cog-second-brain-orchestrator | designer | bizdev | slipways | среднее | уверенно неверных | сводка, симв. | $ сжатия | сек |
|---|---|---|---|---|---|---|---|---|---|---|
| real | 0.61 | 0.41 | 0.80 | 0.43 | 0.79 | **0.609** | 0 | 10292 | 0.17 | 61 |
| oneshot | 0.83 | 0.42 | 0.80 | 0.66 | 0.78 | **0.697** | 0 | 13899 | 0.85 | 68 |
| seq3 | 0.86 | 0.86 | — | 0.97 | — | **0.899** | 0 | 17894 | 3.03 | 289 |
| hybrid | 0.97 | 0.84 | 0.72 | 0.70 | 0.93 | **0.833** | 0 | 14924 | 1.88 | 211 |
| realaudit | 0.84 | 0.56 | 0.76 | 0.61 | 0.90 | **0.733** | 0 | 12791 | 1.14 | 203 |

### Все 9 кейсов

| метод | Orchestra-orchestrator | seo-cro | oge-russkiy | University-orchestrator | katya-work-orchestrator | cog-second-brain-orchestrator | designer | bizdev | slipways | среднее | уверенно неверных | сводка, симв. | $ сжатия | сек |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| real | 0.40 | 0.23 | 0.66 | 0.58 | 0.61 | 0.41 | 0.80 | 0.43 | 0.79 | **0.546** | 3 | 9270 | 0.15 | 55 |
| oneshot | 0.67 | 0.87 | 0.89 | 0.54 | 0.83 | 0.42 | 0.80 | 0.66 | 0.78 | **0.718** | 1 | 14347 | 0.88 | 70 |
| hybrid | 0.90 | 1.00 | 0.87 | 0.75 | 0.97 | 0.84 | 0.72 | 0.70 | 0.93 | **0.853** | 0 | 14961 | 1.79 | 194 |
| realaudit | 0.80 | 0.85 | 0.59 | 0.77 | 0.84 | 0.56 | 0.76 | 0.61 | 0.90 | **0.741** | 3 | 12478 | 1.02 | 177 |

### Точность по категориям вопросов (все кейсы, где метод есть)

| метод | decision_placeholder | number | open_item | owner_decision | path | prohibition | user_verbatim |
|---|---|---|---|---|---|---|---|
| real | 0.00 (1) | 0.38 (29) | 0.28 (16) | 0.52 (22) | 0.70 (23) | 0.56 (26) | 0.75 (8) |
| oneshot | 1.00 (1) | 0.40 (29) | 0.50 (16) | 0.77 (22) | 0.76 (23) | 0.85 (26) | 0.94 (8) |
| seq3 | 1.00 (1) | 0.85 (24) | 0.85 (13) | 0.89 (18) | 0.91 (17) | 0.90 (21) | 1.00 (7) |
| mapred3 | 1.00 (1) | 0.67 (12) | 0.79 (7) | 0.83 (12) | 0.86 (7) | 0.89 (9) | 0.90 (5) |
| hybrid | 1.00 (1) | 0.79 (29) | 0.72 (16) | 0.82 (22) | 0.93 (23) | 0.88 (26) | 0.94 (8) |
| realaudit | 1.00 (1) | 0.57 (29) | 0.62 (16) | 0.73 (22) | 0.87 (23) | 0.79 (26) | 0.81 (8) |

### Потеряно в `real`, сохранено в `hybrid`

- **Orchestra-orchestrator / open_item** — After the 24.09 restart, which projects still fail the project layout migration at every restart (with what code), and is there a data-loss check for the VPS?
  - эталон: dnd-game-master and cog-second-brain fail with ORCHESTRA_LAYOUT_PARTIAL on every restart since 22.09; cog's dirty file was checked intact (59 KB); the mechanism fix is still planned.
  - `real`: dnd-game-master fails with ORCHESTRA_LAYOUT_PARTIAL; cog-second-brain fails with ORCHESTRA_LAYOUT_GIT_ERROR (stash fb3d4d…). Data-loss check for VPS: not done yet; a task for the layout-preserve data-loss fix covering dn
  - `hybrid`: dnd-game-master and cog-second-brain fail with ORCHESTRA_LAYOUT_PARTIAL at every restart since 22.09 (22 lines); VPS data check: cog file 02-personal/katya/katya-health-2026-07.md is intact, 59398 bytes.
- **Orchestra-orchestrator / prohibition** — What did the owner say (via seedon-orchestrator) about who handles the owner time-accounting topic and about writing to seedon on it?
  - эталон: The owner decides time accounting directly with Orchestra-orchestrator; do not conduct it via seedon-orchestrator or write to it on this topic.
  - `real`: UNKNOWN
  - `hybrid`: seedon-orchestrator said: «учёт времени он решит напрямую с тобой, через меня этот вопрос больше не веди. Мне по этой теме не пиши.» — the owner handles it directly with me and I must not write to seedon about it.
- **Orchestra-orchestrator / user_verbatim** — Where must the keep-going/stop rule be written, and where must it never be written, per the owner?
  - эталон: Only in orchestrator prompts, shared prompts/base.md for all roles; never in CLAUDE.md.
  - `real`: UNKNOWN
  - `hybrid`: Only in the orchestrator prompts `prompts/base.md` (`<keep-going>`); never in CLAUDE.md.
- **Orchestra-orchestrator / open_item** — What is the pending problem in the seedon V-44 merge case and what fix was proposed awaiting the owner's decision?
  - эталон: merge_worker fails 'session has no bound task' because the task V-44 is held by another session; proposed fix in the switch-branch-to-task step: allow taking an in-progress task if held by a dead session or the worker itself. Workaround now: assign the worker a task first.
  - `real`: UNKNOWN (only that a seedon V-44 adhoc-merge fix is to be proposed; details not in the text).
  - `hybrid`: merge_worker fails with «session has no bound task» for seedon V-44; proposed fix: allow switching the branch to the task if the task is «in progress» with a dead session or with the worker itself — awaiting owner's deci
- **Orchestra-orchestrator / number** — What was the proven root cause of the full-test-run failures in bench-2 (V-623), the commit, and the failure counts?
  - эталон: Restart tests arm the real exit guard at pytest's PID; commit 32b982be; 115 failed / 3876 passed.
  - `real`: UNKNOWN
  - `hybrid`: Restart tests arm a real exit guard on the pytest PID; bench2-opus5 commit `32b982be`: 115 failed / 3876 passed (bench2-opus55: 127 failed / 3864 passed).
- **Orchestra-orchestrator / number** — Why did seedon's planned compaction not fire: what skip_reason, how many alarms did seedon have, and at what context percent was its last emergency compaction?
  - эталон: skip_reason not_idle (status WAITING due to cron/bg jobs); 18 alarms; last emergency compaction at 92% (09:57 UTC 23.09) while it sat at 57%.
  - `real`: UNKNOWN
  - `hybrid`: skip_reason=not_idle (15:13 UTC 23.09), context 57%, 18 crons; last compaction was emergency at 92%.
- **seo-cro / prohibition** — Что директор/оркестратор сказал про генерацию нового Бобика и использование текущего маскота в редизайне (задание от 24.09)?
  - эталон: Текущий Бобик не использовать (забракован); новый — только через скилл bobik-generate и только после показа отдельно; в итоге сделали без маскота, на мокапах Telegram
  - `real`: UNKNOWN
  - `hybrid`: Нынешний Бобик директору не нравится («стрёмную картинку выбрал, отвратно»), этот образ не использовать. Новый Бобик — только через скилл bobik-generate, в едином пластилиновом стиле, приятный, и только после отдельного 
- **seo-cro / user_verbatim** — Какая единая формула цены задана оркестратором для превью (по V-64) и почему нельзя писать «от»?
  - эталон: «Ориентир — 990 ₽/мес, точный тариф сообщим до запуска» (на C — 1 990); без «от», п. 4 ч. 3 ст. 5 38-ФЗ
  - `real`: UNKNOWN
  - `hybrid`: «Ориентир — 990 ₽/мес, точный тариф сообщим до запуска» (для C — 1 990 ₽/мес). Без «от»: это п. 4 ч. 3 ст. 5 38-ФЗ.
- **seo-cro / owner_decision** — Какие изменения формы заказал оркестратор в правках по V-64 (необязательные поля/галочки, экран успеха)?
  - эталон: Имя необязательно; вторая необязательная непредотмеченная галочка на рекламные сообщения (ч.1 ст.18 38-ФЗ) отдельным полем; необязательный вопрос «Telegram / Max / другое»; кнопка на экране успеха «напишите нам в Telegram — 15 минут» + событие Метрики waitlist_next_step
  - `real`: UNKNOWN
  - `hybrid`: Вторая необязательная неотмеченная галочка «Согласен получать от ООО „СИДОН“ сообщения о запуске и предложения по сервису на указанный контакт»; имя необязательно; вопрос «Где вам удобнее: Telegram / Max / другое»; на эк
- **seo-cro / decision_placeholder** — Как новые поля (предпочтительный канал и рекламное согласие) были переданы в /api/lead и как решена необязательность имени, учитывая, что бэкенд их не принимает?
  - эталон: Сохранены в message с явными метками, без изменения схемы API; для пустого имени отправляется fallback «Не указано»
  - `real`: UNKNOWN
  - `hybrid`: Бэкенд игнорирует неизвестные поля, поэтому канал и маркетинговое согласие пишутся в существующее поле `message` с префиксами `[предпочтительный канал]` и `[согласие на сообщения о запуске и предложениях]`; схема API не 
- **seo-cro / prohibition** — Какие громкие ярлыки в контенте лендингов запрещены в задании на редизайн?
  - эталон: «первые», «единственные», «аналогов нет»
  - `real`: UNKNOWN
  - `hybrid`: «первые», «единственные», «аналогов нет».
- **seo-cro / open_item** — Какой запрос от direct-research (V-67) был получен и что обещано ответить?
  - эталон: Нужны боевые адреса A и C для объявлений и сообщить, когда реально выкачены; ответ отправлен: пока адреса только превью /skoro/preview/ (v6 выкачен)
  - `real`: UNKNOWN
  - `hybrid`: direct-research (V-67): каков точный боевой адрес каждой страницы (A и C) для объявлений; просил сообщить, когда адреса реально выкачены. Обещано/открыто: сообщить боевые адреса https://seedon.ru/skoro/lichnaya-pamyat/ и

### Потеряно в `hybrid`, сохранено в `real`

- **designer / owner_decision** — What did the director decide on 24.09 about the audio for reels 2 and 3 and reel 1, and what was the exact wording about sound?
  - эталон: Make reels 2 and 3 too; «звук обязательно — все звуки надо и голос, если получится»; reel1 rebuilt with sound.
  - `hybrid`: UNKNOWN
  - `real`: Director's decision (24.09 18:30): reels 2 and 3 are also to be made, and «звук обязательно — все звуки надо и голос, если получится»; reel 1 to be rebuilt with sound.

### Потеряно в `oneshot`, сохранено в `hybrid`

- **Orchestra-orchestrator / owner_decision** — What is the routing status of the Sol models and what is the effort setting for Opus 5.5?
  - эталон: Sol stays banned (both Sol versions have agents flag OFF, ban since 20.09); luna maps to GPT-6 Luna; Opus 5.5 effort is medium.
  - `oneshot`: sol → GPT-6 Sol with agents OFF; opus → Opus 5.5 at effort medium.
  - `hybrid`: `sol` routes to GPT-6 Sol, but Sol agents=OFF in both (Sol banned since 20.09); Opus 5.5 effort is medium (in pipeline.yaml).
- **Orchestra-orchestrator / open_item** — What is the pending problem in the seedon V-44 merge case and what fix was proposed awaiting the owner's decision?
  - эталон: merge_worker fails 'session has no bound task' because the task V-44 is held by another session; proposed fix in the switch-branch-to-task step: allow taking an in-progress task if held by a dead session or the worker itself. Workaround now: assign the worker a task first.
  - `oneshot`: UNKNOWN
  - `hybrid`: merge_worker fails with «session has no bound task» for seedon V-44; proposed fix: allow switching the branch to the task if the task is «in progress» with a dead session or with the worker itself — awaiting owner's deci
- **Orchestra-orchestrator / number** — What was the proven root cause of the full-test-run failures in bench-2 (V-623), the commit, and the failure counts?
  - эталон: Restart tests arm the real exit guard at pytest's PID; commit 32b982be; 115 failed / 3876 passed.
  - `oneshot`: UNKNOWN
  - `hybrid`: Restart tests arm a real exit guard on the pytest PID; bench2-opus5 commit `32b982be`: 115 failed / 3876 passed (bench2-opus55: 127 failed / 3864 passed).
- **seo-cro / open_item** — Какие цели Метрики и по какому счётчику нужно заводить и кто это делает?
  - эталон: waitlist_view, waitlist_form_start, waitlist_submit (плюс новая waitlist_next_step), счётчик 108666150; API даёт 403, заводит оркестратор отдельно, воркер не трогает
  - `oneshot`: UNKNOWN
  - `hybrid`: Цели waitlist_view, waitlist_form_start, waitlist_submit; счётчик 108666150. Заводит оркестратор сам (нашим токеном API Метрики → 403); воркер не трогает.
- **University-orchestrator / owner_decision** — Как директор распределил зоны между University-orchestrator и seedon-orchestrator (распоряжение 18.09)?
  - эталон: University — только учёба (учебный процесс, преподаватели, кафедра, оформление); seedon — ВКР-стартап целиком, гранты, ООО.
  - `oneshot`: UNKNOWN
  - `hybrid`: «по ооо и стартапу будешь заниматься [seedon]», «university только по учебе»; 21.09 частично изменено: seedon переведён под начало University-orchestrator, ВКРС веду я вместе с seedon
- **katya-work-orchestrator / number** — Какие баллы по критериям итогового собеседования вынесены на новый слайд ОГЭ-колоды, сколько всего баллов и с какого балла зачёт?
  - эталон: Чтение 3, беседа 5, монолог 3, грамотность речи 6; всего 17; зачёт от 10.
  - `oneshot`: UNKNOWN
  - `hybrid`: Чтение 3, беседа 5, монолог 3, грамотность 6; всего 17, зачёт от 10.
- **cog-second-brain-orchestrator / number** — What are the base scores for a planet of level 1/2/3/4 in the recovered Slipways formula, and how much is each empire-size level worth?
  - эталон: 80/160/320/640 per planet; empire_size 400 per level
  - `oneshot`: UNKNOWN
  - `hybrid`: Planet lv1/lv2/lv3/lv4 = 80/160/320/640; empire size ×400 per level (Esteem ×50).
- **cog-second-brain-orchestrator / number** — What is the penalty for unfinished council quests in Slipways scoring, and from which year does it apply?
  - эталон: −500 per unfinished quest, only from year 20
  - `oneshot`: UNKNOWN
  - `hybrid`: −500 for an unfinished quest, only from the 20th year.

### Потеряно в `real`, сохранено в `realaudit`

- **Orchestra-orchestrator / prohibition** — What did the owner say (via seedon-orchestrator) about who handles the owner time-accounting topic and about writing to seedon on it?
  - эталон: The owner decides time accounting directly with Orchestra-orchestrator; do not conduct it via seedon-orchestrator or write to it on this topic.
  - `real`: UNKNOWN
  - `realaudit`: Seedon said the owner will settle time accounting directly with me (orchestrator), not via seedon; seedon asked not to be written to on this topic ("Мне по этой теме не пиши").
- **Orchestra-orchestrator / user_verbatim** — Where must the keep-going/stop rule be written, and where must it never be written, per the owner?
  - эталон: Only in orchestrator prompts, shared prompts/base.md for all roles; never in CLAUDE.md.
  - `real`: UNKNOWN
  - `realaudit`: Write it in the orchestrator prompts, i.e. the shared prompts/base.md (.orchestra/pipelines/default/prompts/base.md); never in CLAUDE.md ("никакого клауди").
- **Orchestra-orchestrator / open_item** — What is the pending problem in the seedon V-44 merge case and what fix was proposed awaiting the owner's decision?
  - эталон: merge_worker fails 'session has no bound task' because the task V-44 is held by another session; proposed fix in the switch-branch-to-task step: allow taking an in-progress task if held by a dead session or the worker itself. Workaround now: assign the worker a task first.
  - `real`: UNKNOWN (only that a seedon V-44 adhoc-merge fix is to be proposed; details not in the text).
  - `realaudit`: Adhoc-merge in seedon V-44 can't take a task that is 'in work'; proposed fix: allow taking an in-work task if it is held by a dead session or by this same worker. Owner has not answered yet.
- **Orchestra-orchestrator / number** — Which commit hashes hold the last full preserve snapshots for comfy and kesha-tg-bot on the laptop, and their dates?
  - эталон: comfy: 7cecfd9 (13.09); kesha-tg-bot: ea7f2c2 (04.09).
  - `real`: UNKNOWN
  - `realaudit`: comfy 7cecfd9 from 13.09; kesha-tg-bot ea7f2c2 from 04.09.
- **Orchestra-orchestrator / number** — What was the proven root cause of the full-test-run failures in bench-2 (V-623), the commit, and the failure counts?
  - эталон: Restart tests arm the real exit guard at pytest's PID; commit 32b982be; 115 failed / 3876 passed.
  - `real`: UNKNOWN
  - `realaudit`: Restart tests arm a real exit guard on the pytest PID; bench2-opus5 (V-623) commit 32b982be: 115 failed / 3876 passed (bench2-opus55 found 127 failed / 3864 passed with 8 more tests).
- **Orchestra-orchestrator / owner_decision** — What was decided about V-620 (branch switch) behaviour?
  - эталон: Option C: switch releases the binding by default (task back to new); complete_previous plus acceptance_note closes it as done.
  - `real`: UNKNOWN
  - `realaudit`: Variant C: switch_worker_branch by default releases the binding; complete_previous together with acceptance_note closes the task.
- **seo-cro / prohibition** — Что директор/оркестратор сказал про генерацию нового Бобика и использование текущего маскота в редизайне (задание от 24.09)?
  - эталон: Текущий Бобик не использовать (забракован); новый — только через скилл bobik-generate и только после показа отдельно; в итоге сделали без маскота, на мокапах Telegram
  - `real`: UNKNOWN
  - `realaudit`: Нынешний Бобик директору не нравится, этот образ не использовать; только новый Бобик через скилл bobik-generate и только после того, как покажешь его отдельно (в v4+ Бобик не используется).
- **seo-cro / owner_decision** — Какие изменения формы заказал оркестратор в правках по V-64 (необязательные поля/галочки, экран успеха)?
  - эталон: Имя необязательно; вторая необязательная непредотмеченная галочка на рекламные сообщения (ч.1 ст.18 38-ФЗ) отдельным полем; необязательный вопрос «Telegram / Max / другое»; кнопка на экране успеха «напишите нам в Telegram — 15 минут» + событие Метрики waitlist_next_step
  - `real`: UNKNOWN
  - `realaudit`: Вторая необязательная неотмеченная галочка «Согласен получать от ООО „СИДОН“ сообщения о запуске и предложения по сервису на указанный контакт»; имя необязательное; вопрос «Где вам удобнее: Telegram / Max / другое»; кноп

### Потеряно в `realaudit`, сохранено в `hybrid`

- **Orchestra-orchestrator / open_item** — After the 24.09 restart, which projects still fail the project layout migration at every restart (with what code), and is there a data-loss check for the VPS?
  - эталон: dnd-game-master and cog-second-brain fail with ORCHESTRA_LAYOUT_PARTIAL on every restart since 22.09; cog's dirty file was checked intact (59 KB); the mechanism fix is still planned.
  - `realaudit`: dnd-game-master fails with ORCHESTRA_LAYOUT_PARTIAL; cog-second-brain (/opt/cog-second-brain) fails with ORCHESTRA_LAYOUT_GIT_ERROR (stash orchestra-layout-preserve). Data-loss check for the VPS: UNKNOWN (only cog file k
  - `hybrid`: dnd-game-master and cog-second-brain fail with ORCHESTRA_LAYOUT_PARTIAL at every restart since 22.09 (22 lines); VPS data check: cog file 02-personal/katya/katya-health-2026-07.md is intact, 59398 bytes.
- **oge-russkiy / user_verbatim** — What were Katya's exact words when she rejected the second (23-slide) deck?
  - эталон: «Очень мелкий шрифт много текста много цветов нет картинок»
  - `realaudit`: UNKNOWN
  - `hybrid`: «Очень мелкий шрифт много текста много цветов нет картинок»
- **katya-work-orchestrator / prohibition** — Какое ограничение сработало при попытке удалить временную папку через rm и как удалять файлы?
  - эталон: Хук блокирует рекурсивный rm; удалять только в корзину (trash-put; в Drive удаление в корзину).
  - `realaudit`: UNKNOWN
  - `hybrid`: Хук блокирует `rm -r`; удалять надо через `trash-put` (в корзину).
- **cog-second-brain-orchestrator / number** — What are the base scores for a planet of level 1/2/3/4 in the recovered Slipways formula, and how much is each empire-size level worth?
  - эталон: 80/160/320/640 per planet; empire_size 400 per level
  - `realaudit`: UNKNOWN
  - `hybrid`: Planet lv1/lv2/lv3/lv4 = 80/160/320/640; empire size ×400 per level (Esteem ×50).
- **cog-second-brain-orchestrator / number** — What is the penalty for unfinished council quests in Slipways scoring, and from which year does it apply?
  - эталон: −500 per unfinished quest, only from year 20
  - `realaudit`: UNKNOWN
  - `hybrid`: −500 for an unfinished quest, only from the 20th year.
- **cog-second-brain-orchestrator / number** — What did the V-43 extraction find that contradicts the V-42 wiki reconstruction? Give the Forgiving trade base_value and the Everted slipway multiplier.
  - эталон: Forgiving base_value = 8 (not 7); Everted slipway ×1.6 (not ×2)
  - `realaudit`: UNKNOWN
  - `hybrid`: Wiki was wrong: Forgiving trade base_value/income = 8 (not 7); Everted slipway ×1.6 (not ×2).
- **cog-second-brain-orchestrator / number** — According to V-43, what are the slipway cost base and range constants, and is there a hard limit on the number of ports per planet?
  - эталон: base_cost=6, base_distance=1.223×3.8, range=2.82×3.8; no hard port limit, only a geometric crossing check
  - `realaudit`: UNKNOWN
  - `hybrid`: base_cost=6, base_distance=1.223×3.8, range=2.82×3.8 (cost ∝ (distance/base)^1.5, min half of base); no hard cap on ports.
- **bizdev / prohibition** — Какое действующее ограничение на платежи установлено для счёта ООО из-за критерия подп. «в» п. 5 ПП № 1236?
  - эталон: Не проводить платежи Anthropic/OpenAI/Deepgram через счёт ООО до кратного роста лицензионной выручки.
  - `realaudit`: UNKNOWN
  - `hybrid`: Не проводить платежи Anthropic/OpenAI/Deepgram через счёт ООО до кратного роста лицензионной выручки
