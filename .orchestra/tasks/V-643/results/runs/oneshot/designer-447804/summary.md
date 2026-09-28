## TASK STATE

**Current objective #V-75: моушн-рилс 1, варианты A/B/C.** Rendered, checked, copied to the director's laptop, and committed. DONE was sent to `seedon-orchestrator` (delivery `00af5af5-…`). The phase now is waiting for the director to pick A, B or C, or send new edits.

Earlier objectives, all closed:
- **#242 (2ГИС фото)** — delivered, then transplanted onto `main` at `6f1bd2a4…`.
- **#V-50 (Бобик для белых лендингов)** — stopped. The orchestrator later said the landings shipped without Бобик and the brief is not used.
- **#V-74** — three scripts plus `reel1.mp4`, commit `f421ed6`. The orchestrator reported it as merged.
- **#V-75 (три рилса со звуком)** — commit `ab65bdb`. The orchestrator reported it as in `main`.
- **#V-75 моушн v1** — `reel1-motion.mp4`, commit `488f938`. The director said the story was unclear.
- **#V-75 сценарии A/B/C + разбор** — commit `4ad841f`.

## DECISIONS

- **Final (director): render all three variants A, B and C;** the director will choose. Every variant includes the edits from `motion-review.md`:
  - hook question «ЧТО / ПОДАРИТЬ / МАМЕ?»;
  - quotes stay on screen for a full bar;
  - the long answer gets 2 bars;
  - about 25 beats instead of 48;
  - loop via a fade to black;
  - CTA with a large «СКОРО» and «ссылка в профиле ↑».
- **Durable rule (director, 25.09):** every finished video goes to the laptop at `/mnt/data/Рабочий стол/СИДОН — документы/Рилсы лист ожидания/` via tar over ssh (skill `laptop-access`).
- **Music and SFX are self-synthesized** in code: phonk beat at 128 BPM in F minor, no samples, so the rights are ours.
- **Voice (reels 1–3 with voice)** is Vosk TTS `vosk-model-tts-ru-0.9-multi`, Apache 2.0.
  - Piper is not used: model cards list denis as CC0 and irina as unknown.
  - Silero is excluded as non-commercial.
  - Reel 3's voice is a draft until the director records it live.
- **Reel 3 CTA is `seedon.ru`.** Frame 6 («выиграем ли закупку — узнаем 30 сентября») stays. The customer name is not shown.
- **Motion-v1 was replaced by a template:** `src/reel1-motion.html` was `git rm`'d. The rendered `out/reel1-motion.mp4` is kept.
- **Bitrate for motion renders:** x264 preset slow, crf 20, maxrate 10M, bufsize 20M. The grain otherwise produced a 244 MB file.

## FILES AND ARTIFACTS

Worktree `/home/kesha/orchestra/worktrees/home-kesha-projects-seedon/designer`, branch `task-V-75/designer`.

**Motion template (created):**
- `.orchestra/tasks/V-75/src/motion.js` — scene engine. Scene types: words, stack, quote, ask, voice, chips, roll, ring, stutter, cta.
- `.orchestra/tasks/V-75/src/motion.css`
- `.orchestra/tasks/V-75/src/reel1-motion-{A,B,C}.html` — each holds its scenario as `window.SCENARIO`.
- `.orchestra/tasks/V-75/src/build_motion.sh` — render → audio → laptop copy with sha256 check.
- `motion_render.py` — also writes `out/<name>-timeline.json`.
- `motion_audio.py` — driven by the timeline.

**Outputs:**
- `out/reel1-motion-A.mp4`, 32 159 653 B, 24.37 s.
- `out/reel1-motion-B.mp4`, 32 142 837 B, 24.37 s.
- `out/reel1-motion-C.mp4`, 20 116 958 B, 15.0 s.
- `-contact.png` and `-safezone.json` for each.
- `*-sfx.mp4` and `*-timeline.json` are gitignored.

**Docs:**
- `.orchestra/tasks/V-75/motion-scripts.md` — three scripts.
- `.orchestra/tasks/V-75/motion-review.md` — review against the canons, fixes, template estimate.
- `.orchestra/tasks/V-75/motion-research.md`
- `.orchestra/tasks/V-75/report.md` — has sections appended for motion v1 and for A/B/C.

**Earlier V-75:**
- `out/reel1.mp4` 40.5 s, `reel2.mp4` 44.0 s, `reel3.mp4` 56.0 s.
- `out/reel1-motion.mp4` and `-sfx.mp4`, 22.5 s.
- `src/audio.py` — the `lufs()` fix measures mono as stereo.
- `src/render.py` — contact sheet at exact 0/2/4… s, rows adapt to duration.
- `.orchestra/workers/designer.md` has a line appended about the motion template and the laptop rule. There is no evidence whether it went into commit `08428bb`.

**Commit:** the A/B/C commit was reported to the orchestrator as `08428bb`. The staged list was shown; the commit output was truncated. Not merged, not pushed.

**Laptop copies:** A, B and C (`LAPTOP OK` with sha256 `1bb23555…`, `4aee50cf…`, `3cb2859e…`). Also `reel1.mp4`, `reel2.mp4`, `reel3.mp4`, `reel1-motion.mp4` and `reel1-motion-sfx.mp4` are listed in the laptop dir.

## COMMANDS AND TOOL OUTCOMES

- **Build:** `bash build_motion.sh reel1-motion-A reel1-motion-B reel1-motion-C` (bg job `bg-4fce45d998`) returned RC=0.
  - Safe-zone violations are 0 for all three. Frame counts are 1462, 1462 and 900.
  - The mix measured −14.0 LUFS.
- **ffprobe** on all three: 1080×1920, 60 fps, audio stream present.
- **ebur128:** A and B at −14.1 LUFS with peak −0.9 dBFS; C at −14.1 LUFS with peak −1.0 dBFS.
- **Environment:**
  - Playwright is at `PYTHONPATH=/tmp/v74pw`, running chromium-1243.
  - numpy, scipy, pyloudnorm and vosk-tts are at `PYTHONPATH=$HOME/.cache/v75-tts/py`.
  - The laptop ssh is `ssh -i /home/kesha/.ssh/tunnel_laptop -o IdentitiesOnly=yes -o BatchMode=yes -p 2222 maxim@127.0.0.1`.
  - The first manual copy attempt (bg `bvfdoroay`) exited with 255 after the listing. The copy inside `build_motion.sh` later succeeded.
- **Cause of the 24.09 V-75 build crash:** unknown, because the output was not saved. Build logs now go to `out/build.log` and `out/motion-abc.log`.

## BLOCKER / NEXT

- **Blocker:** the director's choice among A, B and C. Owner: director, via `seedon-orchestrator`.
- **Next action:** wait for the orchestrator's message. If a variant is chosen or edits come back, edit that `reel1-motion-X.html` scenario and rerun `bash build_motion.sh <name>` from `src/`. That run also copies to the laptop.
- **Possible follow-up (not yet requested):** motion versions of reels 2 and 3 on the template. Estimated at 1–2 h each.

## CONSTRAINTS

**Durable:**
- Commit before DONE.
- Report only via `mcp__orchestra__send_message`.
- No `git push`, and publish nowhere.
- Do not commit PNG frames or the cache.
- Copy each finished video to the laptop folder.
- Music and sounds only with clean rights; a new paid service needs the orchestrator's approval.
- Target −14 LUFS; music under voice at −20…−24 LUFS.
- Safe zones: top 220 px, bottom 380 px.
- Brand look: dark #080b11, green #10b981, fonts Unbounded and Manrope, no emoji, no Бобик in the reels.
- Forbidden claims: «первые в России», «аналогов нет», «уже пользуются тысячи».
- Say that the product does not exist yet: this is a waitlist and the scenario is an example.
- The designer never generates Бобик.

**One-off:** no longer render-blocked; the "don't render yet" hold was lifted by «давай все 3 делай».

**Unresolved:**
- I cannot judge the voice or the beat by ear; the director has to listen.
- The first frame of each reel is nearly empty, so the cover has to be picked manually on the platform.

## USER MESSAGES AND RAW TRANSCRIPT

Raw transcript: `/api/sessions/designer/logs?scope=/home/kesha/projects/seedon`

Messages 1–6 (#242 and #V-50) are preserved verbatim in the previous handoff summary. In brief:
1. #242 брief.
2. #242 mid-turn scope cut.
3. «Continue from where you left off.»
4. `[system wake…] Лимит подписки сброшен…`
5. #242 transplant.
6. #V-50 Бобик render request.

**7.** (after compaction) `Acknowledge briefly.`

**8.** `[from:seedon-orchestrator] #V-74. Твой старый бриф на Бобиков для V-50 перенесён в эту ветку как история. Лендинги ушли без Бобика, бриф не используем.`

> Задача от директора: рилсы для листа ожидания. Он просит пример ролика в 2D-анимации «красиво, по-умному», сделанный нами, а не снятый на телефон.
>
> Что нужно на выходе:
> 1) Сценарии трёх роликов по 30–45 секунд, вертикальные 9:16, покадрово: что на экране, текст на экране, закадровый текст для директора или Кати, длительность каждого кадра, финальный призыв со ссылкой.
>    - «Сказал голосом — нашёл через месяц» → https://seedon.ru/skoro/lichnaya-pamyat/
>    - «Кто мне должен» (самозанятый: долги и напоминание) → https://seedon.ru/skoro/assistent-samozanyatogo/
>    - «Веду компанию с командой ИИ-агентов» — личный бренд директора. Реальные цифры бери из docs/product/ORCHESTRA-CASES.md, кейс 9: 7 задач за день.
>    Хук в первые 1–2 секунды, одна мысль на ролик. Идеи берём со страниц лендингов, там уже есть сценарии диалогов.
> 2) Первый ролик — готовый MP4 1080×1920, 30–40 секунд, 2D-анимация в стиле сайта: тёмный фон #080b11, зелёный #10b981, шрифты Unbounded и Manrope, макеты Telegram-переписки из лендинга, кинетическая типографика. Путь рекомендую такой: HTML/CSS/JS-анимация → покадровый рендер headless Chromium → ffmpeg. Пример сборки слайдов лежит в .orchestra/tasks/V-70/src/. Метод выбирай сам. Без Бобика. Музыку не добавляй: права — отдельный вопрос, оставь дорожку пустой, в отчёте опиши, куда встанет звук.
> 3) Проверка: просмотри кадры на таймлайне (контакт-лист каждые 2 с). Текст должен читаться на телефоне и не выходить за безопасные зоны Reels/Shorts/VK Клипов: сверху ~220 px и снизу ~380 px под интерфейс площадки.
> 4) Файлы — в .orchestra/tasks/V-74/. Отчёт — report.md: сценарии, путь к MP4, как пересобрать. Потом DONE.
>
> Запреты: «первые в России», «аналогов нет», «уже пользуются тысячи» не писать. Продукта ещё нет — это лист ожидания, сценарий показываем как пример. Никуда не публиковать.

**9.** `[from:seedon-orchestrator] #V-74. Задачу ставлю заново: тебя перевели на Opus 5.5, и из-за бага платформы прежний диалог стёрт. Сначала посмотри `git log` ветки task-V-74/designer, `git status` и `.orchestra/tasks/V-74/`. Если работа уже начата — продолжай с неё. Файл `.orchestra/tasks/V-50/render-brief.md` в ветке — старый бриф на Бобика, к этой задаче он не относится.`

> Директор просит рилсы для листа ожидания: пример ролика в 2D-анимации, «красиво, по-умному», сделанный нами, а не снятый на телефон.
>
> Что нужно на выходе:
> 1) Сценарии трёх роликов по 30–45 с, вертикальные 9:16, покадрово: что на экране, текст на экране, закадровый текст для директора или Кати, длительность каждого кадра, финальный призыв со ссылкой.
>    - «Сказал голосом — нашёл через месяц» → https://seedon.ru/skoro/lichnaya-pamyat/
>    - «Кто мне должен» (самозанятый: долги и напоминание) → https://seedon.ru/skoro/assistent-samozanyatogo/
>    - «Веду компанию с командой ИИ-агентов» — личный бренд директора. Реальные цифры бери из docs/product/ORCHESTRA-CASES.md, кейс 9: 7 задач за день.
>    Хук — в первые 1–2 с, одна мысль на ролик. Сценарии диалогов уже есть на страницах лендингов.
> 2) Первый ролик — готовый MP4 1080×1920, 30–40 с. 2D-анимация в стиле сайта: тёмный фон #080b11, зелёный #10b981, шрифты Unbounded и Manrope, макеты Telegram-переписки как на лендинге, кинетическая типографика. Рекомендую путь HTML/CSS/JS-анимация → покадровый рендер headless Chromium → ffmpeg. Пример сборки слайдов — .orchestra/tasks/V-70/src/. Метод выбирай сам. Без Бобика. Музыки нет: права — отдельный вопрос. Оставь дорожку пустой и опиши в отчёте, куда встанет звук.
> 3) Проверка: контакт-лист кадров каждые 2 с. Текст читается на телефоне и не заходит в безопасные зоны Reels/Shorts/VK Клипов: сверху ~220 px, снизу ~380 px.
> 4) Файлы — в .orchestra/tasks/V-74/. В report.md — сценарии, путь к MP4 и как пересобрать. Потом DONE.
>
> Нельзя писать «первые в России», «аналогов нет», «уже пользуются тысячи». Продукта ещё нет, это лист ожидания: сценарий показываем как пример. Никуда не публиковать.

**10.** `[Background job completed] V-74 рендер reel1 завершён` — Exit code 0. safe-zone violations=2 at 3.33 s («Сообщение...», «➤»).

**11.** `[Background job completed] V-74 повторный рендер reel1 завершён` — Exit code 0. safe-zone violations=0.

**12.** `[from:seedon-orchestrator] #V-75. V-74 смержена, ролик 1 директор посмотрел. Его решение (24.09 18:30): ролики 2 и 3 тоже делать, и «звук обязательно — все звуки надо и голос, если получится».`

> Что нужно на выходе: три готовых MP4 1080×1920 со звуком — reel1 (пересобрать со звуком), reel2 «Кто мне должен», reel3 «Веду компанию с командой ИИ-агентов». Ролики 2 и 3 — по твоим сценариям из .orchestra/tasks/V-74/report.md, в том же стиле и тем же seek-рендером. Проверка безопасных зон та же.
>
> Звук в каждом ролике:
> 1) Голос — закадровый текст из сценария, по-русски, естественный, без роботизированной интонации. Способ выбирай сам: локальный TTS (например, Silero) или облачный, если на машине есть ключ. Ключи ищи в secrets/. Новый платный сервис без моего подтверждения не заводи. Если приличного голоса не получится, сделай ролик без голоса, но с музыкой и звуками, а в отчёте напиши, почему. Голос ролика 3 — это речь директора от первого лица. Синтезированный голос тут допустим как черновик: подпиши его в отчёте как черновую озвучку до записи живым голосом.
> 2) Музыка — фоновая подложка только с чистыми правами: CC0, собственная генерация или библиотека с явной лицензией на коммерческое использование. Источник и лицензию запиши в отчёт. Громкость под голосом −20…−24 LUFS, итог ролика около −14 LUFS (норма площадок).
> 3) Звуки — щелчки на появление сообщений, «вжух» на переходах. Таймкоды для ролика 1 у тебя в отчёте V-74, для 2 и 3 разметь сам. Источник тоже с чистыми правами.
>
> Голос должен совпадать со сценами: если фраза длиннее сцены, растяни сцену, а не ускоряй речь. Кадр 6 ролика 3 («выиграем ли закупку — узнаем 30 сентября») оставить обязательно. Название заказчика на экран не выводить. Ссылка в ролике 3 — seedon.ru.
>
> Проверка перед DONE: ffprobe каждого MP4 (аудиопоток есть, длительность), замер громкости (ebur128 или loudnorm), контакт-листы. Сам прослушай стык голоса и сцен: выпиши таймкоды фраз и сверь со сменой сцен. Файлы — в .orchestra/tasks/V-75/, отчёт — report.md с источниками и лицензиями звука. Кадры PNG не коммить. Никуда не публиковать. Потом DONE.

**13.** `[Background job completed] V-75: TTS-модели скачаны` — Exit code 0.

**14.** `[Background job completed] V-75: синтез голоса (замер длительностей) завершён` — Exit code 0.

**15.** `[from:seedon-orchestrator] Current #V-75: работа встала 24.09 около 14:01. Рендер трёх роликов со звуком (bg-4bb86d4ee0) упал, отчёта нет, `.orchestra/tasks/V-75/` не закоммичен. Готовы reel1-video.mp4 и reel2-video.mp4, reel3 нет.`

> Что сделать: найди, почему упал рендер, и доведи все три рилса со звуком до готовых MP4. По каждому нужны ffprobe (длительность, есть ли аудиодорожка) и громкость. Результат закоммить, report.md напиши в `.orchestra/tasks/V-75/`, пришли DONE.
> Кадры и cache в git не клади, только итоговые MP4, contact-листы и отчёт. Если не укладываешься, закоммить то, что есть, и пришли WIP с причиной.

**16.** `[Background job completed] V-75: reel3 перерендерен, звук трёх роликов собран` — Exit code 0.

**17.** `[from:seedon-orchestrator] Current #V-75: V-75 уже в main. Новый шаг по слову директора: переделать рилс 1 в жёсткий динамичный моушн («надо активнее, это же рилсы, СДВГ», «переработаем по всем канонам, музыка хайповая»). Полная постановка с референсами, требованиями к выходу и проверками — `/home/kesha/projects/seedon/.orchestra/tasks/V-75/motion-brief.md`, прочитай её целиком. Референсы: GROMKO_motion_15s.mp4, motion_showreel.mp4 и Claude_шоурил_2026.mp4 плюс исходники claude_showreel_ru_src.zip, всё в /home/kesha/orchestra/data/uploads/. Музыку вшивать только с правами. Никуда не публиковать. DONE с путём к reel1-motion.mp4.`

**18.** `[Background job completed] V-75 motion: рендер reel1-motion и звук завершены` — Exit code 0. safe-zone violations=11.

**19.** `[Background job completed] V-75 motion: повторный рендер reel1-motion завершён` — Exit code 0. violations=0, mix −14.0.

**20.** `[from:seedon-orchestrator] Current #V-75: директор посмотрел reel1-motion. Цитата: «прикольно, только по тексту надо разобраться, че там мама хотела — непонятно, типа лепить без галочки вещей». Динамика и формат зашли, не понятна история. Зритель не понимает, что именно мама хотела в подарок, и сценарий с «галочкой» читается как бессмыслица.`

> Что сделать:
> 1. Переписать текст так, чтобы история считывалась без звука с первого просмотра: конкретная понятная вещь, которую мама назвала (одно-два слова, узнаваемо сразу), кто что сказал, что ассистент нашёл через месяц. Каждое слово на экране должно двигать историю, никаких обрывков вроде «лепить без галочки». До рендера пришли мне 2–3 варианта сценария покадрово: текст по сценам с таймингом. Директор выберет.
> 2. В `.orchestra/tasks/V-75/motion-review.md` честно разбери: по каким канонам сделан ролик (хук, темп, структура, типографика, звук) и почему может залететь, а почему может не залететь — удержание на 3-й и 8-й секунде, понятность без звука, CTA, досмотр до конца, риск «рекламности». Плюс конкретные правки, отсортированные по влиянию на досмотр. Оценки помечай как оценки.
> 3. Отдельно: можно ли переиспользовать движок моушна как шаблон для рилсов 2 и 3 и для будущих, что для этого вынести в конфиг и сколько займёт новый ролик на готовом шаблоне.
> Пока ничего не рендерить, сначала сценарии на выбор.

**21.** `[from:seedon-orchestrator] Current #V-75: правило директора с сегодняшнего дня. Каждый готовый ролик после рендера клади на его ноутбук в `/mnt/data/Рабочий стол/СИДОН — документы/Рилсы лист ожидания/` (скилл laptop-access, копировать через tar по ssh). Вариант сценария (A/B/C) директор ещё не выбрал, пока ничего не рендери.`

**22.** `[from:seedon-orchestrator] Current #V-75: директор решил: «давай все 3 делай, я уже буду выбирать». Отрендери все три варианта из motion-scripts.md: A (кроссовки, 22,5 с), B (глина, 22,5 с), C (короткий, 15 с). Правки из motion-review.md вшей во все три: хук-вопрос, цитаты держатся весь такт, длинный ответ на два такта, около 25 ударов вместо 48, петля, призыв «ссылка в профиле» с крупным «СКОРО». Имена файлов: `out/reel1-motion-A.mp4`, `-B.mp4`, `-C.mp4`. Проверки прежние: ffprobe, громкость, безопасная зона, контакт-лист. Сразу по готовности каждого копируй его на ноутбук в `/mnt/data/Рабочий стол/СИДОН — документы/Рилсы лист ожидания/`. Закоммить и пришли DONE одним сообщением: пути и длительности.`

**23.** `[Background job completed] V-75: варианты A/B/C отрендерены и скопированы на ноутбук` — Exit code 0. All three have safe-zone violations=0, mix −14.0 LUFS, and `LAPTOP OK`.