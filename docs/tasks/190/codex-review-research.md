## Summary

Независимый пересчёт выполнить невозможно: разрешённый snapshot отсутствует. Фактический вывод команды:

```text
Traceback (most recent call last):
  File "/home/kesha/orchestra/worktrees/home-kesha-orchestra/subscription-decision/docs/tasks/190/analyze.py", line 37, in <module>
    db = sqlite3.connect(DB)
         ^^^^^^^^^^^^^^^^^^^
sqlite3.OperationalError: unable to open database file
```

Проверка наличия дала:

```text
ls: cannot access 'data/tmp190/snap.db': No such file or directory
```

Поэтому результаты ниже — аудит логики `analyze.py` и внутренних противоречий трёх разрешённых файлов, а не независимое подтверждение чисел из БД.

Главный итог: рекомендация оставить $300 не доказана. Документ показывает ценность Codex во время одного 47.8-часового сбоя, но не устанавливает ожидаемую частоту таких сбоев и не сравнивает её со стоимостью варианта $220. Вывод «ревью ≈5%» особенно ненадёжен: метод A смешивает разные периоды и экстраполирует 18 произвольно сохранившихся файлов на 125 вызовов, а метод Б статистически не способен подтвердить нулевой расход ревью.

## Findings

1. **blocking — Claim 1, “codex_review ≈5%”: OVERSTATED. Метод A имеет несогласованный знаменатель и период.**

   Число вызовов считается по всей таблице `logs`, без ограничения дат:

   ```python
   calls = db.execute(
       """SELECT COUNT(*) FROM logs WHERE type='tool'
          AND (content LIKE 'mcp__orchestra__codex_review:%'
               OR (content LIKE 'Bash:%' AND content LIKE '%codex exec%'))"""
   ).fetchone()[0]
   ```

   При этом расход воркеров берётся из `turn_usage`, существующего только за 8.15 суток. Следовательно, заявленные «125 вызовов за период» кодом не обеспечены: это потенциально all-history numerator против 8.15-day denominator.

   Дополнительно usage ревью берётся лишь из 18 файлов, сохранившихся в `/tmp` на момент запуска, без проверки, что они принадлежат тому же периоду или репрезентативны. Масштабирование `calls / n` предполагает одинаковое распределение размеров у сохранившихся и исчезнувших 107 ревью. Сам документ признаёт возможную систематическую ошибку.

   До добавления одинаковых временных границ и постоянного учёта usage вывод 5.3–5.6% нельзя использовать для покупки тарифа.

2. **blocking — Claim 1, метод 4Б: REFUTED как “независимое подтверждение 5%”.**

   Около десяти почасовых точек с целочисленным счётчиком не могут оценить малую добавку от 48 ревью. Более того, метод вообще не оценивает коэффициент ревью: он сравнивает две агрегированные ставки и интерпретирует отрицательный residual как ноль.

   В документе:

   > Предсказание по «чистой» ставке для часов с ревью: **20.8 пп, факт 16 пп.**

   Разница −4.8 п.п. намного больше заявленных ±0.5 п.п. квантования. Это свидетельствует, что модель ставки нестабильна или интервалы атрибутированы неверно, а не доказывает бесплатность ревью.

   Технические причины:

   - расход нормируется только на `input_tokens`, хотя rate card отдельно взвешивает fresh input, cached input и output;
   - ставка из четырёх “чистых” часов переносится на часы с другим составом работы;
   - `util[hour]` хранит последнее наблюдение часа, а токены суммируются по календарному часу; дельта между последними snapshots соседних часов не совпадает с интервалом токенов этого часа;
   - квантование относится к каждому endpoint и разностям, а не даёт общей гарантии ±0.5 п.п.;
   - нет доверительного интервала или верхней границы для расхода 48 ревью.

   Метод Б не различает 0%, 5% и потенциально заметно большую долю. Он не подтверждает метод A.

3. **blocking — Claim 2, “76% во время blackout”: OVERSTATED.**

   Арифметика `270 / 353 ≈ 76%` в коде корректна, но границы жёстко вшиты:

   ```python
   ts>='2026-08-09T07:25' AND ts<='2026-08-11T07:13'
   ```

   `analyze.py` не выводит эти границы из `usage_snapshots` и не проверяет состояние Claude на каждом включённом timestamp. Они заимствованы у другого анализа. Без snapshot нельзя проверить пограничные ходы или sensitivity-анализ со сдвигом начала/конца.

   Кроме того, это 76% не «всей работы Codex» в устойчивом смысле, а работы за короткий 8.15-дневный период, специально содержащий единственный 47.8-часовой blackout. Сам документ признаёт, что период смещён в пользу Codex. Корректная формулировка: «76% зарегистрированных Codex-ходов в доступном восьмидневном срезе попали в заранее заявленное окно».

4. **blocking — Claim 3, “124% / 154% Claude pool”: OVERSTATED и зависим от непроверенного tier-2 input.**

   Пул не выводится из snapshot:

   ```python
   POOL_TURNS, POOL_USD = 1010, 1730  # замер quota-policy #186
   ```

   Это hard-coded результат другого агента. Поэтому `analyze.py` пересчитывает проценты из предположения, но не подтверждает сам знаменатель.

   Чувствительность к ошибке пула ±20%:

   - пул 808 ходов: Claude-only спрос ≈155%, без Codex ≈192%;
   - пул 1010: 124% и 154%;
   - пул 1212: ≈103% и ≈128%.

   Вывод «без Codex не помещается» сохраняется даже при +20%, но сила утверждения резко меняется: собственная нагрузка Claude оказывается лишь примерно на 3% выше пула, а не на 24%.

   Ещё важнее, линейная экстраполяция 8.15 нетипичных суток включает 47.8 часа, когда Claude был capacity-censored и почти не мог производить ходы. Это не нейтральная выборка недельного спроса. Числа годятся как сценарий этой недели, но не как оценка устойчивого недельного спроса.

5. **suggestion — Claim 4, `N = 7.8`: OVERSTATED в рамках этого артефакта.**

   `analyze.py` вообще не рассчитывает `r`, bootstrap CI или `N`. Значение полностью импортировано из `quota-policy #186`, хотя вступление обещает:

   > Все числа ниже — вывод `docs/tasks/190/analyze.py`, а не оценки.

   Значит `N = 7.8` не воспроизводится предоставленным анализом и должно называться external measured input, а не результатом этого скрипта. Без исходного расчёта нельзя проверить выбор сегментов, сбросы счётчика и bootstrap unit.

6. **suggestion — Claim 4, абсолютный Max5/Max20 weekly-ceiling ratio “unmeasurable”: CONFIRMED для предоставленных данных, но формулировку нужно сузить.**

   Отношение `r = 5h limit / weekly limit` для двух тарифов даёт лишь относительное изменение формы лимитов. Чтобы получить отношение абсолютных weekly ceilings, нужен хотя бы один общий абсолютный якорь: одинаково измеренный расход на процент квоты в обоих тарифных периодах.

   `turn_usage` начинается после возвращения на Max20, поэтому для Max5 такого якоря здесь нет. Проценты `usage_snapshots` сами по себе масштаб не раскрывают. Официальный множитель тарифов может определить advertised 5h ratio, но не неопубликованный weekly ratio.

   Теоретически измерение возможно будущим контролируемым экспериментом: одинаковая модель, новый/чистый контекст, одинаковая workload basket на обоих тарифах, измерение абсолютных токенов/стоимости и Δ5h/Δ7d. Поэтому корректно «неизмеримо из этого исторического snapshot», а не безусловно «неизмеримо».

7. **blocking — Claim 5, финальная рекомендация $300: OVERSTATED; данные также совместимы с вариантом $220.**

   Документ доказывает условное утверждение: если каждые несколько недель повторяется двухсуточный Claude blackout и работа во время него ценна, Pro $100 окупает доступность. Но он не оценивает:

   - частоту будущих blackout;
   - стоимость часа простоя для одного пользователя;
   - сколько работы можно отложить;
   - цену докупаемых кредитов на Plus;
   - какую долю Sol-работы можно перенести на Luna/Claude вне blackout;
   - ожидаемую пользу Spark.

   Вариант $220 сохраняет cross-runtime review и CLI, экономит $80 ежемесячно и, согласно самому документу, покрывает типичную review-нагрузку — хотя точность этих 28% сейчас сомнительна. Один экстремальный эпизод не устанавливает expected monthly loss.

   Правило «downgrade only after two consecutive weeks under 100%» не выведено из данных. Оно игнорирует недели ровно на 100%, сезонность, ожидаемый ущерб и тот факт, что наблюдалось лишь два weekly-blackout эпизода за 38 суток. Это управленческая эвристика, представленная как доказанный порог.

8. **suggestion — Несовпадение прозы со скриптом и tier-2-as-measured встречаются системно.**

   Помимо `N` и пула Claude:

   - Max5/Max20 периоды, пики, проценты snapshots и 9.4 часа простоя не рассчитываются `analyze.py`;
   - 72 часа блокировок за 38 суток не рассчитываются скриптом;
   - blackout boundaries не выводятся скриптом;
   - `DAYS = 8.15` задано константой, а не вычислено из фактических `MIN(ts)`/`MAX(ts)`;
   - rate card в комментарии скрипта назван tier 2 из старого артефакта, тогда как prose говорит о подтверждении свежим первоисточником;
   - `POOL_TURNS=1010` и `$1730` — результат другого агента, хотя секция получает уверенность “CONFIRMED — tier 1”;
   - метод A печатает долю ревью в сумме `review + workers` (5.3%), тогда как таблица 2.5 печатает недельный review расход как долю отдельной оценки полного пула (5.6%). Это разные знаменатели, а текст объединяет их в один тезис «ревью — 5%».

   Начальное обещание «все числа — вывод analyze.py» следует удалить или заменить таблицей provenance для каждого load-bearing числа.

## Verdict

Исследование не готово служить основанием для решения о $300/месяц.

Статусы пяти claims:

1. `codex_review ≈5%` — **OVERSTATED**; метод A несогласован по периоду и выборке, метод Б неидентифицируем и не подтверждает 5%.
2. `76% во время blackout` — **OVERSTATED**; арифметика правдоподобна, но границы не воспроизведены, а короткое окно selection-biased.
3. `124% / 154% Claude pool` — **OVERSTATED**; арифметика условно верна, но знаменатель заимствован, а экстраполяция нетипична. При ±20% пула вывод «не помещается» сохраняется, проценты — нет.
4. `N=7.8` — **OVERSTATED** как результат этого анализа; абсолютный Max5/Max20 weekly ratio — **CONFIRMED unmeasurable from the supplied historical data**.
5. Рекомендация оставить $300 — **OVERSTATED**; имеющиеся данные не отделяют её от рационального варианта $220 без оценки будущей частоты и стоимости простоя.

Для решения сегодня честный вывод: $300 — покупка страховки от повторения недавнего экстремального blackout, а не вариант, доказанный средним спросом. Если Максим ценит возможность непрерывной работы во время следующего двухсуточного отказа выше $80/месяц, оставить $300 разумно. Если это редкое событие и работу можно отложить, тот же документ столь же совместим с $220.

## Round (2026-08-11T10:26:04Z)

## Summary

The script now runs successfully against the absolute snapshot. Key verbatim output:

```text
Наблюдённый спрос Claude:   1252 ходов/нед = 127% пула
+ работа, ушедшая на Sol:    303 ходов/нед
ИТОГО без Codex:            1556 ходов/нед = 158% пула
```

Round 1 findings F1, F3, F5, and F6 are fixed. F2 is mostly fixed in presentation but still claims an unsupported “upper bound.” F4 and F7 retain load-bearing methodological problems. F8 has a new reproducibility mismatch caused by live `/tmp` inputs.

`git diff --` emitted no output for the three allowed files, so this review covers their current contents rather than a visible uncommitted diff.

## Findings

1. **blocking — F7 STILL BROKEN: “demand > pool, therefore blackouts must recur” is circular and treats quota-shaped activity as exogenous demand.**

   The measured 1,252 turns/week is throughput under the current quota and routing policy, not unmet demand. Work can expand to consume available capacity:

   - agents may be spawned because quota is available;
   - work may be accelerated before an expected reset;
   - tasks may move to Codex when Claude blocks;
   - lower capacity may cause prioritization, shorter turns, or deferred optional work.

   Saturating a rolling quota proves that the present workflow can consume the pool. It does not prove an invariant external arrival rate of 1,252–1,657 Claude turns/week.

   The prose is too strong:

   > Пока спрос выше потолка, следующая блокировка не «может случиться», а наступит.

   That conclusion requires evidence of an independent backlog or arrival rate that remains above capacity after behavioral adaptation. The data contains executed turns, not attempted-but-denied turns or queued demand. A defensible replacement is: “If workload generation and routing remain comparable to this eight-day period, another weekly saturation is likely.” It cannot be called structurally inevitable.

2. **blocking — F4 STILL BROKEN: the newly derived 984-turn “pool” is not necessarily a full weekly capacity measurement.**

   The script counts turns while the rolling 7-day percentage moves from ≤2% to 100%:

   ```text
   Окно 7d от ~0% до 100%: 2026-08-04T08:10 -> 2026-08-09T07:25
   Израсходовано за него: 984 ходов Claude, $1654
   ```

   During that five-day interval, earlier usage can expire from the rolling window. Therefore:

   `final utilization − initial utilization ≠ gross usage added`

   unless the script verifies that no material usage aged out. If usage expired, the 984 turns represent more than approximately 98 percentage points of gross consumption, so dividing later demand by 984 understates the true pool.

   The close agreement with 1,010/$1,730 is useful corroboration but is not independent if both methods use overlapping data or the same rolling-window assumption. The qualitative saturation observation is sound; exact 127%, 158%, and 168% ratios are not yet independently established.

3. **blocking — F7 NEW BUG: the 168% censoring correction is not a legitimate estimate of latent demand.**

   The calculation assumes the non-blocked execution rate would have continued unchanged through all 47.8 blocked hours:

   ```text
   Темп в НЕзаблокированные 148 ч:
   9.9 ходов/ч -> 1657 ходов/нед =
   168% пула ЕЩЁ ДО добавления работы Sol.
   ```

   That is not a censoring correction unless demand is exogenous, stationary, and unaffected by routing. None is demonstrated.

   In this dataset, 270 Codex turns occurred during the blocked interval. Much of the allegedly missing Claude work was therefore substituted onto Codex rather than censored. Imputing 9.9 Claude turns/hour into that interval estimates a counterfactual “Claude if Codex did not substitute”; adding Sol work to that estimate would double-count. Even without explicitly adding Sol, calling the result “Claude demand before Sol” is misleading because the observed non-blocked Claude rate arose under a two-runtime system.

   The uncorrected `Claude + Codex = 158%` scenario is the more defensible capacity calculation, subject to the pool caveat above. The 168% figure should be removed or labelled a constant-rate counterfactual, not a correction with known bias direction.

4. **suggestion — F2 STILL BROKEN narrowly: method Б does not supply an upper bound.**

   The rewrite correctly admits that method Б cannot estimate the review share. However, both script and prose still say it gives an upper bound:

   ```text
   Он даёт только верхнюю границу:
   вклад ревью меньше разброса самой ставки.
   ```

   A negative residual under an unstable baseline does not bound review consumption. If worker charging rates in review hours were sufficiently lower than in control hours, a positive and potentially material review charge could be hidden by that difference. No bound on baseline instability is calculated.

   Correct conclusion: method Б is inconclusive. Remove “upper bound” and “вклад меньше разброса” unless the script calculates an empirical distribution or confidence interval for the worker-only rate.

5. **suggestion — F1 FIXED, but method A remains only a scenario estimate.**

   The period mismatch is genuinely fixed:

   ```text
   Вызовов ревью В ПЕРИОДЕ turn_usage: 125  (за всю историю logs: 125)
   Числитель и знаменатель теперь на одном периоде. Разницы нет: вне периода вызовов 0.
   ```

   The expanded representativeness sensitivity is an honest improvement. However, testing only 1.5×, 2×, and 3× does not establish that 3× is a statistical upper bound. Thus “central estimate 7%, plausible scenarios 3–18%” is supportable; “even the upper edge” is not, because the edge was selected rather than measured.

6. **suggestion — F8 NEW BUG: current prose does not match current script output because `/tmp` is mutable.**

   Current script output:

   ```text
   Замерено ревью с usage-событием: 23 из 125 (18%)
   медиана: вход 151,067, выход 2,630

   кредиты ревью    ≈     1173
   ДОЛЯ РЕВЬЮ в расходе Codex = 6.6%
   ```

   Current prose says 25/125, median 155,947, 1,180 credits, and 6.7%. The caller’s changelog also expected 25, but two files disappeared or changed before this run.

   This demonstrates that `analyze.py` is not reproducible from `snap.db`: a load-bearing result depends on mutable `/tmp/codex_review_*.jsonl`. Persisting the sampled usage beside the snapshot, or recording the exact aggregate in a snapshot table/file, is necessary before claiming the report can be recomputed independently.

7. **suggestion — F3 FIXED: blackout boundaries and enrichment are now appropriately data-derived.**

   The recomputed result supports the descriptive claim:

   ```text
   7d = 100%: 2026-08-09T07:25 -> 2026-08-11T07:12  =  47.8 ч
   codex   ходов  270  $  493.6   (76.5% всех своих ходов за период)
   ```

   The sensitivity result is also useful: narrowing both boundaries by six hours still retains 171 Codex turns, or 48% of all Codex turns. This establishes strong temporal association with the blackout.

   It does not by itself establish future blackout frequency, but the revised prose now largely acknowledges that distinction.

8. **suggestion — F5 and F6 FIXED; F8 provenance is improved but not fully closed.**

   `N=7.3` and tariff names are now explicitly external inputs. The Max5/Max20 conclusion is correctly narrowed to “unmeasurable from this historical snapshot,” and the controlled experiment that could measure it is named.

   The remaining provenance defect is the opening statement that the script computes “почти всё”: the review estimate is partly produced by mutable external `/tmp` files, while the plan names, tariff boundaries, `N`, and some operational claims remain external. The explicit table is honest enough, but `/tmp` should appear in it as a non-snapshot input.

## Verdict

**NOT APPROVED** for an unconditional $300 recommendation.

The document now supports these narrower conclusions:

- Codex usage was strongly concentrated during the measured Claude blackout.
- $20 likely covers review-only usage, although the precise share is not reproducible and has no measured upper bound.
- $100 provides materially more failover capacity.
- The observed workflow saturated Claude’s weekly quota.

It does not prove that future blackouts are structurally inevitable. The 168% correction assumes constant, exogenous demand and partially imputes work that Codex actually performed. The honest money decision remains conditional: $300 buys protection if the recent workload and routing behavior continue; $220 remains equally evidence-compatible if work contracts, is prioritized, or expands merely to fill available quota.

## Round 2

- F1: **FIXED**
- F2: **STILL BROKEN** only as an alleged upper bound; correctly withdrawn as a share estimate
- F3: **FIXED**
- F4: **STILL BROKEN** because rolling-window expiry is not accounted for in the 984-turn pool
- F5: **FIXED**
- F6: **FIXED**
- F7: **STILL BROKEN** in the structural-inevitability and 168% censoring claims
- F8: **NEW BUG** — prose/script mismatch from mutable `/tmp` review files
