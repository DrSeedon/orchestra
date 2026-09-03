# #388 — #256/#299 против OpenViking

Дата: 24.08.2026. Только исследование и read-only перепроверка. Реализация не разрешена.

## Вердикт

Архитектура из #256 должна **заменить OpenViking как ближайший implementation priority**.
OpenViking решает retrieval/context management в общем виде, а #256 локализует более ранний и
уже измеренный дефект Orchestra: находка не получает стабильную identity, current/rejected
семантику, canonical topic, merge generation и гарантированную доставку в search.

Ставить OpenViking поверх неуправляемого write/promotion seam означает лучше искать неполный и
противоречивый corpus. Сначала нужны canonical facts и freshness contract; после этого отдельные
идеи OpenViking можно добавить без зависимости от его сервера.

## Что подтвердилось при чтении первичных материалов

Основной вывод #256 корректен:

- Git/Markdown остаётся каноном доказательства и review surface.
- SQLite current/FTS — синхронная перестраиваемая проекция, привязанная к Git HEAD.
- Vector/log RAG — асинхронная cold-history проекция, не oracle текущей истины.
- stable fact_key, status, valid/observed/recorded time и provenance определяют обновление.
- semantic similarity может предложить topic/fact candidate, но не имеет права retire/supersede.
- merge устанавливает target_head; projection_head обязан его догнать или явно показать долг и
  прочитать изменённый canonical topic напрямую.

Это не «самописный OpenViking». Это control plane правды для Git-native проекта. OpenViking
оптимизирует context retrieval и memory extraction, но не делает Git commit и review
канонической границей и не даёт Orchestra-specific task/merge receipt.

## Свежая перепроверка VPS

Повторно выполнен неизменённый structural audit #256:

    python3 docs/tasks/256/eval/audit_structure.py \
      --worktree "$PWD" \
      --scope-root /home/kesha/orchestra \
      --vec-db /home/kesha/orchestra/data/vec.db \
      --output /tmp/structure-256-vps-current.json

Текущие значения отличаются от ноутбучного снимка #256:

| Метрика | #256, ноутбук 23.08 | VPS 24.08 | Вывод |
|---|---:|---:|---|
| indexable Markdown | 1 092 | 1 172 | Corpus вырос после Git sync |
| current indexed | 547 | 1 061 | Async index существенно догнал |
| current coverage | 50.1% | 90.5% | Старые 50.1% нельзя называть текущими |
| freshness debt | 545 | 111 | 95 missing + 16 stale; seam всё ещё не закрыт |
| source-link coverage | 7/12 = 58.3% | 15/29 = 51.7% | Promotion discipline не улучшилась |
| unlisted topic | 1/12 | 1/14 | dashboard-quota-map.md всё ещё вне registry |
| prompt footprint | 7 872 B | 8 328 B | Registry/procedure уже растут |

Абсолютный индексный долг оказался частично состоянием конкретного снимка, но причинный вывод
выдержал проверку: индекс может догнать, а promotion/fact identity/current semantics сами от этого
не появляются. search_memory в двух текущих исследованиях также упёрся в собственный 5-секундный
timeout; прямой API-запрос прошёл примерно за 4.8 с. Это дополнительный latency signal, не
доказательство качества ответа.

## Обнаруженный реальный collision двух контуров

После Git sync текущий репозиторий содержит:

- docs/tasks/256 — исследование knowledge architecture;
- live SQLite task #256 — «Ревьюер и исполнитель — одна модель…»;
- docs/tasks/299 — исследование Git-backed task storage;
- live SQLite task #299 — «spawn_worker принимает alias sol».

То есть один и тот же project-scoped #N уже обозначает разные сущности в Git и SQLite.
Архитектура #299 предсказывала именно этот класс отказа: два контура сохраняют человеческий #N,
но без stable UUID/ULID и alias mapping не имеют общей identity.

Это сильнее теоретического довода и меняет порядок работ. До внедрения facts нельзя продолжать
использовать docs/tasks/N как безусловный foreign key к локальной tm task N.

Исторические каталоги сейчас не переименовывать: это сломает ссылки и evidence paths. Сначала
нужен collision manifest и stable identity/aliases; затем миграция может сохранить старые пути
как aliases или redirects.

## Что оставить от OpenViking

Из OpenViking полезны три идеи, но только после typed-fact seam:

1. progressive loading: L0 abstract / L1 overview / L2 evidence;
2. observable retrieval trajectory;
3. server-side token budget и tier degradation.

#256 уже предлагает близкий hot/warm/cold контракт:

- hot: однострочный topic registry;
- warm: typed fact summary с status/time/source;
- cold: полный topic/task/log evidence.

Поэтому L0/L1/L2 можно реализовать как нашу проекцию. Auto session-memory extraction и
LLM dedup/supersession не переносить: они конфликтуют с zero-false-supersession требованием.

## Рекомендуемый порядок реализации

### A. Identity boundary — раньше knowledge schema

Не делать весь широкий #299 с payments и YouGile. Вынести минимальный общий фундамент:

1. stable task ID плюс сохранённый display #N;
2. contour/source и alias mapping;
3. collision audit Git paths против current task projection;
4. canonical_head/projection_head/rebuild receipt;
5. fail-closed mismatch вместо молчаливой привязки docs/tasks/N к другой задаче.

Payments, clients и YouGile остаются вне первого этапа. Текущий origin публичный, поэтому
чувствительные notes вообще нельзя переносить в этот Git.

### B. Typed knowledge write path

1. deterministic topic registry;
2. strict fact record: fact_id, fact_key, status, valid/observed/recorded time, evidence;
3. kb_promote API: agent proposes, server validates;
4. same-key overlapping value требует explicit supersedes или disputed;
5. rejected/historical остаются доступными, refresh_after только создаёт validation debt.

### C. Merge/projection/read path

1. Git merge establishes target_head;
2. changed typed records synchronously fold into SQLite current + FTS;
3. merge receipt checks exact fact_id at projection_head;
4. vector/log indexing stays async;
5. head mismatch triggers visible debt + direct canonical fallback.

### D. После correctness — progressive context

Добавить L0/L1 summaries, retrieval trace и token budget по полезным идеям OpenViking. Отдельно
измерить task success; не смешивать это с write-path rollout.

## Ответы на decision board #295

1. **Схема факта — строгая.** Обязательны fact_key, status, valid/observed/recorded time,
   provenance и generation. Расширения versioned; free-form только внутри claim/evidence.
2. **Promote может запросить агент, принять — только write API.** Same-key update не решается
   similarity. При конфликте источников — disputed или явное человеческое подтверждение.
3. **Связь с #299 — сначала общий identity/head contract, не вся миграция task/payments.**
   Реальный #256/#299 collision делает это блокирующей предпосылкой.
4. **Private data — не в текущий Git.** Current origin публичный. Нужен отдельный private store/repo
   с классификацией; tombstone никогда не называется erase.
5. **Rollout gates — рекомендуемый строгий набор плюс collision gate.** 12 promotion scenarios,
   18 retrieval cases, zero false supersession, exact generation receipts, clean-clone rebuild,
   two-contour ID collision/rebase cases и forced projection debt with canonical fallback.

## Что не доказано

- Candidate architecture не реализована.
- Improvement answer utility/task success не измерен.
- stable fact_key vocabulary и сериализация не выбраны.
- SQLite projector latency на merge не измерена.
- L0/L1 generation quality и cost не измерены.

Следующий шаг при одобрении — Phase 2 plan с отдельными vertical tickets A/B/C. Не запускать
OpenViking shadow-eval раньше identity/promotion/freshness seam: он отвечает на более поздний вопрос.

## Источники

- docs/tasks/256/research.md — основной synthesis и target seam.
- docs/tasks/256/comparison.md — сравнение Git, SQLite, graph, typed statements и event log.
- docs/tasks/256/metrics.md — frozen holdout, baseline и rollout gates.
- docs/kb/knowledge-base-architecture.md — durable conclusions.
- docs/tasks/299/research.md — task identity и Git/SQLite projection.
- docs/kb/task-storage-architecture.md — durable task-store conclusions.
- docs/tasks/387/research.md — проверка OpenViking и других внешних проектов.
- /tmp/structure-256-vps-current.json — текущая read-only перепроверка; temp evidence, числа
  перенесены в этот canonical report.

## Confidence

- Архитектурный порядок identity → typed facts → projection → progressive retrieval: **high**.
- Текущий collision #256/#299 и VPS structural metrics: **confirmed**.
- Отказ от OpenViking как ближайшего priority: **high**, потому что он оптимизирует более поздний seam.
- Будущий task-success effect собственной архитектуры: **uncertain до implementation/eval**.
