# #207 — убрать неподтверждённую цифру MRCR, снизить эффорт full-cycle

Файлы: `pipelines/default/prompts/modules/model-routing.md`, `pipelines/default/pipeline.yaml`.
Основание — `docs/tasks/204/research.md` (смержено в `a100f77`).

## Правка 1 — обоснование ограничения переписано, само ограничение осталось

Было: `never for resolving references between similar fragments (vendor MRCR: Luna 41.3% vs Sol
91.5%, untested here)`.

Стало: `Long context ONLY for EXTRACTION — finding explicitly marked places in a big input (9/9 at
164K). Resolving references across similar fragments we have never measured → that one goes to
Sol. This is caution, not a known cliff: the third-party number once quoted here failed
attribution, and an independent long-context benchmark shows no gap at any working effort.`

Почему так: #204 открыл первоисточник, на который ссылался Vellum
(`openai.com/index/previewing-gpt-5-6-sol/`, 57 КБ сырого текста) — **слова «MRCR» там нет вовсе**,
таблицы с 41.3% нет. Независимая проверка по существу (AA-LCR, вывод по ~100К токенов) обрыва не
воспроизводит: Luna `low 0.653 / medium 0.720 / high 0.740 / xhigh 0.733 / max 0.783` против Sol
`0.730 / 0.743 / 0.753 / 0.763 / 0.777`; единственный провал — режим без рассуждения (0.387).

Ограничение оставлено, потому что оно опирается на НАШ замер: #199 T4 мерил извлечение (5 иголок
из 164К, 9/9), а разрешение ссылок между похожими фрагментами не мерил никто у нас. Формулировка
теперь называет это своим именем — осторожность, а не измеренный обрыв.

## Правка 2 — `full-cycle`: `xhigh` → `high`

`pipeline.yaml:71`, рядом комментарий из шести строк: основание (Anthropic для Opus 5 велит
начинать с `high` и не переносить настройки прошлого поколения; девять чужих бенчмарков дают
+47% цены без значимого прироста; наш #199 на Sol — ×2.04 при том же вердикте) **и незакрытый
контраргумент** (вендор оправдывает xhigh длиной горизонта, а все опубликованные замеры короче
наших сессий; правка обратимая, разваливающиеся длинные ходы = данные за возврат).

**Что реально меняется, а что нет.** Для Claude-моделей `xhigh` и так молча понижался до `high`
(`app/backend_claude.py:210`), так что для них правка делает манифест честным, а поведение не
трогает. Бьёт она по Codex-бэкенду: там `xhigh` доезжал до CLI как есть. По живым сессиям:
`full-cycle` claude 23, codex 17 — то есть фактическое изменение поведения касается 17.

**Существующие сессии не затронуты.** Эффорт берётся из манифеста только при спавне
(`app/manager.py:660-662`); при загрузке/восстановлении — из строки БД (`:1202`, `:1518`). У 40
живых full-cycle в БД записан `xhigh`, и он там останется до пересоздания. В БД не лез: правка
живых сессий вне мандата и вне безопасного окна.

## Правка 3 — вынужденная, тем же диффом

Пункт Sol цитировал значения манифеста: `Closed work goes to the worker role (manifest effort
high), never to full-cycle (xhigh)`. Правка 2 делает эту скобку ложной в тот же день. Стало:
`Closed work goes to the worker role, never to full-cycle: phases and gates buy nothing on a task
that is already specified, and raising effort bought nothing either — on the two closed tasks
measured it cost ×2.04 and ×1.13 without changing the verdict.` Маршрут держится теперь на
семантике ролей (фазы и гейты), а не на числе, которое живёт в другом файле.

## Приёмка

```
role              effort mrcr_gone caution stale_xhigh_claim bytes
orchestrator      medium True      True    False             43150
sub-orchestrator  medium True      True    False             43501
worker            high   True      False   False             23083
full-cycle        high   True      True    False             42162
```
`mrcr_gone` — строки «41.3» нет ни в одном собранном промпте; `caution` — новая формулировка
доехала до трёх спавн-способных ролей; `stale_xhigh_claim` — устаревшей скобки нет нигде;
`worker` по-прежнему без блока маршрутизации (#203). `effort` читан из манифеста через `get_role`.

Тесты: `tests/test_default_pipeline.py tests/test_pipeline.py tests/test_manager.py` — **288
passed** (`/tmp/pytest-207.log`). Тестов, прибитых к `xhigh` в манифесте, нет
(`grep -rn "xhigh" tests/` — только `test_backend_codex` про допустимые значения и
`test_backend_grok` про понижение, оба к манифесту не относятся).

Отдельного теста на значение эффорта не добавлял осознанно: решение объявлено обратимым, а тест
превратил бы откат в правку теста. Откат = одна строка манифеста.

## Codex — один раунд, находок нет

`docs/tasks/207/codex-review-impl.md`. Дословно из вердикта: «The Luna rule remains deterministic
because the explicit "that one goes to Sol" prescription overrides the evidentiary caveat without
claiming a measured failure. Closed work still routes decisively to `worker` based on the absence
of useful phases and gates… The `full-cycle` comment appropriately records both the basis and
unresolved long-horizon counterargument without contradicting `effort: high`.»

Второго раунда нет: ни одной находки, спорить не о чем.

**Замечание Codex, которое не чинил** (его же оговорка «this patch does not introduce or worsen
them»): в блоке остаются другие значения, дублирующие манифест, — id моделей и строка
`Orchestrators — always Opus 5`. Это тот же класс, что скобка `(xhigh)`, только пока не протухший.
Кандидат на отдельную задачу: id брать из манифеста или не называть в промпте вовсе.
