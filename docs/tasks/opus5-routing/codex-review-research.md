## Summary

🙃 Деление верное; уверенность местами решила пожить отдельно от доказательств. Главная проблема — немедленный перевод Opus 4.8 workers: документ сам признаёт, что относительный Max quota burn ещё не измерен.

## Findings

1. **blocking — Немедленный switch с Opus 4.8 не следует из данных.**
   [research.md:19](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-opus5/docs/tasks/opus5-routing/research.md:19) и [research.md:308](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-opus5/docs/tasks/opus5-routing/research.md:308) рекомендуют прямой переход, хотя F2 оставляет relative quota burn неподтверждённым до production A/B. Одинаковая API-цена не гарантирует одинаковый расход Max. Нужен canary для specialist workers с теми же quota thresholds, что и для orchestrators.

2. **suggestion — API-equivalent dollars не дают достаточно устойчивой capacity-модели.**
   [research.md:257](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-opus5/docs/tasks/opus5-routing/research.md:257) содержит арифметически правильные расчёты, но внутренние коэффициенты расходятся: долгосрочно `$96.8/5h`, в последнем burst — `$29.67/5h`, а probe `$0.178` дал отображаемые `+2 pp` — около `$8.9/5h` при точном изменении. Поэтому `95–125/week`, `9–13/day` и `7–9/day` лучше назвать сценариями при допущении `$3–4/task`, а confidence снизить до `UNCERTAIN`.

3. **suggestion — “тот же quota bucket” доказан слишком сильно.**
   [research.md:107](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-opus5/docs/tasks/opus5-routing/research.md:107) показывает, что Opus 5 увеличивает общий Claude plan meter и отдельный бесплатный пул не обнаружен. Это не доказывает одинаковый вес Opus 5 и 4.8 внутри лимита или одинаковую механику 5h/weekly meters. Стоит именно так сузить утверждение.

4. **suggestion — Формула safety reserve неоднозначна.**
   [research.md:282](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-opus5/docs/tasks/opus5-routing/research.md:282) считает `30% baseline + 20 процентных пунктов reserve`: `382 × 0.5 / ($3–4) ≈ 48–64`, округлённо `50–65`. Если имелось в виду 20% от оставшихся после baseline ресурсов, получится примерно `54–71`. Нужно явно назвать выбранную формулу.

5. **suggestion — Решение по Fable опирается на API-цену как на Max quota weight.**
   [research.md:234](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-opus5/docs/tasks/opus5-routing/research.md:234) подтверждает 2× API-equivalent price, но не 2× расход подписочного лимита. Маршрут “manual escalation” можно оставить из-за близких benchmark results, однако формулировки `2× quota weight` и `NOT COST-JUSTIFIED` требуют отдельного Max-замера либо оговорки “по API-equivalent цене”.

6. **question — Как нормализованы 106 weekly percentage points?**
   [research.md:264](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-opus5/docs/tasks/opus5-routing/research.md:264) математически даёт `393 × 100 / 106 ≈ 371` completions, но не сказано, пересекал ли срез weekly reset и исключена ли параллельная Claude-нагрузка. Без этого `~370` — характеристика конкретного смешанного периода, а не надёжный weekly ceiling.

## Verdict

**REQUEST CHANGES.** Routing Sol оставить и orchestrator canary обоснованы; арифметика диапазонов корректна. Нужно убрать немедленный fleet switch с Opus 4.8 и ослабить quota-прогнозы до условных сценариев — сейчас линейка точная, а стол кривой.

## Round (2026-07-24T17:38:37Z)

## Summary

**Round 2.** 🙃 Пять из шести замечаний исправлены полностью; одно осталось в формулировке гипотезы. Blocking-проблем больше нет.

## Findings

1. **FIXED — prior blocking:** Opus 4.8 specialists теперь проходят отдельный metered canary с заданными порогами ([research.md:351](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-opus5/docs/tasks/opus5-routing/research.md:351)).

2. **FIXED — prior suggestion:** weekly/day estimates явно названы conditional scenarios с `UNCERTAIN` confidence ([research.md:283](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-opus5/docs/tasks/opus5-routing/research.md:283)).

3. **FIXED — prior suggestion:** shared-meter evidence больше не приравнивается к одинаковому model weight ([research.md:107](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-opus5/docs/tasks/opus5-routing/research.md:107)).

4. **FIXED — prior suggestion:** safety reserve однозначно определён как 20 процентных пунктов полного лимита, оставляя workers 50% ([research.md:292](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-opus5/docs/tasks/opus5-routing/research.md:292)).

5. **STILL BROKEN — suggestion:** Основной вывод по Fable исправлен, но H4 всё ещё утверждает `2× цену/квотный вес`, хотя Max weight не измерен ([research.md:62](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-opus5/docs/tasks/opus5-routing/research.md:62)). Стоит заменить на `2× API-equivalent цену; relative Max burn неизвестен`.

6. **FIXED — prior question:** исторический `393/106` теперь корректно обозначен rough calibration с возможными resets и параллельной нагрузкой ([research.md:267](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-opus5/docs/tasks/opus5-routing/research.md:267)).

7. **New suggestion:** Falsifier H2 логически не совпадает с гипотезой: рост общего meter подтверждает наличие расхода, но не опровергает равенство burn с Opus 4.8 ([research.md:50](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-opus5/docs/tasks/opus5-routing/research.md:50)). Настоящий falsifier — превышение matched Opus 4.8 baseline по 5h points/task, уже предусмотренное canary.

## Verdict

**APPROVED.** Оставшиеся замечания касаются точности формулировок, а не арифметики или routing-решения. Квотная модель теперь честно называется условной — калькулятор наконец перестал изображать провайдера.
