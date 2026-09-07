#!/usr/bin/env python3
"""#523 — prove no KB fact disappeared while 40 topics became 16 and records were reworded.

Two slices, both read by this script, nothing dumped into the task directory:

- BEFORE — every ``.orchestra/kb/*.md`` at :data:`BASE_REF`, read with ``git show``.
- AFTER  — every ``.orchestra/kb/*.md`` in the working tree as it stands right now.

Every BEFORE unit (a top-level bullet with its continuation lines, or a paragraph, longer
than 40 characters) must clear one of three gates:

1. VERBATIM — the unit is present character-for-character (whitespace-normalised) in AFTER.
   This is what a pure move produces, so the merge itself is proven by this gate alone.
2. ANCHORED — the unit was reworded, and every literal anchor extracted from it is still
   present in AFTER: backticked code/paths, «quoted» owner speech, dates, ``#task`` refs,
   percentages, ratios and any number of three digits or more. Rewording may change the
   prose around an anchor; it may not change or drop the anchor itself.
   A unit qualifies for this gate only if it owns at least one SIGNATURE anchor — an anchor
   that occurs in exactly one BEFORE unit in the whole KB. Without one, the check could not
   tell "this unit survived" from "some other unit happens to mention the same things", so
   such a unit is refused here and has to go through gate 3.
3. DROPPED — the unit is listed in :data:`DROPPED` with the reason it was deliberately
   removed. This is the only way a fact leaves the KB, and it leaves a written trace.

Run (from the repo root, one command, no arguments needed):

    python3 .orchestra/tasks/523/check_no_fact_lost.py

Exit code 0 = PASS. Mutation check: delete any two records from any topic file and re-run —
the script must print two LOST lines and exit 1.
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import subprocess
import sys

# main as it stood before #523 started.
BASE_REF = "979c46315049f7fb59200cbed4d04992962e4c09"
REPO = pathlib.Path(__file__).resolve().parents[3]
KB = ".orchestra/kb"

# Units deliberately removed by #523. Key = the first 60 characters of the normalised BEFORE
# unit; value = why it left. A pointer with no assertion is not knowledge — but every entry
# here had to be opened first, and whatever it actually claimed was moved into a record.
_MERGED_H1 = (
    "H1 старого файла: тема слита, её заголовок стал `### …` внутри объединённой темы; "
    "ни одного утверждения этот заголовок не нёс сверх названия"
)
_INDEX_LINE = (
    "строка оглавления README: список тем переписан под 16 объединённых тем; сборку индекса "
    "проверяет `app.kb_index.kb_topic_index`, которая падает на строке без файла и на файле "
    "без строки, так что полнота нового списка доказана кодом, а не этой строкой"
)
DROPPED: dict[str, str] = {
    '- [current-operations](current-operations.md) — Текущие прав': _INDEX_LINE,
    '- [Правила записи](../guides/knowledge-authoring.md) — доказ': _INDEX_LINE,
    '- [prompt-delivery](prompt-delivery.md) — Промпты: сборка и ': _INDEX_LINE,
    '- [token-efficiency](token-efficiency.md) — Токены: цена и э': _INDEX_LINE,
    '- [evidence-methods](evidence-methods.md) — Измерения: доказ': _INDEX_LINE,
    '- [test-oracles](test-oracles.md) — Тесты: ложные зелёные ре': _INDEX_LINE,
    '- [test-suite-pruning](test-suite-pruning.md) — Тесты: удале': _INDEX_LINE,
    '- [dead-code-audit](dead-code-audit.md) — Мёртвый код: дости': _INDEX_LINE,
    '- [agent-code-intelligence](agent-code-intelligence.md) — На': _INDEX_LINE,
    '- [codex-runtime](codex-runtime.md) — Codex: модели, контекс': _INDEX_LINE,
    '- [repo-ops](repo-ops.md) — Git, worktree, деплой': _INDEX_LINE,
    '- [tg-media-delivery](tg-media-delivery.md) — Telegram: меди': _INDEX_LINE,
    '- [openrouter-quotas](openrouter-quotas.md) — OpenRouter: кв': _INDEX_LINE,
    '- [grep-memory-blowup](grep-memory-blowup.md) — grep: память': _INDEX_LINE,
    '- [harness-tools](harness-tools.md) — Harness: встроенные ин': _INDEX_LINE,
    '- [ox-alpha-harness-verdict](ox-alpha-harness-verdict.md) — ': _INDEX_LINE,
    '- [model-routing-selection](model-routing-selection.md) — Вы': _INDEX_LINE,
    '- [knowledge-base-architecture](knowledge-base-architecture.': _INDEX_LINE,
    '- [task-storage-architecture](task-storage-architecture.md) ': _INDEX_LINE,
    '- [information-architecture-synthesis](information-architect': _INDEX_LINE,
    '- [data-locality](data-locality.md) — KB: локальность и пере': _INDEX_LINE,
    '- [chat-freshness](chat-freshness.md) — Чат: свежесть snapsh': _INDEX_LINE,
    '- [message-provenance](message-provenance.md) — Сообщения: п': _INDEX_LINE,
    '- [agent-memory-architecture](agent-memory-architecture.md) ': _INDEX_LINE,
    '- [prime-agent](prime-agent.md) — Prime Agent и Hermes': _INDEX_LINE,
    '- [auto-work](auto-work.md) — Авторабота: триггеры и границы': _INDEX_LINE,
    '- [project-portfolio](project-portfolio.md) — Проекты: scope': _INDEX_LINE,
    '- [dashboard-quota-map](dashboard-quota-map.md) — Квоты: сбо': _INDEX_LINE,
    '- [feature-usage-audit](feature-usage-audit.md) — Функции: а': _INDEX_LINE,
    '- [competitive-landscape](competitive-landscape.md) — Harnes': _INDEX_LINE,
    '- [antigravity-runtime](antigravity-runtime.md) — Antigravit': _INDEX_LINE,
    '- [muse-spark-runtime](muse-spark-runtime.md) — Muse Spark: ': _INDEX_LINE,
    '- [review-design-defects](review-design-defects.md) — Ревью:': _INDEX_LINE,
    '- [knowledge-pipeline](knowledge-pipeline.md) — Знания: от с': _INDEX_LINE,
    '- [founder-intent](founder-intent.md) — Намерения владельца': _INDEX_LINE,
    '- [agent-guardrails](agent-guardrails.md) — Агенты: кодовые ': _INDEX_LINE,
    '- [code-simplification](code-simplification.md) — Код: упрощ': _INDEX_LINE,
    '- [tool-latency](tool-latency.md) — Время инструментов: изме': _INDEX_LINE,
    '- [model-text-control-flow](model-text-control-flow.md) — Те': _INDEX_LINE,
    '- [self-improvement-loop](self-improvement-loop.md) — Самоул': _INDEX_LINE,
    '- [review-context](review-context.md) — Ревью: калибровка от': _INDEX_LINE,
    "# chat-freshness — актуальность чата в дашборде": _MERGED_H1,
    "# codex-runtime — Codex/Sol, модели, лимиты, ревью": _MERGED_H1,
    "# competitive-landscape — чем Orchestra отличается от чужих ": _MERGED_H1,
    "# grep/ugrep в Claude Code: взрыв памяти на шаблоне контекст": _MERGED_H1,
    "# harness-tools — встроенные тула́ рантайма (app/harness/too": _MERGED_H1,
    "# Ox Alpha + свой харнес: вердикт первого рабочего дня (22.0": _MERGED_H1,
    "# test-oracles — почему зелёный прогон ничего не доказывает": _MERGED_H1,
    "# tool-latency — из чего состоит время вызовов инструментов": _MERGED_H1,
    "# evidence-methods — чем доказывают, что работа сделана и чи":
        "H1 файла, который остался темой; заголовок переписан на человеческий, "
        "утверждений не нёс",
    "# repo-ops — git, деплой, дубли, воркеры, чужая машина":
        "H1 файла, который остался темой; заголовок переписан на человеческий, "
        "утверждений не нёс",
}

# Units that own no signature anchor of their own — short prose, an Источники pointer, a Gap
# with only a task number — and were nonetheless reworded or translated. Key = first 60
# characters of the normalised BEFORE unit; value = literal strings that must be present in
# AFTER. Unlike gate 2 these anchors are hand-written, so they prove that the rendering
# stayed in the file, not that the rendering is faithful; faithfulness is a reading check
# and the pair is listed here precisely so it can be read.
REWORDED: dict[str, list[str]] = {
    "- Historical frequency of missing/misspelled class-B review ": [
        "Как часто в истории встречались отсутствующие или написанные с ошибкой формы "
        "находок ревью класса B — не измерено",
        "полный корпус артефактов не разбирал",
    ],
    "- `.orchestra/tasks/504/research.md` — full A/B/C inventory,": [
        "`.orchestra/tasks/504/research.md` — полный инвентарь A/B/C, история приёма, "
        "тесты на радиус поражения и швы замены.",
    ],
    '- The smallest truthful durable contract is per-file `event_': [
        'Минимальный честный долговечный контракт задаётся на КАЖДЫЙ файл',
    ],
    '- «The whole Telegram route was down for the interval» · pro': [
        '«Весь телеграм-маршрут лежал в этом интервале» — нет',
    ],
    '- Which exact logical file corresponds to successful message': [
        'Какому именно логическому файлу соответствуют успешные id сообщений',
    ],
    '- Exact number of the eight batch calls admitted before the ': [
        'Сколько из восьми вызовов партии было допущено до того, как вызывающий перестал ждать',
    ],
    '- `.orchestra/tasks/333/contract.md` — smallest durable per-': [
        '`.orchestra/tasks/333/contract.md` — минимальный долговечный контракт на файл',
    ],
    '- `.orchestra/tasks/421/research.md` — по-механизмная дельта': [
        '`.orchestra/tasks/421/research.md` — дельта Prime Agent ↔ Hermes ↔ Orchestra по каждому механизму',
    ],
    '- `docs/tasks/424/research.md` — lifecycle seams, exactly-on': [
        '`docs/tasks/424/research.md` — швы жизненного цикла, ограничения «ровно один раз» и хранения источника',
    ],
    '- Whether an operator-installed copy of the proxy scripts ex': [
        'Есть ли поставленная оператором копия прокси-скриптов вне проверенного чекаута — не проверено: менят',
    ],
    '- Whether an external reducer integration calls `fan_id_for_': [
        'Зовёт ли `fan_id_for_reducer` внешняя интеграция редьюсера — из репозитория и статических реестров н',
    ],
    '- The safest current progress action is HIDE frontend UI whi': [
        'Самое безопасное действие с прогрессом сегодня — СПРЯТАТЬ интерфейс, сохранив поля API, MCP и БД.**',
    ],
    '- Zero named MCP calls imply safe deletion · incomplete wrap': [
        '«Ноль именованных вызовов MCP означает, что удалять безопасно» — нет.** Телеметрия обёрток и `NULL`-',
    ],
    '- A route/UI row with no count is unused · request/click tel': [
        '«Строка маршрута или интерфейса без счётчика не используется» — нет.** Телеметрии запросов и кликов',
    ],
    '- The progress bar can be deleted together with its API imme': [
        '«Полосу прогресса можно удалить вместе с её API прямо сейчас» — нет.** Пять текущих вызовов от ворке',
    ],
    '- Exact historical MCP semantics before named `tool_name` te': [
        'Точная историческая семантика MCP до начала телеметрии с именами `tool_name` 2026-08-13 остаётся неи',
    ],
    '- HTTP route and dashboard click usage is unmeasured · add p': [
        'Использование HTTP-маршрутов и кликов дашборда не измерено · нужна безопасная для приватности перепи',
    ],
    '- Whether a human actually observes progress UI is unmeasure': [
        'Смотрит ли человек на интерфейс прогресса на самом деле — не измерено · нужен обратимый эксперимент',
    ],
    '- Whether automatic task tickets/stages outperform or safely': [
        'Обыгрывают ли автоматические тикеты и стадии задач ручной прогресс и могут ли безопасно его заменить',
    ],
    '- Proven DELETE/MERGE candidates: zero nodes and zero LOC; s': [
        'Доказанных кандидатов на удаление или слияние оказалось НОЛЬ узлов и НОЛЬ строк.** Одного статическо',
    ],
    '- Full default test execution remains unmeasured because hos': [
        'Полный прогон сьюта по умолчанию так и не измерен: сборка на хосте даёт восемь ошибок импорта `pidfd',
    ],
    '- No mutation/selection experiment was run for quota, merge,': [
        'Мутационный и отборочный эксперимент не запускался ни для квотных, ни для мержевых, ни для фронтендн',
    ],
    '- README index entry for this new topic was not added becaus': [
        'Строка в оглавление README для этой темы не добавлена: жёсткая область записи, заданная владельцем,',
    ],
    '- Exact base-revision versus current-worktree policy for a p': [
        'Не решено, откуда брать файл контекста проекта: из текущего рабочего дерева или из пришпиленной базо',
    ],
    '- Structured file schema, central-registry alternative, and ': [
        'Не выбраны ни схема структурного файла, ни альтернатива с центральным реестром, ни порог предупрежде',
    ],
    '- `.orchestra/tasks/449/research.md` — consumer trace, Git i': [
        '`.orchestra/tasks/449/research.md` — обход потребителей, проба идентичности Git, цена отсутствующего',
    ],
    '- `.orchestra/tasks/506/research.md` — empirical review size': [
        '`.orchestra/tasks/506/research.md` — эмпирическая граница размера ревью, отдача третьего раунда, иде',
    ],
    '- «Текущий quota-map timeout требует IndexedDB corruption» ·': [
        '«Текущий таймаут карты квот требует порчи IndexedDB» — нет.** Свежий контекст упал ещё до грязного с',
    ],
    '- Exact minimal queue width and ownership contract are not s': [
        'Точная минимальная ширина очереди и контракт владения не выбраны: кандидата «только очередь» оказало',
    ],
    '- Original #364 corrupt IndexedDB state is unavailable; synt': [
        'Исходного испорченного состояния IndexedDB из #364 нет: синтетический объём и рассогласование опрове',
    ],
    '- Long-run production failure probability is unknown; 12 nor': [
        'Вероятность отказа на длинной дистанции в бою неизвестна: 12 обычных действий в браузере устанавлива',
    ],
    '- A live quota router chooses Luna/Sol/Opus at spawn — the f': [
        '«Живой квотный маршрутизатор выбирает Luna/Sol/Opus при спавне» — нет.** Прежняя политика маршрутиза',
    ],
    '- Effective effort used by standalone `codex_review` was not': [
        'Фактический effort у отдельного `codex_review` из живого Codex CLI и его конфига не измерялся; в тек',
    ],
    '- VPS/Contabo observed-use counts were not collected because': [
        'Счётчики фактического использования на VPS/Contabo не собирали: безопасный read-only путь к БД в той',
    ],
    '- The model’s hidden rationale for scanning before spawning ': [
        'Почему модель решила сначала сканировать, а потом спавнить, в структурных логах не записано; наблюда',
    ],
    '- .orchestra/tasks/236/research.md — current identity/metada': [
        '.orchestra/tasks/236/research.md — текущая идентичность и метаданные, предохранитель «только бесплат',
    ],
    '- .orchestra/tasks/283/research.md — frozen protocol, produc': [
        '.orchestra/tasks/283/research.md — замороженный протокол, отображение effort на боевой путь, квитанц',
    ],
    '- .orchestra/tasks/283/research.md — Contabo run, corrected ': [
        '.orchestra/tasks/283/research.md — прогон на Contabo, исправленная оценка, метрики и сверка',
    ],
    '- `.orchestra/tasks/502/research.md` — полный merge-path inv': [
        '`.orchestra/tasks/502/research.md` — полный инвентарь пути мержа, воспроизведения 1/3/4 на скретче,',
    ],
    '- `docs/tasks/506/research.md` — current official contract, ': [
        '`docs/tasks/506/research.md` — текущий официальный контракт, матрица интеграции с GitHub, пробы на с',
    ],
    '- `docs/tasks/249/research.md` — historical live 1.1.12 stre': [
        '`docs/tasks/249/research.md` — исторические живые замеры 1.1.12: поток, инструменты, MCP, продолжени',
    ],
    '- `.orchestra/tasks/505/report.md` — open Astra/Sol long-wor': [
        '`.orchestra/tasks/505/report.md` — открытый A/B Astra против Sol на длинной работе, замороженный `qu',
    ],
    '- `.orchestra/tasks/469/research.md` — access, price, CLI/MS': [
        '`.orchestra/tasks/469/research.md` — доступ, цена, CLI и MSP, контекст, шлюз, веса и таблица фактов',
    ],
    '- `.orchestra/tasks/412/research.md` — distribution ledger, ': [
        '`.orchestra/tasks/412/research.md` — реестр распределения, рекомендация по формату, владельцы, обрат',
    ],
    '- `.orchestra/tasks/430/research.md` — exhaustive old-path i': [
        '`.orchestra/tasks/430/research.md` — исчерпывающий инвентарь старых путей, отличие путей-доказательс',
    ],
    '- OpenViking mechanisms transferable selectively are typed U': [
        'Из OpenViking выборочно переносимы семь механизмов: типизированный URI, разделение содержимого и инд',
    ],
    '- Markdown-only prompt contract as complete current-state sy': [
        '«Контракт в промпте на одном Markdown — это полноценная система текущего состояния» — нет.** #256 на',
    ],
    '- Graph-first or automatic LLM compression/dedup/supersessio': [
        '«Граф или автоматическое сжатие, дедупликация и замена фактов силами LLM могут быть каноническим авт',
    ],
    '- Stable fact-key vocabulary, legal private-field/purge poli': [
        'Открытыми остаются три вещи: словарь устойчивых ключей факта, юридическая политика приватных полей и',
    ],
    '- Candidate architecture answer utility, promotion recall an': [
        'Не измерены ни полезность ответов у предложенной архитектуры, ни полнота продвижения фактов, ни эффе',
    ],
    '- .orchestra/tasks/315/research.md — joined current-state ma': [
        '.orchestra/tasks/315/research.md — сводная матрица текущего состояния, доказательства, контраргумент',
    ],
    '- .orchestra/tasks/315/openviking-comparison.md — official m': [
        '.orchestra/tasks/315/openviking-comparison.md — таблица официальных механизмов и вердикты по перенос',
    ],
    '- .orchestra/tasks/315/schema.md — concrete URI/record schem': [
        '.orchestra/tasks/315/schema.md — конкретная схема URI и записи и правило «никакой второй истины»',
    ],
    '- .orchestra/tasks/315/state-machines.md — lifecycle, projec': [
        '.orchestra/tasks/315/state-machines.md — контракты жизненного цикла, проекции, мержа, сессии, пакета',
    ],
    '- .orchestra/tasks/256/research.md — полный local/external s': [
        '.orchestra/tasks/256/research.md — полный синтез своего и чужого опыта и рекомендованный шов записи,',
    ],
    '- `.orchestra/tasks/454/research.md` — inventory, deletion p': [
        '`.orchestra/tasks/454/research.md` — инвентарь, предикат удаления, оценка промпта Luna, экономика ве',
    ],
    '- New tools are `project_goal` and `project_wait`; task link': [
        'Новых тулов ровно два: `project_goal` и `project_wait`.** Привязка задач расширяет существующие изме',
    ],
    '- «Большой threshold исправит ложные watchdog pings» · corre': [
        '«Большой порог исправит ложные срабатывания сторожа» — нет.** Исправленный синтетический прогон на ч',
    ],
    '- Optimal stall threshold · 30m is the proposed six-check in': [
        'Оптимальный порог залипания · предложенное начальное значение — 30 минут на шесть проверок; точная и',
    ],
    '- Visual column order and whether idle owner counts as activ': [
        'Порядок колонок на экране и считается ли простаивающий владелец активной работой · решение владельца',
    ],
    '- A Phase-1 safe snapshot watermark on 2026-08-23 contained ': [
        'Безопасный снимок фазы 1 от 2026-08-23: 19 проектов, 601 задача, 2 платежа, 3 распределения, 488 стр',
    ],
    '- A later live recheck watermark on 2026-08-23 still had 19/': [
        'Одна продолжившаяся запись изменила наблюдаемый агрегат прямо во время замера: повторная живая прове',
    ],
    '- Git clones preserve repository history/recovery and git me': [
        'Клоны Git сохраняют историю и возможность восстановления, а `git merge` останавливается на конфликту',
    ],
    '- git-issue stores editable text issue directories with Git ': [
        'Как хранят задачи чужие Git-трекеры:** git-issue — редактируемые текстовые каталоги задач с push/pul',
    ],
    '- A Git-canonical task store with SQLite query projection is': [
        'Каноническое хранение задач в Git с проекцией запросов в SQLite ВОЗМОЖНО без переименования тулов за',
    ],
    '- Recommended identity is stable UUID/ULID plus preserved di': [
        'Рекомендованная личность задачи — устойчивый UUID/ULID плюс сохранённый отображаемый `#N`, выдаваемы',
    ],
    '- Projection integrity requires the changed ordinary row, it': [
        'Целостность проекции требует, чтобы изменённая обычная строка, её точечное удаление и вставка в FTS',
    ],
    '- Global sequential #N as the sole cross-contour identity · ': [
        '«Глобальный сквозной `#N` как единственная личность между контурами» — нет.** Два офлайн-контура оба',
    ],
    '- SQLite canonical plus Git export as the final portability ': [
        '«Канонический SQLite плюс экспорт в Git как окончательная архитектура переносимости» — нет.** Устаре',
    ],
    '- #405 retained immutable resources completely eliminates #3': [
        '«Сохранённые неизменяемые ресурсы из #405 полностью убирают зависящее от размера залипание из #395»',
    ],
    '- Legal policy for storing payment/client notes in private G': [
        'Не выдана юридическая политика хранения платёжных и клиентских заметок в приватном Git и требуемая п',
    ],
    '- User acceptance of lease gaps versus requirement for one c': [
        'Не выяснено, согласен ли владелец на пропуски в арендах номеров или требует одну непрерывную глобаль',
    ],
    '- Performance baseline for current task_list/task_get and 10': [
        'Базовая производительность текущих `task_list` и `task_get` и прогон на 10 000 записей не измерены ·',
    ],
    '- Exact migration from per-row global heads to an atomic pro': [
        'Открытыми на фазу 2 остаются: точная миграция от глобальных голов на строку к атомарной квитанции пр',
    ],
    '- Post-change latency and old/new snapshot behavior remain u': [
        'Задержка после правки и поведение на старом и новом снимке не измерены · повторить точную команду бе',
    ],
    '- Cold-cache latency distribution and exact live page reside': [
        'Распределение задержки на холодном кеше и точная резидентность страниц в живой системе остаются откр',
    ],
    '- .orchestra/tasks/299/research.md — current model, safe agg': [
        '.orchestra/tasks/299/research.md — текущая модель, безопасные агрегаты, сравнение с чужими решениями',
    ],
    '- .orchestra/tasks/395/research.md — hot-path call graph, ol': [
        '.orchestra/tasks/395/research.md — граф вызовов горячего пути, прогретые и холодные базовые срезы на',
    ],
    '- `.orchestra/tasks/455/protocol.md` — preregistration, pilo': [
        '`.orchestra/tasks/455/protocol.md` — предрегистрация замера: вопрос, изменение под проверкой, базово',
    ],
    '- `.orchestra/tasks/455/candidate-audit.md` — AST call graph': [
        '`.orchestra/tasks/455/candidate-audit.md` — граф вызовов по AST, вычисляемые `getattr`, корни тестов',
    ],
    '- `.orchestra/tasks/332/research.md` — full current-main dea': [
        '`.orchestra/tasks/332/research.md` — полный разбор достижимости мёртвого кода на текущем main.',
    ],
    '- `.orchestra/tasks/309/research.md` and `.orchestra/tasks/3': [
        '`.orchestra/tasks/309/research.md` и `.orchestra/tasks/309/evidence/` — срез ДО #309; текущей правдо',
    ],
    '- `.orchestra/tasks/309/research.md` — full hypotheses, find': [
        '`.orchestra/tasks/309/research.md` — гипотезы, находки, контраргументы, решения по кандидатам и буду',
    ],
    '- `.orchestra/tasks/309/metrics.md` — measurement contract, ': [
        '`.orchestra/tasks/309/metrics.md` — контракт замера (read-only `Connection.backup()`, отсечка, окна',
    ],
    '- `.orchestra/tasks/309/evidence/` — sanitized generated reg': [
        '`.orchestra/tasks/309/evidence/` — очищенные сгенерированные реестры, счётчики использования, след в',
    ],
    '- `.orchestra/tasks/313/research.md` — full current-suite pr': [
        '`.orchestra/tasks/313/research.md` — полный разбор чистки сьюта и принятые решения по каждому кандид',
    ],
    '- `.orchestra/tasks/250/research.md` — valid-alternate and i': [
        '`.orchestra/tasks/250/research.md` — откуда взялось требование годной альтернативы и независимого му',
    ],
    '- `.orchestra/kb/test-oracles.md` — vacuity, live-state, dir': [
        'Правила оракулов — пустых проверок, живого состояния, прямого шва, моков, браузера и рантайма — теперь в этой же теме, разделы выше.',
    ],
    '- `.orchestra/tasks/332/research.md` — независимый current-r': [
        '`.orchestra/tasks/332/research.md` — независимый аудит мёртвого кода на текущем репозитории и реальн',
    ],
    '- [anthropics/claude-code#59517](https://github.com/anthropi': [
        '[anthropics/claude-code#59517](https://github.com/anthropics/claude-code/issues/59517) — та же обёрт',
    ],
    '- `.orchestra/tasks/298/research.md` — тотальное first-match': [
        '`.orchestra/tasks/298/research.md` — полное дерево первого совпадения, инвентарь текущего состояния',
    ],
    '- `.orchestra/tasks/462/research.md` — post-#436 negative co': [
        '`.orchestra/tasks/462/research.md` — негативный контроль покрытия ревью на мерже после #436, ложные',
    ],
    '- `docs/tasks/430/research.md` — benchmark на 30 Orchestra e': [
        '`docs/tasks/430/research.md` — бенчмарк на 30 эпизодах Orchestra, два исключённых по доступности пил',
    ],
    '- `.orchestra/tasks/516/research.md` — отчёт фазы 1.': [
        '`.orchestra/tasks/516/research.md` — отчёт фазы 1: откуда берётся время вызова инструмента и что в н',
    ],
    'Факты и доказательства лежат в темах ниже; сырые отчёты — в ': [
        'Шестнадцать тем; факты и доказательства лежат в них, сырые отчёты — в `.orchestra/tasks/`.',
        "`rg -n -i -F --glob '*.md' '<якорь>' .orchestra/kb`",
    ],
    'Читай совпавший факт со статусом и датой, затем его источник при необхо': [
        'Читай совпавшую запись вместе с её разделом',
        'Текущий рантайм и конфиг проверяются у владельца; исторический замер за сегодня не отвечает.',
    ],
    '- [Правила записи](../guides/knowledge-authoring.md) — доказательства, ': [
        '- [Правила записи](../guides/knowledge-authoring.md) — доказательства, статусы и актуальность',
    ],
}

ANCHOR_PATTERNS = [
    r"`[^`]+`",                       # code, paths, file:line, symbols, search anchors
    r"«[^»]+»",                       # quoted owner speech — carried 1:1
    r"(?:\.orchestra|docs|app|scripts|tests|deploy|data)/[^\s,;·)\]]*[./][^\s,;·)\]]+",  # bare paths
    r"\b\d{2}\.\d{2}\.\d{4}\b",       # 06.09.2026
    r"\b\d{4}-\d{2}-\d{2}\b",         # 2026-09-06
    r"#\d+",                          # task references
    r"\d+(?:[.,]\d+)?\s*(?:%|×|п\.п\.)",
    r"\b\d{3,}\b",
]
ANCHOR_RE = re.compile("|".join(ANCHOR_PATTERNS))
# `fact:<key>` is the machine prefix #523 retires; its disappearance is the point of the
# task, not a lost fact. Every other backticked span still has to survive.
RETIRED_RE = re.compile(r"\A`fact:[^`]+`\Z")
# A «…» span containing Latin letters is never owner speech in this KB — checked over all 611
# spans of the BEFORE tree: the owner's own quotes are colloquial Russian without a single
# Latin word, while every mixed span is an agent-written formulation of a belief being
# asserted or rejected. Rendering those in Russian is exactly what #523 was asked to do, so
# such a span is exempt from the anchor gate. Every exempted span is printed at the end of
# the run so the before/after pair can be read; and the unit still has to keep at least one
# surviving signature anchor plus every path, number, date and symbol it carried.
LATIN_RE = re.compile(r"[A-Za-z]")


def translatable(anchor: str) -> bool:
    return anchor.startswith("«") and bool(LATIN_RE.search(anchor))


# Topic files #523 merged away. An anchor that is a link to one of them cannot survive — the
# file is gone — so it is exempt, but only while its replacement topic exists in AFTER.
MERGED_TOPICS = {
    "test-oracles": "code-and-tests", "test-suite-pruning": "code-and-tests",
    "dead-code-audit": "code-and-tests", "code-simplification": "code-and-tests",
    "feature-usage-audit": "code-and-tests",
    "review-design-defects": "review", "review-context": "review",
    "model-routing-selection": "models-and-quotas", "openrouter-quotas": "models-and-quotas",
    "dashboard-quota-map": "models-and-quotas",
    "ox-alpha-harness-verdict": "models-and-quotas",
    "codex-runtime": "runtimes", "antigravity-runtime": "runtimes",
    "muse-spark-runtime": "runtimes",
    "harness-tools": "agent-tools", "tool-latency": "agent-tools",
    "grep-memory-blowup": "agent-tools", "agent-code-intelligence": "agent-tools",
    "knowledge-base-architecture": "knowledge-base", "knowledge-pipeline": "knowledge-base",
    "agent-memory-architecture": "knowledge-base", "data-locality": "knowledge-base",
    "information-architecture-synthesis": "knowledge-base",
    "prompt-delivery": "agent-control", "model-text-control-flow": "agent-control",
    "agent-guardrails": "agent-control",
    "task-storage-architecture": "tasks-and-projects",
    "project-portfolio": "tasks-and-projects",
    "self-improvement-loop": "auto-work",
    "prime-agent": "external-harnesses", "competitive-landscape": "external-harnesses",
    "chat-freshness": "chat-and-telegram", "tg-media-delivery": "chat-and-telegram",
    "message-provenance": "chat-and-telegram",
}


def renamed_topic(anchor: str, after: dict[str, str]) -> bool:
    for old, new in MERGED_TOPICS.items():
        if f"{old}.md" in anchor:
            return f"{new}.md" in after
    return False


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def read_before(base_ref: str) -> dict[str, str]:
    listing = subprocess.run(
        ["git", "-C", str(REPO), "ls-tree", "--name-only", f"{base_ref}:{KB}"],
        check=True, capture_output=True, text=True,
    ).stdout.split()
    out = {}
    for name in listing:
        if name.endswith(".md"):
            out[name] = subprocess.run(
                ["git", "-C", str(REPO), "show", f"{base_ref}:{KB}/{name}"],
                check=True, capture_output=True, text=True,
            ).stdout
    return out


def read_after() -> dict[str, str]:
    kb = REPO / KB
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(kb.glob("*.md"))}


def units(text: str) -> list[str]:
    """Top-level bullets and paragraphs, continuation lines kept with their bullet."""
    out: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        starts = bool(re.match(r"^\s*[-*] ", line)) or (
            line.strip() and not line.startswith((" ", "\t")) and current and not current[-1].strip()
        )
        if starts and current:
            out.append("\n".join(current))
            current = []
        current.append(line)
    if current:
        out.append("\n".join(current))
    return [u for u in (norm(u) for u in out) if len(u) > 40]


def anchors(unit: str) -> list[str]:
    seen: list[str] = []
    for match in ANCHOR_RE.findall(unit):
        match = match.rstrip(".,;:")
        # A "code span" that swallowed a ` · ` record separator is a mis-paired backtick in the
        # source line, not a symbol anybody will ever search for.
        if " · " in match:
            continue
        if match and not RETIRED_RE.match(match) and match not in seen:
            seen.append(match)
    return seen


def stamp(text: str) -> str:
    raw = text.encode()
    return f"{len(raw):7} B  sha256:{hashlib.sha256(raw).hexdigest()[:16]}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", default=BASE_REF)
    parser.add_argument("--verbose", action="store_true", help="list every reworded unit")
    args = parser.parse_args()

    before = read_before(args.base_ref)
    after = read_after()
    after_all = norm("\n".join(after[name] for name in sorted(after)))

    before_units: list[tuple[str, str]] = []
    for name in sorted(before):
        for unit in units(before[name]):
            before_units.append((name, unit))

    owners: dict[str, int] = {}
    for _, unit in before_units:
        for anchor in anchors(unit):
            owners[anchor] = owners.get(anchor, 0) + 1

    verbatim = reworded = declared = dropped = 0
    translated: list[str] = []
    failures: list[str] = []
    for name, unit in before_units:
        if unit in after_all:
            verbatim += 1
            continue
        key = unit[:60]
        if key in DROPPED:
            dropped += 1
            continue
        if key in REWORDED:
            missing = [a for a in REWORDED[key] if norm(a) not in after_all]
            if missing:
                failures.append(f"{name}: LOST declared anchors {missing} → {unit[:120]}")
            else:
                declared += 1
            continue
        unit_anchors = anchors(unit)
        signature = [a for a in unit_anchors if owners[a] == 1]
        if not signature:
            failures.append(f"{name}: LOST (no signature anchor, not verbatim) → {unit[:150]}")
            continue
        missing = [a for a in unit_anchors if a not in after_all]
        exempt = [a for a in missing if translatable(a) or renamed_topic(a, after)]
        missing = [a for a in missing if a not in exempt]
        if missing:
            failures.append(
                f"{name}: LOST anchors {missing[:4]} → {unit[:120]}"
            )
            continue
        if exempt and not [a for a in signature if a in after_all]:
            failures.append(f"{name}: LOST (only exempt anchors survived) → {unit[:120]}")
            continue
        translated.extend(f"{name}: {a}" for a in exempt)
        reworded += 1
        if args.verbose:
            print(f"  reworded  {name}: {unit[:110]}")

    print(f"BEFORE  git show {args.base_ref[:12]}:{KB}  — {len(before)} topics")
    print(f"AFTER   working tree {KB}              — {len(after)} topics\n")
    print(f"units   verbatim={verbatim}  anchored={reworded}  declared={declared}"
          f"  dropped={dropped}  total={len(before_units)}")
    print(f"before  {stamp(''.join(before[n] for n in sorted(before)))}")
    print(f"after   {stamp(''.join(after[n] for n in sorted(after)))}\n")
    if translated:
        print(f"English claim spans rendered in Russian ({len(translated)}), listed for reading:")
        for item in translated:
            print("  " + item)
        print()

    if failures:
        for failure in failures:
            print("FAIL " + failure)
        print(f"\nFAILED: {len(failures)} unit(s) lost")
        return 1
    print("PASS — every unit of the old knowledge base is verbatim, anchored or declared dropped")
    print(
        f"ГРАНИЦА ВЫВОДА: PASS доказывает, что единица не ИСЧЕЗЛА, а не что её смысл не поехал.\n"
        f"  Для {verbatim} verbatim-единиц совпадение посимвольное — там подмена невозможна.\n"
        f"  Для {reworded} anchored держатся все числа, пути, даты и цитаты, но проза вокруг них\n"
        f"  переписана и на верность не проверяется. Для {declared} declared гарантия ещё слабее:\n"
        f"  доказано лишь присутствие объявленной формулировки, а изменение условия или\n"
        f"  квалификатора внутри неё оракул не увидит. Эти {reworded + declared} единиц\n"
        f"  проверяются чтением; пары «до/после» перечислены в REWORDED и в отчёте задачи."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
