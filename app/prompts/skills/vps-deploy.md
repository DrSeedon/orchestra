---
name: vps-deploy
description: Обновление и рестарт Orchestra на VPS (git pull + systemctl restart)
---

# VPS Deploy

Обновление Orchestra на продакшн VPS.

## Когда использовать
- Юзер просит обновить VPS / продакшн / деплой
- Юзер говорит "обнови сервер", "задеплой", "pull на VPS", "рестартни на VPS"
- После мержа важных фиксов которые нужны на проде

## Процедура

### 1. Проверь что main чистый
```bash
git status
git log --oneline -3
```
Убедись что нужные коммиты в main и запушены на GitHub.

### 2. Обнови код на VPS
```bash
ssh -o StrictHostKeyChecking=no root@orchestra.zahoron.ru "cd /opt/orchestra && git pull origin main"
```

### 3. Рестартни сервис
```bash
ssh -o StrictHostKeyChecking=no root@orchestra.zahoron.ru "systemctl restart orchestra"
```
`uv sync` запускается автоматически через `ExecStartPre` — зависимости ставятся сами.

### 4. Проверь что поднялся
```bash
ssh -o StrictHostKeyChecking=no root@orchestra.zahoron.ru "sleep 3 && systemctl status orchestra --no-pager | head -8"
curl -s --max-time 10 -o /dev/null -w '%{http_code}' https://orchestra.zahoron.ru
```
Ожидаемо: `active (running)` + HTTP 302 (redirect to login).

### 5. Если упал — диагностика
```bash
ssh -o StrictHostKeyChecking=no root@orchestra.zahoron.ru "journalctl -u orchestra -n 30 --no-pager"
```

## Правила
- **НЕ деплоить** пока воркер активно работает над фиксом — жди DONE
- **НЕ деплоить** непроверенный код — сначала тесты локально
- **Всегда проверять** что сервис поднялся после рестарта
- При ошибке `ModuleNotFoundError` — `uv sync` должен решить (он в ExecStartPre). Если нет — `ssh root@orchestra.zahoron.ru "cd /opt/orchestra && uv sync"`

## VPS параметры
- Host: `root@orchestra.zahoron.ru`
- Path: `/opt/orchestra`
- Service: `orchestra.service`
- URL: `https://orchestra.zahoron.ru`
- User: `orchestra` (systemd)
