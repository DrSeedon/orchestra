# #224 T6 — вынести API ID и hash из ExecStart в окружение

**Ничего из этого агентом НЕ выполнено.** Установка, `daemon-reload` и рестарт — окно владельца.
Команды выписаны дословно: копировать целиком, по одному шагу.

## Зачем

Сейчас юнит `-rw-r--r-- root root` (world-readable) и держит значения прямо в `ExecStart`,
поэтому они видны И в файле, И в `/proc/<pid>/cmdline` любого процесса на хосте. Через `ps`
они уже попали в лог-хранилище: 14 строк с `--api-hash=` в 4 сессиях.

Бинарник умеет брать их из окружения сам:

```
$ telegram-bot-api --help
  --api-id=<arg>    ... (defaults to the value of the TELEGRAM_API_ID environment variable)
  --api-hash=<arg>  ... (defaults to the value of the TELEGRAM_API_HASH environment variable)
```

Поэтому флаги убираются ЦЕЛИКОМ. **Вариант `--api-id=${TELEGRAM_API_ID}` не годится** —
systemd развернёт подстановку, и значение снова окажется в argv.

## Шаги

**1. Забрать текущие значения из работающего юнита** (не из истории, не из чата):

```bash
sudo grep -o -- '--api-id=[0-9]*'      /etc/systemd/system/telegram-bot-api.service
sudo grep -o -- '--api-hash=[0-9a-f]*' /etc/systemd/system/telegram-bot-api.service
```

**2. Создать файл окружения 600 ДО правки юнита** (иначе рестарт поднимет сервис без кредов):

```bash
sudo install -m 600 -o root -g root /dev/null /etc/telegram-bot-api.env
sudo tee /etc/telegram-bot-api.env >/dev/null <<'EOF'
TELEGRAM_API_ID=<значение из шага 1>
TELEGRAM_API_HASH=<значение из шага 1>
EOF
sudo chmod 600 /etc/telegram-bot-api.env
```

**3. Сверить подготовленный юнит с текущим** — глазами, прежде чем перезаписывать:

```bash
diff <(sed -E 's/--api-(id|hash)=[^ ]*/--api-\1=<MASKED>/g' /etc/systemd/system/telegram-bot-api.service) \
     docs/tasks/224/telegram-bot-api/telegram-bot-api.service
```
Ожидаются ровно два отличия: пропали оба флага, добавился `EnvironmentFile=`.

**4. Установить и перезапустить:**

```bash
sudo cp /etc/systemd/system/telegram-bot-api.service /root/telegram-bot-api.service.bak
sudo cp docs/tasks/224/telegram-bot-api/telegram-bot-api.service \
        /etc/systemd/system/telegram-bot-api.service
sudo systemctl daemon-reload
sudo systemctl restart telegram-bot-api
```

## Проверка ПОСЛЕ установки — обязательная

Тест в репозитории проверяет только подготовленный ТЕКСТ. Что значения ушли из argv живого
процесса, доказывает эта команда, и выполнить её надо здесь же:

```bash
ps -o args= -C telegram-bot-api | grep -c -- '--api-'   # ожидается: 0
systemctl is-active telegram-bot-api                    # ожидается: active
```

`0` при `active` = получилось. Ненулевой счётчик = флаги вернулись; `inactive`/`failed` =
сервис не нашёл креды, смотреть `journalctl -u telegram-bot-api -n 50` и `EnvironmentFile`.

## Откат

```bash
sudo cp /root/telegram-bot-api.service.bak /etc/systemd/system/telegram-bot-api.service
sudo systemctl daemon-reload && sudo systemctl restart telegram-bot-api
```

## Что это НЕ чинит

Значения, уже записанные в `data/orchestra.db` (14 строк). Их санитизация — отдельное
решение владельца; правило «логи агентов не удалять» здесь не нарушается.
Ротация ID/hash — тоже решение владельца, и делать её осмысленно ПОСЛЕ этого шага.
