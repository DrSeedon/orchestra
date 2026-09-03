# #237 — изолированная мини-Orchestra

## Назначение и границы

Стенд предназначен только для разрушающих проверок рестарта. Он не использует рабочий
процесс `orchestra.service`, порт `8888` или боевую БД даже на чтение.

| Ресурс | Значение |
|---|---|
| clone | `/home/kesha/orchestra-scratch/237/mini-orchestra` |
| object store | собственный `.git`, клон создан с `git clone --no-local` |
| unit | `orchestra-237.service` (transient system unit) |
| HTTP | `127.0.0.1:18888` |
| DB | `/home/kesha/orchestra-scratch/237/data/orchestra.db` |
| HOME агентов | `/home/kesha/orchestra-scratch/237/home` |
| рабочие каталоги | `/home/kesha/orchestra-scratch/237/workspace` |
| environment file | `/home/kesha/orchestra-scratch/237/stand.env` (mode 600, не в Git) |

В копии есть локальные, незакоммиченные адаптации стенда:

- `app/manager.py`: URL Orchestra для MCP берётся из `ORCHESTRA_URL`, иначе остаётся
  production-default `http://127.0.0.1:8888`;
- `app/bootstrap.py`: корень workspace берётся из `WORKSPACE_DIR`;
- `app/manager.py`: перед shutdown в journal печатаются только тип бэкенда, значения
  FD/PID и наличие process/stream (без содержимого env или кадров);
- `app/manager.py`: systemd FD names используют допустимый разделитель `.`, а inherited pair
  делает строку resumable даже при `session_id=NULL`;
- `app/backend_codex.py`: quiesce не ждёт смерти CLI, который передаётся следующему поколению;
- `app/backend_grok.py`: stand-only active-prompt/adopt adapter поверх общего JSON-RPC transport;
- `app/backend_claude.py`: stand-only private-SDK `Query` поверх inherited transport;
- `app/backend_grok.py`: только на стенде отсутствие identity-frame не считается
  несовпадением, если обязательный сервер всё равно появился по имени, стал `ready` и
  сообщил ненулевое число tools.

Без первой адаптации тестовые агенты звали бы MCP живого сервиса; без второй bootstrap
писал бы вне каталога стенда. Эти изменения нужны только до появления эквивалентной
настройки в основном коде.

Последняя адаптация Grok нужна из-за отдельного измеренного несовпадения с CLI 1.0.3:
`_x.ai/mcp/servers_updated` приходит с пустым `mcpServers`, а затем
`_x.ai/mcp/server_status` сообщает готовый `orchestra` без command/args/env identity.
Production-код fail-closed отвергает такой connect; поэтому результат рестарта Grok ниже
отвечает только на вопрос о transport/lifecycle, а не доказывает, что текущий production
connect уже совместим с 1.0.3.

## Управление

Статус (безопасно):

```bash
systemctl status orchestra-237.service --no-pager
curl -fsS -H "Authorization: Bearer $(sed -n 's/^INTERNAL_TOKEN=//p' /home/kesha/orchestra-scratch/237/stand.env)" \
  http://127.0.0.1:18888/api/sessions
```

Перезапуск измерительного стенда — только этой командой; имя `orchestra` без суффикса
`-237` здесь запрещено:

```bash
sudo systemctl restart orchestra-237.service
```

Погасить стенд после завершения следующих экспериментов:

```bash
sudo systemctl stop orchestra-237.service
```

Transient unit исчезнет после stop благодаря `--collect`. Для повторного подъёма:

```bash
sudo systemd-run --unit=orchestra-237 --collect \
  --property=Type=simple \
  --property=NotifyAccess=main \
  --property=User=kesha \
  --property=Group=kesha \
  --property=WorkingDirectory=/home/kesha/orchestra-scratch/237/mini-orchestra \
  --property=EnvironmentFile=/home/kesha/orchestra-scratch/237/stand.env \
  --property=Restart=always \
  --property=RestartSec=1 \
  --property=KillMode=process \
  --property=FileDescriptorStoreMax=64 \
  --property=FileDescriptorStorePreserve=restart \
  --property=TimeoutStopSec=30 \
  /home/kesha/orchestra/.venv/bin/python -m uvicorn app.main:app \
    --loop asyncio --host 127.0.0.1 --port 18888
```

## Предрегистрация mid-turn замера

Каждый рантайм проверяется отдельно одним настоящим агентом: Codex, Claude, Grok.

1. Агент получает абсолютный путь к двум файлам и одно действие: записать `STARTED`,
   выполнить долгую работу, и лишь в самом конце атомарно записать заранее заданную строку
   результата.
2. До рестарта проверяющий обязан увидеть `STARTED`, статус `running` и PID CLI. Это
   разрешающее плечо: без него отсутствие результата означало бы «ход не начинался».
3. После этого перезапускается только `orchestra-237.service`.
4. Успех требует одновременно:
   - MainPID супервизора изменился;
   - PID CLI агента остался жив и совпадает с новым реестром;
   - итоговый файл появился в установленный срок и побайтово равен ожидаемой строке;
   - новая Orchestra увидела production-терминал (`type=status`, content начинается с
     `turn ended`), а сессия
     вышла из `running`.
5. Отсутствие ошибок, пустая очередь и восстановленная idle-сессия не считаются успехом.

Основной timeout на один опыт — 180 секунд после рестарта. Если агент не предъявил
`STARTED` за 120 секунд, опыт помечается как `SETUP FAILED`, а не как обрыв рестартом.
Рестарт запускается через 40 секунд после `STARTED`, внутри 90-секундного участка между
маркером и финальной записью (44% участка, а не сразу после старта).

## Подтверждающие результаты

| runtime | runner | raw log | итог |
|---|---|---|---|
| Codex | frozen actual-PID run9 | `/home/kesha/orchestra-scratch/237/codex-run9.log` | PASS |
| Claude | run4 после отдельного `session_id=NULL` stand fix | `/home/kesha/orchestra-scratch/237/claude-run4.log` | PASS прототипа; не production-кандидат |
| Grok | run5 с stand-only active-prompt adapter | `/home/kesha/orchestra-scratch/237/grok-run5.log` | PASS прототипа |

Codex run7/run8 и Claude run3 навсегда exploratory: их оракулы или стендовые предусловия
исправлялись после просмотра результата. Причины и границы перечислены в `research.md`.

Стенд намеренно оставлен `active` после research. Полный `stop` освобождает systemd FD store;
следующий `start` требует повторить `systemd-run` выше.
