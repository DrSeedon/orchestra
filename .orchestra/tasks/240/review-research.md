<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

Ну да, 41 инструмент в конфиге ещё не означает, что клиент их действительно увидел. 🔬 Архитектурный вывод подтверждён: Orchestra запускает CLI `app-server` и общается с ним по JSON-RPC, не через Python SDK. Исправленная A/B арифметика total-to-final также верна. Однако вывод о влиянии MCP опирается на неполный контроль и блокирует одобрение.

## Findings

blocking: [docs/tasks/240/research.md:142](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-latency/docs/tasks/240/research.md:142) — Сырые строки доказывают наличие MCP-конфигурации и отдельно вычисленный размер локального реестра, но не успешную инициализацию MCP и получение app-server всех 41 инструментов. PONG не вызывает tools, а backend-замеры не сохраняют результат MCP startup/tools-list. Поэтому `CONFIRMED no stable wall penalty` и вывод о неэagerной загрузке схем могут описывать неработающий MCP → до положительного подтверждения discovery классифицировать MCP-вывод как `UNCERTAIN`.

suggestion: [docs/tasks/240/research.md:130](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-latency/docs/tasks/240/research.md:130) — A/B total-time посчитан правильно, но две пары при секундном собственном разбросе не дают статистического верхнего предела «at most sub-second» → сформулировать как «в этих двух парах крупная добавка не наблюдалась» и снизить `CONFIRMED`.

suggestion: [docs/tasks/240/research.md:109](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-latency/docs/tasks/240/research.md:109) — В одной колонке `final wall` у A указано время от запуска процесса, а у B–F — только от `turn/start`; сопоставимая B-величина получается лишь после добавления `connect` → вывести отдельный `total-to-final` либо явно разделить начала отсчёта.

suggestion: [docs/tasks/240/research.md:146](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-latency/docs/tasks/240/research.md:146) — Каждый E выполнялся строго после D, три дельты меняют знак, а архивный 218K-запуск не имеет синхронного fresh-контроля. Медиана `+0.792` не подтверждает причинный «small history cost» → заменить `LIKELY` на `UNCERTAIN`.

suggestion: [docs/tasks/240/research.md:152](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-latency/docs/tasks/240/research.md:152) — Значения `r=0.115` и `r=−0.369` воспроизводятся на старом корпусе с пилотными A/B, а не на 20 строках актуальной M1-таблицы. На M1 получаются примерно `0.001` и `−0.505` → назвать точный корпус либо пересчитать по authoritative rows.

question: [docs/tasks/240/research.md:102](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-latency/docs/tasks/240/research.md:102) — В пяти перечисленных raw-артефактах присутствуют 24 model turns, не 28. Где находятся доказательства ещё четырёх завершённых запусков?

suggestion: [docs/tasks/240/research.md:104](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-latency/docs/tasks/240/research.md:104) — Таблица содержит 20 строк, но `cached_tokens` отсутствует в 9, а `reasoning_tokens` — в 18. Причина reasoning раскрыта, пропуски cache только косвенно обозначены → описать полноту по каждому обязательному полю и не называть весь набор полностью заполненным.

suggestion: [docs/tasks/240/research.md:257](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-latency/docs/tasks/240/research.md:257) — D/A меняет сразу app-server wrapper, managed home, prompt и MCP, поэтому положительный результат воспроизведёт end-to-end симптом, но не докажет условие «Orchestra role causes pain» → разделить критерий воспроизведения и последующий role-on/role-off контроль.

## Verdict

**NEEDS WORK** — архитектура и исправленная A/B total-time математика выдержали проверку, но MCP-слой объявлен измеренным без доказательства, что измеряемый MCP действительно был активен.

Иначе это как посадочный список на 41 пассажира: список подробный, а взлетел ли кто-нибудь — не записали. 🙃

## Round (2026-08-23T13:43:40Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Re-review status

Ну вот, секундомер уже меряет событие, а не закрытие дверцы футляра. ⏱️ Scoped `git diff` не показал hunks, потому что все артефакты untracked; проверены текущие файлы и механически пересчитаны raw-данные.

- MCP positive control — **FIXED**: `orchestra` прошёл `starting→ready`, возвращены 41/41 инструментов, `missing=[]`.
- A/B confidence при n=2 — **FIXED**: верхняя граница больше не заявляется, confidence снижен до `LIKELY`.
- Несовпадающие origins времени — **FIXED**: M1 объясняет origins и содержит `total-to-final`.
- History causality — **FIXED**: снижено до `UNCERTAIN`, непарный archived run раскрыт.
- Корпус корреляций — **FIXED**: M1 n=20 воспроизводит `0.001106` и `−0.505022`.
- Учёт 28 turns — **FIXED**: 20 authoritative + 6 исключённых raw rows + 2 reconnect warmups.
- Пропуски token fields — **FIXED**: явно указаны 9 cache-пропусков и недоступность reasoning.
- End-to-end против role isolation — **FIXED**: эксперименты разделены.

## New findings

suggestion: [docs/tasks/240/research.md:163](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-latency/docs/tasks/240/research.md:163) — Корреляции всё ещё объединяют несопоставимый `TTFT`: у A он начинается с запуска процесса, у B–F — с `turn/start`. Для сопоставимого `total-to-TTFT` получаются `input r=0.125645` и `load1 r=−0.411802`. Направление выводов не меняется, но метрику следует пересчитать либо явно назвать mixed-origin.

## Verdict

**APPROVED** — все прежние блокеры закрыты, новых блокирующих ошибок нет. Оставшаяся находка уточняет две вспомогательные корреляции и не меняет итог исследования.

Доказательство чтения изменённого артефакта: “A one-word answer is ideal for transport isolation and poor for workflow behavior.”

Чудеса метрологии: теперь смешаны только две точки отсчёта, а не две разные гонки. 🙃
