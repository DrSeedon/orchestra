# TASK STATE

Я — `cog-second-brain-orchestrator` (модель claude-opus-5-5[1m]), оркестратор проекта `/opt/cog-second-brain` (второй мозг Кеши: знания, личные проекты, Balatro, теперь Slipways). Владелец — Кеша (на ноуте пользователь `maxim`). Последнее событие: 23.09 ~12:18 по Красноярску (10:18 UTC) — влил V-44 в main, опубликовал Slipways и отчитался владельцу; ждём его выбора следующего шага (задач в работе нет).

## Slipways — текущая линия (23.09)
- **V-42** (правила из открытых источников) — DONE, в main `dcf9f23`. Воркер `slipways-research` убит.
- **V-43** (точные правила из установленной игры) — DONE, в main `2262a69` (worker head c0ac749092a212b61c1a2ff23c49d04a2ebe6173). Воркер `slipways-extract` убит. Игра почти целиком на Python + Excel в архиве `data.swar`; C#-часть декомпилирована ILSpy. Формула счёта воспроизводит **9/9 standard-партий владельца с diff=0**; campaign — отдельная система очков. Я перепроверил сам (844, 13042, 14126). UNKNOWN: генерация карты seed→карта (RNG не распутан), источник consumer.PriceMultiplier, механизм третьего перка, партия 28 лет вместо 25.
- **V-44** (task_id 4510) «Slipways: ядро симулятора + бот + статистика» — владелец выбрал [13:03] «ядро бот». Ядро без технологий, перков, рас, событий, квестов/Esteem, quirks, структур.
  - Воркер `slipways` (lifecycle=persistent, owned_dirs `04-projects/slipways`), ветка `task-V-44/slipways`, worktree `/home/kesha/orchestra/worktrees/opt-cog-second-brain/slipways`. Начинал Sonnet (~10 мин, ~700 строк), затем по просьбе владельца переведён на `claude-opus-5-5[1m]` (алиас `opus-5.5` не существует). Opus выкинул 6 из 7 файлов Sonnet (оставил `rng.js`).
  - Воркер застрял на квотном гейте Claude (24–25% при линии ~23–24%) и не получил результаты прогона. В 10:17 UTC я сделал ему `stop_worker` → **idle** (ctx 49%, persistent, НЕ убит). Таймер-повтор bg-3e652fa4c4 отменён в 10:09 UTC; активных таймеров по V-44 нет.
  - Владелец [17:09] поручил мне самому доделать отчёт, коммит и HTML с графиками → я сделал: добавил в `stats.js`/`auto-ui.js` график кассы по годам, гистограмму счёта по тысячам, «месяцы на колонии и слипвеи из 300» и блок «упор во время, а не в деньги»; заполнил раздел результатов в `.orchestra/tasks/V-44/report.md`; дополнил CHANGELOG; тесты 15/15; собрал `data/stats.json` + `data/replays.json` (build_stats EXIT=0, повтор медианных партий совпал); проверил страницы в playwright (auto 14 svg / 86 элементов, index 338 элементов, 0 ошибок консоли).
  - **Коммит `fbc9952`** «#V-44: Slipways core engine, bots, results page and report» в ветке воркера (поверх WIP `b4acf6a`, `b58498f`); 39 файлов, +4286; исходников игры (.py/.xls/.cs/.dll/.swar) в диффе нет.
  - **V-44 ВЛИТ В MAIN (DONE).** Первая попытка merge_worker (короткий хеш, воркер в waiting) упала (operation e6773471-…); после `stop_worker` вторая попытка `merge_worker(name="slipways", expected_head="fbc995241163a9b04d22c2bb8dd005b2768de3b8", task_outcome="complete", waive_diff_budget=true)` → **SUCCEEDED**, operation `0a516a56-3fe7-4b8a-9139-882d4eb3d381`, commits_merged 3, конфликтов нет, main `e3a7599` → **`270da3b48b6b0c7615ad65a213af07f1f25d94dc`** (платформа взяла для сквош-коммита заголовок первого WIP: «V-44: WIP #V-44: Slipways core engine, bots, pages; runs pending», 39 файлов +4286 — содержимое = финальный fbc9952). Статус задачи V-44 (task_id 4510) → **done**.
  - **Опубликовано**: `/var/www/cog-slipways/current -> /var/www/cog-slipways/releases/270da3b48b6b0c7615ad65a213af07f1f25d94dc` (скопировано из `/opt/cog-second-brain/04-projects/slipways/`). В nginx вхост `/etc/nginx/sites-available/photoserver-qr` добавлен `location ^~ /slipways/` (alias на current, `limit_req zone=balatro_static burst=400 nodelay`, те же заголовки, что у /balatro/), бэкап `photoserver-qr.bak-slipways`; `nginx -t` ok, reload. Соседи до/после: /balatro/ /elevator/ /tabletop/ /board/ /golos 200, /wall/ 403 (так и было).
  - URL: https://photo-158-220-127-161.sslip.io/slipways/auto.html (статистика), https://photo-158-220-127-161.sslip.io/slipways/ (карта партии с перемоткой).
  - Раздел «Заготовка Sonnet» (итог Opus, озвучен владельцу): формулу счёта Sonnet написал без ошибок (Opus переложил на свою структуру); таблицу планет выкинул из-за дефектов данных (у 23 из 27 вариантов не хватало колонки уровня, уровни сдвинуты на единицу, неверный upkeep у Arid Colony, лишний вариант из перка); в константах неверный порог поражения для Forgiving и дальность линии от центров вместо «от края до края»; генератор карты заменён по архитектурным причинам, ошибок не было.

## Balatro (фон, всё закрыто 20.09)
Все задачи 20.09 закрыты, влиты, опубликованы (V-22, V-27..V-32, V-35..V-41). Главный результат: `blueprint+blue+half` на политике v9 = **13.567** блайнда против базовых **12.95** (Δ+0.583, ДИ [0.450; 0.717]); на v8 та же связка 12.983 (ноль). Полных побед (24 блайнда) нет нигде. Каталог 56/150 джокеров; 94 недоступны (деньги/магазин 25, правила руки/колоды 17, модификаторы карт 16, действия с колодой/блайндами 16, таро/планеты 11, случайные эффекты 9). Вопрос владельцу «открывать ли деньги и магазин» — **без ответа**. В трекере висят: V-33, V-34 [new], V-19 (legacy, in_progress), V-37 [new] (фактически выполнен 20.09).

# OWNER & USER REQUIREMENTS (verbatim)

- [23.09 11:55] «крч есть такая игра типо slipways погугли. крч по аналогии с балатро я хочу чето такое прикольное сделать типо по науке повторить игру типо и бота ии и статистику всю и все такое»
- [23.09 12:26] «давай еще гугли и еще у нас игра на ноуте давай её посмотри там все данные все исходники»
- [23.09 12:27] «я там играл и там все есть я даже 2 раза 5 звезд срубал»
- [23.09 13:03] «ядро бот» — выбор масштаба (ядро + бот, без технологий/перков/рас).
- [23.09 13:15] «переведи на опус 5.5 проверим его ок» — владелец тестирует именно Opus 5.5 на воркере `slipways`.
- [23.09 13:23] «и надо будет узнать че опус там изучи и че думал о сонет работе и переписала или чето оставила» — отвечено в итоговом сообщении (см. раздел «Заготовка Sonnet»).
- [23.09 17:09] «изучи все что там сделано и как какие результаты и тд и тп. отчет сам можешь сделать и коммит ок? и хтмл такой же для просмотра результатов графики как в балатро» — сделано (отчёт, коммит fbc9952, страница с графиками опубликована, V-44 влит в main 270da3b и закрыт).
- (Balatro, 20.09 20:23) «давай добивай все джокеры каких хотели и уже на них будем тестить страты» — выполнено V-41.

# DECISIONS

- Slipways: где V-43 противоречит V-42 — прав V-43 (код игры).
- Код/таблицы игры в репозиторий НЕ копировать (чужая интеллектуальная собственность): в репо только наши числа и наш код. Проверено для V-43 и V-44.
- Модельное ревью заморожено владельцем — приёмка по самому артефакту (отчёт читать целиком, числа перепроверять самому, мутационные проверки тестов).
- Вывод V-44: боты упираются во **время** (300 месяцев; колония 3 мес., слипвей 1), а не в деньги; касса копится, потому что в ядре нечего купить — это **ограничение ядра, а не политики ботов** (внесено в отчёт, CHANGELOG и страницу).
- Balatro: универсальной стратегии нет (v8/v9 выбираемые, выбор политики под набор — решение владельца). sparse UCT «не отвергнут, но не окупается при текущей оценке». Полный перебор 5 слотов запрещён до отдельного решения (962 598 наборов ≈ 50 суток). Ключ кеша обязан включать порядок слотов, policy и отпечаток движка.
- Тесты — только на механику, не на формулировки.

# FILES, IDS AND ARTIFACTS

## Slipways V-44
- Worktree `/home/kesha/orchestra/worktrees/opt-cog-second-brain/slipways`, ветка `task-V-44/slipways`, коммиты `b4acf6a`, `b58498f` (WIP), `fbc995241163a9b04d22c2bb8dd005b2768de3b8` (финал, мой) → в main как `270da3b48b6b0c7615ad65a213af07f1f25d94dc`.
- `04-projects/slipways/`: `src/rules.js`, `engine.js`, `scoring.js` (roundToInt половина к чётному, mul32 во float32), `mapgen.js` (свой генератор, 9 зон), `bots.js` (greedyBot, rolloutBot, DEFAULT_PARAMS), `sim.js` (`playGame({seed,difficulty,bot,keepActions})`), `stats.js` (бутстрэп 10 000, seed 44, знаковый тест, histogram, monthsUsed), `charts.js`, `auto-ui.js`, `map-ui.js`, `geometry.js`, `rng.js` (mulberry32), `style.css`; `auto.html`, `index.html`; `tools/run_bots.mjs`, `build_stats.mjs --replays`, `check_page.mjs`; `tests/scoring|engine|bots.test.js` (15 тестов); `data/runs/{forgiving,reasonable}-{greedy,rollout}.jsonl`, `data/stats.json`, `data/replays.json`; README, CHANGELOG, `serve.sh` (порт 18103), `package.json`.
- `.orchestra/tasks/V-44/`: `report.md`, `run_bots.log` (`finished 400, errors 0, 2967 s`), `build_stats.log` (EXIT=0), `sweep1/2/3.txt`, `sweepR-a.txt`, `map_kind_mix.csv`.
- Прогон: `node tools/run_bots.mjs --seeds 1-100 --difficulties forgiving,reasonable --bots greedy,rollout --workers 6`; тяжёлое — вне cgroup через `ssh -o BatchMode=yes kesha@localhost`.
- Релиз: `/var/www/cog-slipways/releases/270da3b48b6b0c7615ad65a213af07f1f25d94dc`, nginx `/etc/nginx/sites-available/photoserver-qr` (+ бэкап `.bak-slipways`).

## Slipways исходные данные
- Ноут (read-only!): игра `/mnt/data/Games/Slipways/` (Unity, GOG 1.3, под Wine, Mono): `Slipways_Data/Managed/Slipways.dll`, `Data/localization/*.py`.
- Сейвы: `/home/maxim/.wine_slipways/drive_c/users/maxim/AppData/LocalLow/Beetlewing/Slipways/saves/` — `runs/standard/` 9 партий + `runs/campaign/` 1; `odo.json`; `sandbox/joy-dbyevlemc-70745212098.json` (240 КБ, полное состояние карты).
- Лучшая партия: `20260911150509-0-10014126-bvs-nu-p_scholars-p_orbital_engineering.json`, 14126, 5★, forgiving, seed `JRJ-AWIQZXFKC`. Вторая 5★: `20260629161708-0-10013042-bvd-qu-p_researchers-p_growth.json` (13042).
- Копии на VPS: `/home/kesha/slipways-extract` (DLL, Data, saves, `data.swar`), `/home/kesha/slipways-data-v43/` (распакованный data.swar: `core/*.py` включая `scoring.py`, `mutators.py`, `generation.py`, `seeds.py`; `modes/standard/setup.py`; `game.xls` 13 листов с листом Constants; `difficulty-*.xls`; `game_rules.py`), `/home/kesha/slipways-xls-v43/*.csv`, декомпиляция `/home/kesha/slipways-decomp-v43/`. dotnet 8.0.425 в `/home/kesha/.dotnet`.
- В main: `.orchestra/tasks/V-42/report.md` (354 строки), `.orchestra/tasks/V-43/report.md` (264 строки) + `saves_summary.csv`, `saves_yearly_log.csv` (214 строк), `saves_scoring_components.csv`.
- Доступ к ноуту: скилл `laptop-access`; `ssh -i /home/kesha/.ssh/tunnel_laptop -o IdentitiesOnly=yes -o BatchMode=yes -p 2222 maxim@127.0.0.1`.
- Задачи: V-42 (4505), V-43 (4507), V-44 (4510).
- Источники: https://en.wikipedia.org/wiki/Slipways_(video_game), https://slipways.fandom.com/wiki/Slipways_Wiki, https://store.steampowered.com/app/1264280/Slipways/

## Balatro (всё в main и опубликовано)
- `04-projects/balatro/`: `assets/jokers/` (150 PNG + manifest), `assets/cards/` (52 PNG, в рендер не подключены), `src/joker-picker.js`, `combos.html`, `src/strategy-v9.js`, `src/strategy-uct.js`, `tools/run-cache.mjs`, `src/run-cache.js`, `tools/check_ui.py` (39 групп). Кеш `~/.cache/balatro/runs.jsonl`.
- Отчёты `.orchestra/tasks/V-30,36,38,39,40,41/report.md`; `V-37/solo-1000.jsonl`; `V-40/measure-v40-corrected.json` (итоговый; `measure-v40.json` — черновик); `V-41/measure-v41.json`, `measure-strategies-v41.json`.
- Сайт: https://photo-158-220-127-161.sslip.io/balatro/auto.html; релизы `/var/www/cog-balatro/` (current → releases/af7331c…).

# NUMBERS

## V-44 результаты (400 партий, seed 1–100, бутстрэп из stats.json)
| | greedy | rollout | rollout − greedy | лучше/ничья/хуже |
|---|--:|--:|--:|--:|
| Forgiving mean | 7 887 [7 624; 8 137] | 9 023 [8 843; 9 199] | +1 136 [985; 1 303], sign p=3.16e-30 | 99/1/0 |
| Reasonable mean | 6 780 [6 516; 7 044] | 8 315 [8 132; 8 490] | +1 535 [1 322; 1 762], sign p=6.31e-30 | 98/2/0 |
| Forgiving min/max | 3 702 / 10 614 | 6 868 / 11 110 | | |
| Reasonable min/max | 3 055 / 9 565 | 5 432 / 10 195 | | |
| счастье в конце F / R | 85.6 / 77.8 | 97.0 / 92.3 | | |
| касса в конце F / R (mean) | 4 248 / 734 | 4 346 / 799 | | |
| месяцев занято из 300 F / R | 297.1 / 285.3 | 292.9 / 287.7 | | |
| мс на партию F / R | 1 744 / 1 528 | 96 554 / 103 904 | | |
- Все 400 — win, поражений нет. Ранг 5 (12 000) не взят ни разу; лучшая партия 11 110. Ранги: f-greedy {1:3,2:25,3:67,4:5}; f-rollout {2:2,3:72,4:26}; r-greedy {1:7,2:54,3:39}; r-rollout {2:10,3:82,4:8}.
- Уровни планет (ср.): lv0 0.8–2.9, lv1 ≈48–49, lv2 ≈14–17, lv3 ≈0.4–1.1, lv4 0 (в ядре потолок lv3; lv4 только через техи Post-Scarcity/Elysium). Колоний ≈66–68, слипвеев ≈87–93.
- Проверка «упор во время» (seed 1–10, Forgiving, greedy): колонизируемых планет 305–317, бот колонизирует 57–70; колоний×3 + слипвеев = 296–302 месяца (seed 3 — 242). Greedy seed 1: 68 колоний (50 lv1), cash 4203, income 329; касса копится с ~7-го года. Администрация 68 колоний ≈408/год при торговле 813.
- Мутационные проверки: округление «половина вверх» → scoring tests 2 fail; длина слипвея от центров → engine tests 1 fail. Тесты рабочие.
- rollout-бот: 4 лучших хода жадного + пропуск, каждый доигран жадным до конца партии, выбор по финальному счёту. greedy: лучший прирост оценки на месяц по макроходам «колония + слипвеи + поставщики».

## Правила Slipways (V-43/V-44, CONFIRMED)
- Счёт: последовательно к running_total с округлением на каждом шаге (Mathf.RoundToInt — половина к чётному; умножение во float32): (1) planets Σ count(lv)×[0,80,160,320,640]; (2) Esteem ×50; (3) empire_size level×400 (пороги колоний 8/16/24/32/40/50; может заменяться quirk-мутаторами: 80/employed People или 300/tech); (4) −500 за незавершённый квест, только если NormalizedTurn ≥ 20; (5) × round(Happiness%)/100; (6) × round(100+Σ quirk score_modifier)/100. Пример: 14126 = 10090×1.40; 13042 = 13600×1.37=18632 ×0.70; 6770×0.45 = 3046.5 → 3046.
- Ранги 0–9: 12 000 = 5-я звезда; платиновые 16 000 / 20 000 / 24 000 / макс 30 000. 14126 = ранг 5.
- Слипвей: `floor(max(0.5,(L/4.647)^1.5) × 6 × (1+перегрузка))`, L = d − 2×0.65 (от края до края); base_cost 6, base_distance 1.223×3.8, дальность 2.82×3.8 = 10.716; перегрузка +10% за каждые 5 слипвеев сверх порога сложности (80/60). Нельзя пересекать слипвей и проходить ближе 0.999 от чужого узла. Хардкапа портов нет. Маршрут только между соседями по слипвею (транзит только через реле). Слипвей только между колонизированными планетами.
- Доход маршрута `floor(base×(1+m[прод]+m[покуп]))`, m=[−0.25,0,0.1,0.2,0.4] по уровням 0..4, base Forgiving 8 / Reasonable 6; upkeep RoundToInt(scaling×base) (0.7/1.0); администрация floor(ставка×колоний), ставка 0…6 по порогам 8/16/24/32/40/50. Годовое начисление max(доход до последнего действия, после).
- Уровни: →1 все нужды закрыты; →2 +≥2 импорта и ≥min(2, продуктов) экспорта; →3 +≥3 разных партнёров lv≥2 и импорт+экспорт ≥6.
- Счастье = 100 + Σ: процветание +1/+3 (lv2/lv3), голодная lv0 −(годы+1) до −8, затем постоянно −3, безработный People −1, «ничего не экспортирует» −2. Поражение: счастье ниже порога (30/60) 3 года подряд; касса <3 при доходе ≤0. Конец на 25-м году.
- Противоречия с вики V-42 (игра права): Forgiving base 8 (не 7); Everted ×1.6 (не ×2); Infraspace Relay 20 (не 30), Teleporter 40 (не 30); upkeep Fusion Plant 2, Protostar 7, Void Synth 5, Ascension Gate 5; отдельных компонентов Population/Technology в счёте нет.
- odo.json владельца: 419 планет, 703 маршрута, 55 технологий, 10 партий; forgiving рекорды MostPlanets 55, MaxHappiness 141, MostMoneyPerYear 556.

## Balatro
- Тесты Node 130/130, UI 39 групп.

# CONSTRAINTS AND BANS

- Публикую/мёржу только я; воркерам запрещён `git push` и деплой.
- Ноутбук — только ЧТЕНИЕ, ничего не ставить и не менять. На VPS ставить инструменты разрешено.
- Прямой `sudo` из процесса Orchestra запрещён NoNewPrivileges → `ssh -o BatchMode=yes kesha@localhost '<cmd>'`; тяжёлый счёт туда же (cgroup платформы убивает по OOM, EXIT=137).
- Код/таблицы игры Slipways в репо не коммитить.
- Воркера `slipways` на Luna не переводить без решения владельца (владелец тестирует именно Opus 5.5; смена модели сотрёт контекст).
- Квотный гейт Claude блокирует ходы Claude-воркеров; если снова закрыт — не ставить молча бесконечные таймеры, а сказать владельцу и предложить выбор (ждать / сменить модель ценой контекста).
- Тесты на формулировки запрещены; квитанции прогонов — файлами; отчёт читать целиком до приёмки; числа проверять своим прогоном.
- Правка чужого общего вхоста: снять коды соседей ДО и ПОСЛЕ (`/balatro/ /elevator/ /tabletop/ /board/ /golos /wall/`), `nginx -t` мало. Многофайловые страницы — отдельная зона `balatro_static`, не общая `photoserver_public`. KB: `/opt/cog-second-brain/.orchestra/kb/static-hosting-silent-failures.md`.
- После 23:00 по Красноярску сворачивать разговор. Рестарт Orchestra — только владелец. Вхост `dnd-duckdns` не редактировать; `/var/www/balatro/` принадлежит проекту D&D; `02-personal/` наружу не отдаётся. Диагностический `access_log cog-diag.log` в nginx (у /elevator/) всё ещё включён.
- merge_worker: полный 40-символьный expected_head; `DIFF TOO LARGE` → `waive_diff_budget=True`; воркер должен быть idle (не waiting) — лечится `stop_worker`.
- Уведомления о фоновых заданиях воркера приходят МНЕ, а не воркеру — воркер их сам не подхватывает; пересылать/говорить читать квитанции.
- Модель Codex/luna часто упирается в rate limit (младший тариф) — для slipways-extract пришлось переводить на sonnet.
- Публикация: `ssh … kesha@localhost` + `sudo cp -a` в `/var/www/cog-<proj>/releases/<sha>` + `ln -sfn … current.new` + `mv -T`.
- Playwright: `uv run --no-project --with playwright python …`.

# PEOPLE AND AGENTS

- Владелец Кеша (русский, неформально, иногда голосом; время по Красноярску = UTC+7).
- Воркеры: `slipways` (V-44 влит, claude-opus-5-5[1m], persistent, **idle** после stop_worker, ctx 49%; следующие этапы Slipways можно давать ему); `balatro-vps` (luna, persistent, idle); `autobattler`, `elevator` (luna, idle); `balatro-perf` (luna, one-shot, idle). Убиты: `slipways-research`, `slipways-extract`.
- Модели в платформе: claude-opus-5-5[1m], claude-sonnet-5[1m], gpt-5.6-luna и др. Codex/luna упирается в rate limit (подписка на младшем тарифе).

# OPEN ITEMS AND NEXT ACTION

1. V-44 закрыт полностью: влит (main 270da3b), опубликован из main-SHA 270da3b, сайт и соседи проверены, владельцу доложено (10:18 UTC). Ничего не висит.
2. Ждать решения владельца по следующему шагу Slipways (предложено): (а) добавить технологии и структуры — превращают деньги во время (моя рекомендация); (б) научить бота растить планеты вглубь (lv3–4); (в) остановиться на ядре.
3. Balatro: ответ владельца «открывать ли деньги и магазин» всё ещё не получен; при «нет» — V-33 или V-34.
