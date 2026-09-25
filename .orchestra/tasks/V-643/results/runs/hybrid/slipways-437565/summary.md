# V-46 Slipways: handoff summary (final)

## TASK STATE
- **Task #V-46** (from cog-second-brain-orchestrator): add the original game's mechanics to the Slipways core, teach the bots to use them, rerun the bots on the V-44/V-45 maps, then deliver a popular-science report, CHANGELOG entry, task report, commit and deploy.
- **Where the work lives:**
  - Branch: `task-V-46/slipways`, cut from main with V-45.
  - Repo root: `/home/kesha/orchestra/worktrees/opt-cog-second-brain/slipways`.
  - Project directory: `04-projects/slipways/`.
- **Phase:** full reruns are in progress.
  - Mechanics, bots, tests and the report-builder drafts are all committed.
  - Last commit: `828671a8` "WIP #V-46: lab economy guards (income floor, negative-income penalty), Quantum Computers first; KB slipways-rules".
- **Implemented and committed:**
  - Multi-import needs: a satisfied need accepts a second supply of the same resource, as in the game's `Need.Wants`/`RoutingDefault`.
  - Variable year length: `s.year`, `s.moy` (month of year), `s.month`, and `s.mods.monthsPerYear`, which techs set to 13 or 15.
  - Feature flags `{multiImport, council, science}`.
  - Council, quests, Esteem and race rewards (`src/quests.js`).
  - A1 build sites.
  - Labs, science, technologies and projects (`src/techs.js`).
  - Asteroid exploitation and stations.
  - Bot support for all of the above.
  - Map viewer support for labs and stations.
  - Run-spec options `rules=` and `gift=`, e.g. `greedy:rules=m`, `greedy:rules=mc`, `greedy:gift=2000`.
- **Tests:** `node --test tests/` passes 24 of 24.
- **Replay check:** with the new features off, the engine reproduces V-45 exactly. That was 200 greedy games plus 3 rollout games with 0 mismatches.
- **Running now:** bg job `bg-57f6630065`, started 2026-09-24 09:35 and expected to take about 3 hours. It expires 19:35 UTC.
- **Reported to the orchestrator so far:**
  - The inventory and the forks (A/B).
  - Interim results after A1/B1.
  - The stop/restart report (delivery `6b6d60f6-ea99-4db0-9c8e-548fdd821152`).
  - DONE has not been sent yet.

## OWNER & USER REQUIREMENTS (verbatim)
**V-46 assignment** from cog-second-brain-orchestrator, full text:
> #V-46: доработать ядро Slipways механиками оригинала. Владелец дословно: «Давай ядро улучшать. Дорабатывать. Технологии квесты и все такое.» Ветка task-V-46/slipways (от main с V-45). Что нужно на выходе: 1. Инвентаризация: какие механики оригинала есть в нашем движке, каких нет (технологии/исследования и наука, квесты и задания совета, члены совета, структуры, особые планеты/события — что найдёшь). Источник — исходники и данные игры на ноуте (только чтение, через laptop-access), а не память. Для каждой механики: влияние на счёт/время/деньги и цена реализации. 2. Реализовать в движке всё, что даёт существенный вклад в игру, начиная с технологий (они меняют деньги на время — это единственный путь выше потолка ~9.4k) и квестов. Если какая-то механика требует архитектурного выбора с заметной ценой (например, смена модели времени) — не выбирай молча, пришли мне развилку с ценой вариантов. 3. Боты (greedy и доигрыш) умеют пользоваться новыми механиками. Тесты только на механику, не на формулировки. 4. Перепрогон на тех же 100 картах V-44/V-45 по обеим сложностям, сравнение с V-45: как сдвинулся потолок и за счёт чего. Замер скорости движка до/после. 5. Научпоп-отчёт в том же стиле, что V-45 (вопрос в заголовке, аналогия, числа, графики, мораль, «чего мы не знаем»), плюс CHANGELOG, отчёт в .orchestra/tasks/V-46/, коммит, деплой тем же способом, что в V-45 (атомарно, /balatro/ не трогать, проверить соседей до и после). Тяжёлые прогоны — через bg_create или ssh kesha@localhost. Промежуточные находки, которые меняют план, присылай сразу.

**Orchestrator, after the owner chose:**
> Current #V-46: владелец выбрал A1 и B1. A1: для каждой карты заранее рассчитываются места под постройки, примерно 2–3 на планету. B1: тумана и зондов пока нет. Сервер Orchestra перезапускался посреди твоего хода, поэтому сначала проверь дерево и то, что уже закоммичено, потом продолжай по плану: фикс нескольких поставок на нужду (замерить отдельно), время, совет, задания, награды рас, астероиды, затем лаборатории/релеи по A1 и технологии. Финиш прежний: перепрогон на тех же 100 картах, сравнение с V-45 и научпоп-отчёт.

**Orchestrator, latest instruction:**
> Current #V-46: продолжай. Тебе не дошёл таймер bg-3d6a08be49 из-за квотного гейта: проверь результаты greedy-фазы в data/runs/*greedy*.jsonl. Полный прогон bg-1fd430b441 (greedy-варианты, rollout x4/x8, лог run_bots.log) ещё идёт — проверь его состояние сам. Дальше по плану: снабжение лабораторий → перепрогон → отчёт.

The lab-supply step is done. `bg-1fd430b441` was stopped and replaced by `bg-57f6630065`.

**slipways-notime (V-47), merge conditions (agreed):**
> (1) years может быть Infinity — yearsLeft(s) тогда должен возвращать Infinity (Math.max(0, Infinity − …) это и даёт), без округлений/циклов по годам до s.years; (2) лямбда у меня `s.years === Infinity ? p.moneyValue : p.moneyValue * left / s.years` — при 25 это твоя формула бит-в-бит, оставь, пожалуйста, ветку Infinity … Мой блок (skipYears/lastBuild/endReason: 8 лет подряд одних пропусков → finish('win') с endReason='stall', кап 200 лет) я перенесу в advance() сам, после того как твоя ветка попадёт в main — предлагаю мержить тебя первым, я ребейзнусь.

## DECISIONS
**Owner choices (via the orchestrator):**
- **A1 (chosen):** build sites are precomputed per map, about 2–3 per planet.
- **B1 (chosen):** no fog of war and no probes. As a result, the two Ba'qar quests ("открыть планеты", "разведать область") are not offered.
- **Rejected:**
  - A2, continuous placement: several days of work, and the bots would be many times slower.
  - B2, fog plus probes (3$ and 1 month each): 2–3 days of work, and it would muddle the comparison with V-45.

**Self-chosen and reversible.** I told the orchestrator «скажите, если не так»; there was no objection.
- The council of 3 races is picked randomly by map seed, as in Quick Start, and is the same for all bots.
- Techs are generated as in the game's code (template '012344' per race).
- Perks are not implemented in V-46.
- Techs with no expressible effect (energy, culture, hubs, etc.) can still be invented, for tech level and quests, but give no effect. The report must show their share.

**Engine signature, agreed with V-47:**
- `newGame(map, diff, {features, years})` with `s.years = opts.years ?? 25`.
- `yearsLeft = Math.max(0, s.years − s.year − s.moy/mpy)`.
- `evaluate` uses `lambda = s.years===Infinity ? p.moneyValue : p.moneyValue*left/s.years`.
- Merge order: V-46 goes into main first, then V-47 rebases onto it.

**Score attribution:** the fix to the multi-import core defect is measured separately, so the score gain splits into «исправление ядра» and «новые механики».

**Bot parameters.** Tuned on seeds 101–160 only; evaluation is on seeds 1–100, because V-45 tuning overfit.
- `scienceValue` 80, `labSites` 8, `maxLabs` 10.
- `projectReserve` 200, scaled by the fraction of years left.
- `labIncomeFloor` 20: a new lab is built only if yearly income stays at 20 or more afterwards.
- `negIncome` 100: penalty on negative income in the evaluation.
- `saveFor` 999, which turns off saving science for strong techs because saving didn't help.
- `PROJECT_ORDER` starts with `quantum_computers`.
- The extended candidate-slipway range applies only when science is on. This is the speed fix.

**First full run `bg-1fd430b441`:** stopped because of two defects.
1. 5 of 100 greedy games on Reasonable went bankrupt: lab upkeep is quadratic and labs can't be demolished.
2. Bot params never reached the project purchases, so the cash reserve was stuck at 20.

What happened to that run's results:
- **Kept:** `greedy:rules=m` and `greedy:rules=mc`. A recheck of 5 seeds per spec per difficulty (20 games) gave identical scores.
- **Moved to trash:** the invalid greedy, `gift=2000` and rollout partials.

**Speed cost accepted:** the V-46 engine is 28–38% slower on V-45 rules because of multi-supply lists, tech bonus checks, and sites/stations. This is deliberately not hidden by optimizations; the explanation is in `data/speed46.json`.

**Superseded:** the V-45 ban "do not add technologies or structures to the game core" is lifted by V-46. The owner said: «Технологии квесты и все такое».

## FILES, IDS AND ARTIFACTS
**Code** (`04-projects/slipways/`, committed):
- Changed: `src/{engine,bots,rules,sim,map-ui}.js`, `tests/engine.test.js`, `tests/bots.test.js`.
- New: `src/quests.js`, `src/techs.js`, `tests/science.test.js`.
- Report drafts, committed: `tools/build_report46.mjs`, `tools/report46-template.html`, `tools/report46-content.mjs`.
- Existing tools: `tools/run_bots.mjs`, `tools/build_stats.mjs`, `tools/bench_speed.mjs`, `tools/check_page.mjs`.
- `auto.html` has a nav link to `report46.html` and updated texts.
- `README.md` is updated.
- `CHANGELOG.md` is not updated yet.

**Data:**
- V-45 runs were moved to `data/runs-v45/` with `git mv`.
- `data/runs/` now holds only `{forgiving,reasonable}-greedy:rules={m,mc}.jsonl`; the new run writes there.
- `data/speed46.json`: before/after speed rows plus the explanatory text.

**Task folder `.orchestra/tasks/V-46/`:**
- `inventory.md`: 16 mechanics, each with its source in the game code, its impact and its cost.
- `bench_speed.txt`.
- `run_bots.log`: live; the run appends `EXIT=` when it finishes.
- `report.md` is still to be written.

**Knowledge base:** `.orchestra/kb/slipways-rules.md` was created, and a line was added to `.orchestra/kb/README.md`.

**Game sources** (read-only, V-43 snapshot):
- `/home/kesha/slipways-data-v43/`: `core/*.py` and `game.xls`.
- `/home/kesha/slipways-decomp-v43/`: decompiled `Slipways.dll`.

**Deploy (same method as V-45):**
- Release directory: `/var/www/cog-slipways/releases/<full commit sha>`, then switch the `current` symlink atomically.
- Public URL: https://photo-158-220-127-161.sslip.io/slipways/
- The V-45 release is `857446a112bbc2f23f8930b45ffef3a0a2b47767`.

**Commits:**
- V-45: HEAD `4a54ffa`; engine for benchmarks `bf32e56`.
- V-44: squash on main `270da3b`.

**Scratch files in /tmp:**
- `/tmp/v46_bench.sh`: runs a bench in 6 parallel chunks. Args: `bot diff seedFrom seedTo featuresJSON paramsJSON`.
- `/tmp/v46_sum.py`: summarizes bench output.
- `/tmp/v46_regress.mjs`: compares against `data/runs-v45`.
- `/tmp/v46_dbg.mjs` and `/tmp/v46_part*.mjs`.
- `/tmp/v45src`: the V-45 engine at `bf32e56`.

**Background job IDs:**
- `bg-57f6630065`: current run.
- `bg-1fd430b441`: stopped.
- `bg-3d6a08be49`: its timer was blocked by the quota gate.

**Raw transcript:** `/api/sessions/slipways/logs?scope=/opt/cog-second-brain`

## NUMBERS
**V-45 baselines** (seeds 1–100, Forgiving/Reasonable):

| Bot | Forgiving | Reasonable | Time per game |
|---|--:|--:|--:|
| greedy | 7887 | 6780 | |
| rollout ×4 | 9023 | 8315 | |
| rollout ×8 (best V-45 bot) | 9356 | 8714 | 34 s |

**Core fix alone (multiImport), 100 maps, greedy:** 7887→9866 on Forgiving and 6780→8636 on Reasonable, i.e. +25–27%. That is already above V-45 rollout ×8.

**Council and quests, maps 1–20, greedy:**
- Forgiving 10297→11347 (+10%); Reasonable 8486→9680 (+14%).
- 5–6 quests and 40–48 V per game. The owner got 24–98 V.

**Owner's own games (from the inventory):**
- Best scores 14126 and 13042 on Forgiving.
- 2750 and 4900 Legacy points from quests (55 and 98 V at 50 points each).
- Happiness ×140% and ×137%.
- 45 colonies, against the bots' 67.
- Unspent money at the end of the game: 2.5–4.9k for the owner, 4.4k for the bots.

**Scale of the new content:**
- A1 sites: about 780 per map.
- Techs: 87 from the game table, 45 of them with a modeled effect.

**Unlimited-science test** (maps 1–10, Forgiving): 22859 with it vs 11215 without, happiness up to ×141%.

**Old full run before the fixes** (`bg-1fd430b441`, all mechanics):
- Greedy: 15267 / 13453.
- Rollout ×4 on the first 52 maps: 20490 / 19009.
- Lab upkeep is quadratic: 9 labs cost 189$/yr. Before the fixes the bot built 4 labs, getting 3 science/yr for 44$/yr upkeep.

**Lab supply:** buying Quantum Computers first (+2 science per lab for 15$) raised science from 12.4 to 13.7/yr. The score change is within noise.

**`saveFor` tuning** (seeds 101–160, greedy, n=60, 0 losses in all):

| `saveFor` | Reasonable | Forgiving |
|--:|--:|--:|
| 70 | 12708 | 14810 |
| 999 (chosen) | 13018 | 15093 |
| 50 | 13208 | 14706 |

With 999: Reasonable techs 7.7, labs 6.2, science 13.7; Forgiving techs 7.4, labs 6.2, science 13.6.

**"2000 free science" (`gift=2000`, Forgiving, greedy):** 24046 vs 15267 without.

**Rollout ×4, all mechanics, seed 101:** 19411 points in 3 min 18 s.

**Speed benchmark** (`bench_speed.txt`; 40 greedy games on seeds 1–20 × both difficulties, 6 rollout games on seeds 1–3; single thread):

| Engine and rules | greedy | rollout | Hash |
|---|--:|--:|---|
| V-45 engine (`bf32e56`) | 13.7 s | 122.2 s | greedy `7f1fc9f29afb8d23`, rollout `a3933228fdac5412` |
| V-46 engine, V-45 rules, before range fix | 20.1 s | 169.6 s | same as V-45 |
| V-46 engine, V-45 rules, after range fix | 18.9 s | 158.0 s | same as V-45 |
| V-46 engine, all mechanics | 149.4 s | 1241 s | greedy `8a41c92f5b91ba6d`, rollout `68bb24254586550f` |

## CONSTRAINTS AND BANS
- **Push and publish:** do not push, and publish nothing except the authorized deploy (same method as V-45: atomic, check neighbours before and after).
- **Other projects:** do not touch `/var/www/balatro` or cog-balatro. Check `/balatro/` for 200 before and after the deploy.
- **Architectural forks** with a real cost go to the owner as a question; do not choose silently.
- **Laptop:** read-only, only via laptop-access. The game's sources are the reference, «а не память»; the wiki is not a source.
- **Heavy jobs:** run them through `bg_create` or `ssh kesha@localhost`. Never sleep to poll; end the turn and let the platform wake you.
- **Deleting files:** never use `rm -r`; move files to trash (a hook enforces this).
- **Tests:** «Тесты только на механику, не на формулировки».
- **Interim findings:** send any that change the plan to the orchestrator right away.
- **Bot tuning:** tune only on seeds 101–160 and evaluate on 1–100.
- **Commit messages:** use the format `#V-46: ...`.
- **Unresolved trailer conflict:** the earlier preference is no Co-Authored-By/watermark trailers. The platform's attribution reminder asks for one, and past commits include it.

## PEOPLE AND AGENTS
- **Owner:** gives tasks through the orchestrator.
- **cog-second-brain-orchestrator:** assigns tasks and receives reports and DONE via `send_message`.
- **slipways-notime:** the V-47 agent working on the engine's time model. Its merge conditions are recorded above. It will rebase after V-46 is merged.
- **Me:** the agent `slipways`, scope `/opt/cog-second-brain`.

## OPEN ITEMS AND NEXT ACTION
**Now:** wait for the wake-up from `bg-57f6630065`. The job runs `node tools/run_bots.mjs --seeds 1-100 --difficulties forgiving,reasonable --bots "greedy,greedy:gift=2000,rollout" --workers 7` over ssh, logging to `run_bots.log`.

**On wake-up:**
1. Check the `EXIT=` line in `.orchestra/tasks/V-46/run_bots.log`.
2. Check the row counts in `data/runs/*.jsonl`: 100 per difficulty per bot.

**Then, in order:**
1. Launch `rollout:width=8` on seeds 1–100, both difficulties, via `bg_create` plus ssh (about 6 hours). I promised this to the orchestrator: «после них запущу доигрыш ×8… если он не понадобится раньше».
2. Build stats and replays, then `report46.html`. It must include:
   - V-45 style: a question in the title, an analogy, numbers, charts, a moral, and «чего мы не знаем».
   - The shift of the ceiling versus V-45 and why, with the gain split into «исправление ядра» vs «новые механики».
   - Speed before and after.
   - The share of techs with no effect.
3. Write the `CHANGELOG.md` entry and `.orchestra/tasks/V-46/report.md`. Run the tests again.
4. Commit `#V-46: ...`.
5. Deploy atomically to `/var/www/cog-slipways/releases/<sha>` and switch `current`. Check the Slipways URLs and `/balatro/` for 200 before and after, and do a headless render check.
6. Send DONE to cog-second-brain-orchestrator via `send_message`.
