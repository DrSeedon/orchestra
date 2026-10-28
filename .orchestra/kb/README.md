# Исследования и опыт: оглавление KB

Порядок чтения и записи для всех ролей: [knowledge](../pipelines/default/prompts/modules/knowledge.md).

- [evidence-methods](evidence-methods.md) — MemoryHigh/reclaim, GIL-профиль, ложная CSS-абляция, плавающий baseline, бенчмарки: bwrap/AppArmor/userns и учёт при лимите
- [models-and-quotas](models-and-quotas.md) — КАК СЧИТАТЬ расход модели (cost_usd, кредиты, запрет делить общий котёл), cache_read/input/reasoning, Claude Max V-541, reset/ценность пула V-542, ошибки фаз, цена хода Astra/Sol/Luna и квантование quota_primary_pct; формула подписки: запись кеша 0.6 п.п./М, чтение ≈0 (V-660, внешний bulk-probe V-664); Sonnet 5.5 против Opus 5.5 и effort low…max (V-656/V-661)
- [runtimes](runtimes.md) — Grok 1.0.3 doctor/trust/MCP, MultiCode hub: проект с нашей папкой, steer/interrupt/runId, форма t3_thread_read (V-1008), контроль Codex 0.153.4, bwrap RC=0, ARTEMIS/Android отклонён за отсутствием предмета; V-831: input_json_delta, пустой thinking, файл вывода local_bash
- [chat-and-telegram](chat-and-telegram.md) — page.route и кеш, scroll anchoring, конечный SSE, coalescing без dropped
- [knowledge-base](knowledge-base.md) — Luna #454: 8/11 и 6/11, отменённое правило как current, пределы оценки; V-1114: «сон» памяти — сжатие без архива теряет факты, консолидация со ссылками не хуже, −7 % записи кеша
- [tasks-and-projects](tasks-and-projects.md) — 33 коллизии UUID независимых узлов, расходящийся acceptance-контракт, эксперимент с карточками предложенных задач и удалённой сводкой дочерних работ INFO
- [agent-control](agent-control.md) — Инструкция не доставлена: ошибка до создания сессии #430; V-570: глобальный AGENTS вне managed Codex; V-572: две личные копии скилла; проверка «читает ли агент файл правил» ломается о включённые инструменты
- [history](history.md) — Закреплённый Git-снимок исходных исследований и старых материалов
- [prompt-engineering](prompt-engineering.md) — #77: соблюдение ≠ сохранность; #147: фильтр и триггер; #148/#149: подписка и доставка; #125: пропущенная ветка; V-548/V-550: свобода метода; V-565/V-566: рекомендация для Astra помогла Luna; V-666: «сравни подходы/думай глубже» жгут токены без выигрыша; V-895: переписывание задания «deeper» (Ризеберг) ×2,07 токенов без прироста принятого
