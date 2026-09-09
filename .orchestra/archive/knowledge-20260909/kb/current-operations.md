# Что действует сейчас и у кого спрашивать

Точка входа: кто владеет каким состоянием и где смотреть текущее значение. Выводы и доказательства — в темах ниже по списку.

## Established

Это указатель на владельцев, не копия значений. Проверено 05.09.2026.
Живые процессы, квоты и конфиги нужно проверять заново в нужном контуре.

- **Полномочия на рестарт, остановку и выкат определены в AGENTS.md §Границы полномочий.** Наличие кода в Git не доказывает, что процесс его загрузил · ищи: `рестарт`, `VPS`, `restart` · [AGENTS.md](../../AGENTS.md); [.orchestra/archive/instructions/2026-09-05-CLAUDE.md](../archive/instructions/2026-09-05-CLAUDE.md) §Принципы · 2026-09-05
- **Правило публикации секретов принадлежит AGENTS.md.** Локальное существование OAuth-токена и публичная утечка — разные события · ищи: `секрет`, `OAuth`, `origin` · [AGENTS.md](../../AGENTS.md); [secret_scan.py](../../scripts/secret_scan.py) · 2026-09-05
- **Владелец proxy и ограничения переключения заданы в AGENTS.md.** Текущий маршрут проверяется в нужном контуре, а не выводится из старого замера · ищи: `ai-proxy-manager`, `Contabo`, `failover` · [AGENTS.md](../../AGENTS.md); ~/.claude/docs/ai-proxy-manager.md (ранбук вне Git) · 2026-09-05
- **Текущие модели, effort и допуск определяют исполняемые владельцы, а не исторические benchmark-проценты.** Смена политики требует полномочий · ищи: `model-routing`, `effort`, `quota_gate` · [pipeline.yaml](../pipelines/default/pipeline.yaml); [quota_gate.py](../../app/quota_gate.py); [models.py](../../app/models.py) · 2026-09-05
- **Точный остаток подписочной квоты из статической базы знаний НЕ определяется.** API-цена не задаёт размер подписочного окна · ищи: `квота`, `подписка`, `API` · [runtimes.md](runtimes.md) §Rejected; [AGENTS.md](../../AGENTS.md) · 2026-09-05
- **Владелец контракта свежести чата — тема «Чат, Telegram и происхождение сообщений» и AGENTS.md.** Старый IndexedDB-кеш не подтверждает актуальность сообщения · ищи: `IndexedDB`, `stale-while-revalidate`, `snapshot` · [chat-and-telegram.md](chat-and-telegram.md); [test_frontend.py](../../tests/test_frontend.py) · 2026-09-05
- **Чтение памяти организовано file-first.** Compatibility-поиск не обязателен; включена ли семантика, проверяется у владельца текущей конфигурации · ищи: `file-first`, `RAG_ENABLED`, `search_memory` · [memory-search.md](../pipelines/default/prompts/modules/memory-search.md); [rag_service.py](../../app/rag_service.py) · 2026-09-05
- **Тип `current.db`/`vec.db` определяется схемой и владельцем, а не именем каталога `knowledge-v1`.** Исторический размер файла не разрешает его удалить · ищи: `current.db`, `FTS`, `vector`, `vec.db` · [runtime.py](../../app/ia/runtime.py); [rag.py](../../app/rag.py) · 2026-09-05

## Rejected

- **«Один LLM-конспект доказывает полноту извлечения» — нет.** В exploratory-корпусе #454 найдено 8/11, 6/11 и 6/11 проверяемых эталонов, а отозванное условие названо current в трёх прогонах. Это не метрика всей базы знаний и не основание удалять сырьё · ищи: `Luna`, `extractor`, `сырьё` · [eval-score-setlevel.json](../tasks/454/eval-score-setlevel.json); [eval-semantic-audit.json](../tasks/454/eval-semantic-audit.json) · 2026-09-03

## Gaps

- Остатки подписок, процессы и фактический деплой требуют живого наблюдения.
- Личные предпочтения без подтверждённого источника неизвестны.
- Эксперименты прежних моделей/корпусов не доказывают качество нового extractor.

## Источники

- [Правила актуализации](../guides/knowledge-authoring.md).
- [Исторический корневой документ](../archive/instructions/2026-09-05-CLAUDE.md).
