# Текущие решения и владельцы состояния

## Established

Это указатель на владельцев, не копия значений. Проверено 05.09.2026.
Живые процессы, квоты и конфиги нужно проверять заново в нужном контуре.

- `fact:restart-owner` — Полномочия на рестарт, остановку и выкат определены в AGENTS.md §Границы полномочий; наличие кода в Git не доказывает его загрузку процессом · search: `рестарт`, `VPS`, `restart` · evidence: [AGENTS.md](../../AGENTS.md); [.orchestra/archive/instructions/2026-09-05-CLAUDE.md](../archive/instructions/2026-09-05-CLAUDE.md) §Принципы · 2026-09-05
- `fact:secret-owner` — Правило публикации секретов принадлежит AGENTS.md; локальное существование OAuth-токена и публичная утечка различаются · search: `секрет`, `OAuth`, `origin` · evidence: [AGENTS.md](../../AGENTS.md); [secret_scan.py](../../scripts/secret_scan.py) · 2026-09-05
- `fact:proxy-owner` — Владелец proxy и ограничения переключения заданы в AGENTS.md; текущий маршрут проверяется в нужном контуре, не выводится из старого замера · search: `ai-proxy-manager`, `Contabo`, `failover` · evidence: [AGENTS.md](../../AGENTS.md); ~/.claude/docs/ai-proxy-manager.md (ранбук вне Git) · 2026-09-05
- `fact:routing-owner` — Текущие модели, effort и допуск определяют исполняемые владельцы, а не исторические benchmark-проценты; смена политики требует полномочий · search: `model-routing`, `effort`, `quota_gate` · evidence: [pipeline.yaml](../pipelines/default/pipeline.yaml); [quota_gate.py](../../app/quota_gate.py); [models.py](../../app/models.py) · 2026-09-05
- `fact:quota-observation` — Точный остаток подписочной квоты сейчас неизвестен из статической KB; API-цена не определяет размер подписочного окна · search: `квота`, `подписка`, `API` · evidence: [codex-runtime.md](codex-runtime.md) §Rejected; [AGENTS.md](../../AGENTS.md) · 2026-09-05
- `fact:chat-owner` — Владелец контракта свежести чата — chat-freshness и AGENTS.md; старый IndexedDB-кеш не подтверждает актуальность сообщения · search: `IndexedDB`, `stale-while-revalidate`, `snapshot` · evidence: [chat-freshness.md](chat-freshness.md); [test_frontend.py](../../tests/test_frontend.py) · 2026-09-05
- `fact:knowledge-owner` — Организация чтения памяти file-first; compatibility-поиск не обязателен, включение семантики проверяется у владельца текущей конфигурации · search: `file-first`, `RAG_ENABLED`, `search_memory` · evidence: [memory-search.md](../pipelines/default/prompts/modules/memory-search.md); [rag_service.py](../../app/rag_service.py) · 2026-09-05
- `fact:storage-identity` — Тип current.db/vec.db определяется схемой и владельцем, не именем каталога knowledge-v1; исторический размер не разрешает удаление · search: `current.db`, `FTS`, `vector`, `vec.db` · evidence: [runtime.py](../../app/ia/runtime.py); [rag.py](../../app/rag.py) · 2026-09-05

## Rejected

- `fact:extraction-not-lossless` — Один LLM-конспект не доказывает полноту извлечения: в exploratory-корпусе #454 найдено 8/11, 6/11 и 6/11 проверяемых эталонов, отозванное условие названо current в трёх прогонах; это не метрика всей KB и не основание удалять сырьё · search: `Luna`, `extractor`, `сырьё` · evidence: [eval-score-setlevel.json](../tasks/454/eval-score-setlevel.json); [eval-semantic-audit.json](../tasks/454/eval-semantic-audit.json) · 2026-09-03

## Gaps

- Остатки подписок, процессы и фактический деплой требуют живого наблюдения.
- Личные предпочтения без подтверждённого источника неизвестны.
- Эксперименты прежних моделей/корпусов не доказывают качество нового extractor.

## Источники

- [Правила актуализации](../guides/knowledge-authoring.md).
- [Исторический корневой документ](../archive/instructions/2026-09-05-CLAUDE.md).
