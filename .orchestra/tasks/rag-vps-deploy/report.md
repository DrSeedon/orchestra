# RAG deployment — Contabo VPS

Дата: 2026-07-17. VPS: `158.220.127.161`, Orchestra: `/home/kesha/orchestra`.

- Установлены optional dependencies: `uv sync --extra rag`.
- Модель `AlpEge/bge-m3-onnx-int8` скачана напрямую с Hugging Face в `data/models/` и проверена embedding размерности 1024.
- В `.env` включены `RAG_ENABLED=true`, offline cache path и `HF_HUB_OFFLINE=1`.
- Добавлен systemd drop-in `orchestra.service.d/environment.conf` с `EnvironmentFile=/home/kesha/orchestra/.env`. Это необходимо, потому что `app.routes.memory` импортирует `rag_service` до вызова `load_dotenv()` в lifespan.
- Reindex завершён: 236 файлов, 4047 файловых чанков. Для scope `/home/kesha/orchestra` подходящих логов нет (`logs=0`).
- Контрольный semantic search вернул HTTP 200 и релевантный фрагмент `CLAUDE.md`; `orchestra.service` активен.

На VPS до задачи уже были изменения `uv.lock` и `docs/team-structure.html`; они сохранены и не коммитились.
