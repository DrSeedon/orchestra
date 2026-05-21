# Telegram Local Bot API Server Setup

Позволяет скачивать файлы до 2GB вместо лимита 20MB публичного TG API.

## 1. Установить зависимости сборки

```bash
sudo apt install -y make git g++ cmake libssl-dev zlib1g-dev gperf
```

## 2. Сборка из исходников

```bash
cd /opt
sudo git clone --recursive https://github.com/tdlib/telegram-bot-api.git
cd telegram-bot-api
sudo mkdir build && cd build
sudo cmake -DCMAKE_BUILD_TYPE=Release ..
sudo cmake --build . --target install -j$(nproc)
```

Бинарь установится в `/usr/local/bin/telegram-bot-api`.

## 3. Получить API credentials

- Идти на https://my.telegram.org → API Development Tools
- Создать приложение, получить `api_id` (число) и `api_hash` (hex строка)

## 4. Создать директорию для данных

```bash
mkdir -p /mnt/data/Projects/Python/orchestra/data/tg-bot-api
```

## 5. Создать systemd service

Создать файл `/etc/systemd/system/telegram-bot-api.service`:

```ini
[Unit]
Description=Telegram Bot API Server
After=network.target

[Service]
ExecStart=/usr/local/bin/telegram-bot-api \
    --api-id=API_ID \
    --api-hash=API_HASH \
    --local \
    --http-port=8081 \
    --dir=/mnt/data/Projects/Python/orchestra/data/tg-bot-api/
Restart=always
User=maxim

[Install]
WantedBy=multi-user.target
```

Заменить `API_ID` и `API_HASH` реальными значениями.

## 6. Запустить сервис

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now telegram-bot-api
sudo systemctl status telegram-bot-api
```

## 7. Проверить

```bash
curl http://localhost:8081/botTOKEN/getMe
```

## 8. Настроить Orchestra

В `.env` проекта добавить:

```env
TG_LOCAL_API_URL=http://localhost:8081
```

Orchestra автоматически переключится на локальный сервер при наличии этой переменной.

## Порт

8081 зарезервирован в `~/ports.md` как `telegram-bot-api`.
