# Платформенные инварианты Orchestra ↔ Кеша (Волна 15, 20.11.2026)

## Железный закон независимости Кеши и Orchestra
Кеша (`/opt/kesha-bot`) и Orchestra (`/home/kesha/orchestra`) — два на 100% независимых процесса и репозитория с нулевым общим кодовым импортом (Кеша — последний оплот Out-of-Band восстановления сервера с полным `sudo`; права `sudo` у Кеши не урезать и чат Кати на отдельного Linux-юзера не выносить). Запрещено импортировать модули рабочего дерева Orchestra внутрь Кеши или сливать их рантаймы; общение Кеши с воркерами Orchestra идёт строго через внешний локальный HTTP/CLI контракт с graceful fallback.

## Межсервисный контракт
- **Orchestra API (`127.0.0.1:8888`):** все запросы от Кеши (`send_to_orchestrator`, `orch_list_sessions`, `orch_spawn_worker`, `orch_task_status`, `orch_read_logs`, `/orch status`) авторизуются `Authorization: Bearer <INTERNAL_TOKEN>`.
- **Kesha Inbox (`127.0.0.1:18081/inbox`):** принимает пуши от Orchestra строго с `Authorization: Bearer <INTERNAL_TOKEN>` (`hmac.compare_digest`). Сессии/воркеры, запущенные с `kesha_handoff` или `kesha_worker` (`kv` `kesha_notify:<session_id>`), при завершении хода отправляют компактное уведомление в `/inbox` fail-soft.
- **ACP Mux (`.acp-mux.sock`):** Кеша подключается только как клиент к существующему UNIX-сокету, никогда не запускает `python -m app.acp_mux` из рабочего дерева Orchestra; при недоступности сокета или лимите — `1 с` авто-failover в `GPT-6.2-Sol`.
- **Точка возврата:** при успешном старте lifespan Orchestra сдвигает git-тег `last-known-good` на `HEAD` для отката из карманного пульта `/orch rollback`.
