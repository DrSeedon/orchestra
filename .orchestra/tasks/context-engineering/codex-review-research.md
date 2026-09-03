## Summary

Ну да, проценты опять оказались менее сговорчивыми, чем выводы. 🧮 Обрезка Codex и двойное включение `background-jobs` подтверждаются, но расчёт доли, полная загрузка Claude и безопасность архивации доказаны недостаточно. Блокирующих проблем нет; четыре предложения и один вопрос.

## Findings (blocking/suggestion/question)

1. **[suggestion] Исправить долю загруженного файла.**  
   В [research.md:12](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-fullcycle/docs/tasks/context-engineering/research.md:12) утверждается, что из 61 643 байт доезжает 32 806, то есть 47%. Фактически это **53,2%**; 46,8% — потерянная часть. Следовательно, «меньше половины» и H2 в текущей формулировке неверны. Обрыв также находится внутри строки 375 текущего [CLAUDE.md:375](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-fullcycle/CLAUDE.md:375), а не 374.

2. **[question] Проверка хвоста не доказывает загрузку Claude на 100%.**  
   Воспроизведение последнего раздела и последней строки в [research.md:62](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-fullcycle/docs/tasks/context-engineering/research.md:62) доказывает доступность хвоста, но не отсутствие пропусков внутри файла. Для вывода «100%» нужен сохранённый вход либо уникальные маркеры в начале, середине и конце.

3. **[suggestion] Не обобщать расчёт Claude-кэша на всю статику и Sol.**  
   В [research.md:81](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-fullcycle/docs/tasks/context-engineering/research.md:81) используются коэффициенты Anthropic, цена Opus `$5/M` и допущение об одной записи кэша на всю persistent-сессию. Строка `worker/codex` в расчёте не участвует, а повторные cold starts после TTL не учтены. Поэтому общий вывод «2–5% для бэкендов» из приведённых данных не следует; арифметика `$0.75` верна только внутри выбранного сценария.

4. **[suggestion] Не считать семь текущих поисков проверкой архивации.**  
   В [research.md:116](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-fullcycle/docs/tasks/context-engineering/research.md:116) большинство ответов пришло из других документов и логов, остальные — из ещё не архивированного `CLAUDE.md`. Ни один запрос не проверяет уникальный фрагмент после переноса и переиндексации. Более того, оговорка про boot в строке 128 фактически оставляет H3 открытой.

5. **[suggestion] R3 может затереть нативный `AGENTS.md`.**  
   Предложение перезаписывать зеркало по `mtime` в [research.md:193](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-fullcycle/docs/tasks/context-engineering/research.md:193) уничтожает защиту репозиториев с собственным `AGENTS.md`, ради которой существует проверка в [workspace.py:243](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-fullcycle/app/workspace.py:243). Обновлять можно только файл, ранее созданный именно как зеркало.

6. **[suggestion] R4 удаляет доказанный anti-sleep guard.**  
   Сокращённые три строки из [research.md:197](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-fullcycle/docs/tasks/context-engineering/research.md:197) не сохраняют запрет sleep/poll из [base.md:41](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-fullcycle/pipelines/default/prompts/base.md:41). `worker/full-cycle` модуль не получают, а `bg_create` этого запрета не содержит. Это вернёт уже измеренное зависание Codex.

## Verdict

Исследование требует доработки перед реализацией R1–R4. Обрезка и дубль реальны, но три остальных несущих вывода сильнее своих измерений — фундамент есть, только пара несущих стен нарисована мелом.
