# V-585 — GigaChat в Harness

## Живая приёмка

Дата: 2026-09-22, Opus-проход после смены модели. Скрипт `live_acceptance.py` в этой папке:
отдельный процесс из worktree, без рестарта Orchestra, ключи читаются из закрытого
`/home/kesha/projects/seedon/secrets/gigachat.env` (в репозиторий не попадают),
`GIGACHAT_CA_BUNDLE=/home/kesha/.config/seedon/certs/russian_trusted_root_ca_pem.crt`,
переменные `HTTP(S)_PROXY` сняты. Журнал снимается на уровне сокетов: перехвачены
`socket.getaddrinfo` и `socket.socket.connect`, то есть видно каждое TCP-соединение процесса,
а не только запросы httpx.

Ход `HarnessBackend` (выбран `GigaChatClient`): во временной папке лежит `secret.txt` с
кодовым словом, задача — прочитать его инструментом `read`. Результат для `GigaChat-2` и
`GigaChat-2-Max` одинаков: `tool_use read: {"path": "secret.txt"}` → `tool_result` с
содержимым → `text` с правильным кодовым словом → `turn_end ok=True stop_reason=end_turn`.

Все исходящие соединения хода (одинаковы для обеих моделей):

```text
dns ngw.devices.sberbank.ru:9443       → connect 185.157.96.243:9443  (RIPE: SBRF-public-services-network-1, RU)
dns gigachat.devices.sberbank.ru:443   → connect 84.252.147.216:443   (RIPE: SBER-public-services-network-6, RU)
```

Адрес чата изменён с `api.giga.chat` (его использует seedon) на официальный
`gigachat.devices.sberbank.ru/api/v1`: `api.giga.chat` резолвится в 155.212.234.167 —
российский адрес, но сеть `RU-SERVICEPIPE` (ServicePipe LLC, DDoS-защита), а не Сбера.
Критерий «только адреса Сбера» им формально не выполнялся бы.

## Включение

1. Скопировать `.env.example` в `.env` и добавить значения из закрытого файла ключей:
   `GIGACHAT_SCOPE`, `GIGACHAT_AUTH_KEY`. Допустим также вариант
   `GIGACHAT_CLIENT_ID` + `GIGACHAT_CLIENT_SECRET`; секреты не коммитить.
2. Для окружений, где системное доверие не содержит российский корневой CA, задать
   `GIGACHAT_CA_BUNDLE=/path/to/russian_trusted_root_ca_pem.crt`.
3. Выбрать модель `GigaChat-2` (короткий alias `gigachat`) или `GigaChat-2-Max`.
   Имя `GigaChat` не поддерживается провайдером и даёт 404.

Прокси в `.env.example` — необязательная сетевая настройка. GigaChat использует прямые
адреса Сбера и не наследует `HTTPS_PROXY`; это сохраняет российский сетевой маршрут.
Токен OAuth обновляется перед истечением 30-минутного срока и однократно перевыпускается
после HTTP 401.

## Проверки

`python -m pytest tests/test_gigachat_harness.py` — 5 passed (импорт `app` из этого worktree).
Механика покрыта переводом схем в обе стороны, переводом истории и результатов инструментов,
обновлением токена после истечения и 401, а также видимой ошибкой провайдера.

Связанные наборы (models, backend_routing, model_catalog, model_gates, model_flags,
catalog_api, model_catalog_frontend, change_model_unloaded, harness_production, harness_tools,
harness_inject, audit0901_harness, backend_harness_turn_usage_422 + GigaChat): 112 passed.

Прежний отчёт называл падение `test_backend_never_uses_anthropic_credentials_for_openrouter`
«pre-existing» — это неверно: на базе `a8d2e20a` тест зелёный. Причина — `connect()` теперь
сначала берёт спецификацию модели (провайдер решает, какой клиент строить), а тест использовал
не засеянный маршрут `z-ai/glm-5.2:free` и раньше доходил до проверки ключа до поиска модели.
Тест теперь засевает маршрут фикстурой `live_harness_route`, его контракт (без
`OPENROUTER_API_KEY` не подхватывается `ANTHROPIC_API_KEY`) сохранён. Тест регистрации
GigaChat обращался к `get_model_spec("gigachat")`, а та алиасы не разрешает — исправлен на
`resolve_model`.
