## Summary

Ну конечно, память согласилась быть точной — пока не сверили snapshots 😏

Базовая методика корректна: `PSS + SwapPss` подходит для process attribution, а `memory.current + memory.swap.current` — для отдельного cgroup-контроля; смешивать их как одну бухгалтерскую сумму нельзя, и отчёт это в целом признаёт. Арифметика основной таблицы сходится: строки дают `11.732 GiB`. Расчёт `codex_review` около `0.33 GiB/review` тоже сходится.

Однако точные выводы о snapshot total, освобождении `3.3–3.5 GiB`, составе swap, гарантированных `0–4 s` cleanup и независимости ranked gains требуют исправления. По порогу `review` ниты отброшены; ниже только влияющие на достоверность замечания.

## Findings (blocking/suggestion/question)

**Blocking:** нет. Это исследовательский отчёт; проблем уровня crash/corruption/security не найдено.

1. **[suggestion] Не называть 11.73 GiB единым snapshot**

   В § «Честная картина» ([research.md:32](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/docs/tasks/113/research.md:32), строки 32–45) Serena `4.09 GiB` импортирована из #112, где она включает четыре temporary review instances ([research.md:249](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/docs/tasks/113/research.md:249)), тогда как строка review текущей таблицы содержит три reviews. При среднем `0.67 / 4 ≈ 0.168 GiB` это известное несовпадение cardinality примерно на одну Serena review instance; остальной churn делает знак итоговой ошибки неизвестным. Сумма `11.73 GiB` арифметически верна, но является composite estimate из разных моментов, поэтому её нельзя подавать как snapshot 14:21:58 или использовать для точного delta с одновременным cgroup `15.41 GiB`.

2. **[suggestion] 3.3–3.5 GiB — footprint idle trees, а не доказанный gain**

   В § «Idle sessions» ([research.md:126](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/docs/tasks/113/research.md:126), строки 126–134), § «Рестарт» и итогах этот объём превращается из суммы текущего `PSS+SwapPss` в «освободится» и `CONFIRMED gain`. Это не следует из snapshot: после завершения подмножества процессов доли shared resident/swap могут перераспределиться оставшимся процессам, а file cache и часть cgroup charge могут остаться на машине. До измерения before/after корректная формулировка — «атрибутивный retained footprint idle trees 3.30–3.54 GiB; фактическое немедленное освобождение не измерено». Именно как текущая цена процессов вывод сильный; как обещанный выигрыш — завышенная уверенность.

3. **[suggestion] Исправить перекрывающийся “состав swap”**

   В § «Swap» ([research.md:168](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/docs/tasks/113/research.md:168), строки 168–171) под заголовком «Orchestra без Serena» перечислены `ordinary idle trees 2.43 GiB`, хотя выше прямо сказано, что эти trees включают Serena ([research.md:134](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/docs/tasks/113/research.md:134)). Кроме того, idle-tree total уже содержит относящиеся к этим деревьям CLI и MCP, которые затем перечисляются снова как отдельные классы. Это не состав/partition swap, а две пересекающиеся проекции. Их нужно разделить и явно запретить суммирование.

4. **[suggestion] В ranked gains не отмечены существенные overlaps**

   Таблица утверждает, что пересечения отмечены, но не отмечает как минимум два ([research.md:188](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/docs/tasks/113/research.md:188), строки 188–198):

   - `4.09 GiB` Serena включает `0.67 GiB` четырёх review instances, а выигрыш review isolation `0.255 GiB/review` уже включает примерно `0.168 GiB` Serena.
   - `0.255 GiB/review` включает `~0.040 GiB` KWin, который снова указан в следующей мере.
   - `0.665 GiB regular KWin + 0.040/review` не подтверждено census: `681 MiB = 0.665 GiB` — весь измеренный KWin total из 17 instances, а не явно выделенный regular-only subtotal.

   Таблица должна показывать gross gain каждой меры и marginal gain после мер выше; сейчас её значения нельзя складывать даже там, где пересечение не помечено.

5. **[suggestion] Согласовать confidence атрибуции main PID**

   § «Что реально держится в main» называет RAG/ONNX «подтверждённым куском» и «измеренным owner» ([research.md:97](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/docs/tasks/113/research.md:97), строки 97–116), но измерение подтверждает только `1.473 GiB` в крупных anonymous mappings. Anonymous mapping не идентифицирует владельца: это могут быть ONNX allocations, Python heap или другие native allocators. Малый persisted payload доказывает, что конкретные DB-поля и дисковый log store не равны гигабайтам, но не измеряет весь live heap объектов сессий/backend state. Финальное `LIKELY` на строке 234 соответствует доказательствам; ранние `CONFIRMED` и широкое `H1 REFUTED` нужно сузить до persisted histories/log cache.

6. **[suggestion] Убрать гарантию cleanup за 0–4 секунды**

   § `codex_review` утверждает, что leftover lifetime после leader exit ограничен `0–4 s` ([research.md:149](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/docs/tasks/113/research.md:149)). Код вызывает `killpg` только если descendant продолжает держать stdout и reader не получает EOF за две секунды ([bg_jobs.py:676](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/app/bg_jobs.py:676), строки 676–706). Descendant, закрывший stdout, но оставшийся в той же process group, обойдёт этот путь; финальный `_kill_proc()` также сразу возвращает, если leader уже завершён ([bg_jobs.py:114](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/app/bg_jobs.py:114), строки 114–133). Ему не требуется менять process group. Snapshot подтверждает лишь «orphans сейчас не найдены»; кодовой верхней границы lifetime нет.

7. **[suggestion] Не приравнивать retained footprint к active working set**

   В § «Swap» ([research.md:166](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/docs/tasks/113/research.md:166), строки 166–177) из `15.4 GiB Orchestra + 8.5 GiB desktop retained` делается вывод, что working set больше RAM и именно поэтому kernel ушёл в swap. Retained уже включает холодные swapped pages, cache и kernel charge, поэтому сравнение с RAM показывает объём логически удерживаемого состояния, но не размер активного working set и не устанавливает причинность. Свежий boot действительно опровергает «swap остался после недель uptime», а fault/churn trace доказывает активное возвращение части страниц; связь всего роста с RAG/reviews и исключение иных причин остаются `LIKELY`, не `CONFIRMED`.

8. **[suggestion] Представить restart/reboot числа как ceilings, не измеренный эффект**

   В § «Рестарт сервиса или reboot» ([research.md:179](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/docs/tasks/113/research.md:179), строки 179–184) `11.7/15.4 GiB` — pre-restart footprint, а не измеренный объём, который станет свободной RAM: process exit освободит private anonymous memory и swap entries, но shared/file-cache charge не обязан немедленно исчезнуть с машины. Аналогично один свежий boot показывает, что при наблюдавшейся нагрузке swap набрался за часы; он не доказывает безусловный возврат после любого следующего reboot. Направление вывода верное — reboot не устраняет источник, — но количественная уверенность выше данных.

9. **[suggestion] Сохранить проверяемый след ключевых измерений**

   § «Источники и измерения» ([research.md:244](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/docs/tasks/113/research.md:244), строки 244–262) перечисляет источники M1–M13, но почти все являются описаниями эфемерных команд без сохранённых PID sets, SQL, raw counters и точных timestamps каждого составного snapshot. Поэтому независимо проверить classification, отсутствие overlap, idle membership и deltas уже нельзя. Serena `4.09 GiB` принимается как разрешённое внешнее измерение, но её timestamp/cardinality всё равно нужны для корректного объединения с M1/M10.

## Verdict

**Verdict: требует исправлений, но основное направление исследования выдерживает проверку.**

Можно принимать следующие выводы: RSS-сумма была плохой метрикой; отдельное сравнение process `PSS+SwapPss` и cgroup charge методологически разумно; Serena и live CLI/MCP — крупные классы; `codex_review` стоит около `0.33 GiB` в steady state; свежий boot опровергает «недельный остаток swap»; RAG/ONNX — вероятный, но не доказанный owner main anonymous memory.

Нельзя пока принимать как подтверждённые точные `11.73 GiB snapshot`, `3.54 GiB hibernation gain`, взаимно независимые ranked savings, гарантированный cleanup за четыре секунды и строгую причинность swap. Иначе это не бюджет памяти, а счёт, где Serena незаметно заказали дважды.
