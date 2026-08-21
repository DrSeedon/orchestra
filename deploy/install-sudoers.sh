#!/bin/bash
# Ставит точечные права агенту на СВОИ сервисы.
# Битый файл в sudoers.d ломает sudo целиком -> visudo -c ДО установки.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)/orchestra-agent-sudoers"
DST=/etc/sudoers.d/orchestra-agent
install -m 0440 -o root -g root "$SRC" /tmp/.sudoers-check
if ! visudo -c -f /tmp/.sudoers-check; then echo "СИНТАКСИС БИТЫЙ — ничего не установлено"; rm -f /tmp/.sudoers-check; exit 1; fi
rm -f /tmp/.sudoers-check
install -m 0440 -o root -g root "$SRC" "$DST"
if ! visudo -c >/dev/null; then echo "КОНФИГУРАЦИЯ БИТАЯ -> удаляю"; rm -f "$DST"; visudo -c; exit 1; fi
echo "установлен: $DST"
echo "=== ПРОВЕРКА (чего не хватало) ==="
sudo -u maxim sudo -n systemctl status orchestra.socket >/dev/null 2>&1 && echo "  OK orchestra.socket" || echo "  FAIL orchestra.socket"
sudo -u maxim sudo -n journalctl -u orchestra -n 1 >/dev/null 2>&1 && echo "  OK journalctl" || echo "  FAIL journalctl"
sudo -u maxim sudo -n systemctl status telegram-bot-api >/dev/null 2>&1 && echo "  OK telegram-bot-api" || echo "  FAIL telegram-bot-api"
echo "=== КОНТРОЛЬ: лишнего не дали ==="
sudo -u maxim sudo -n whoami >/dev/null 2>&1 && echo "  ВНИМАНИЕ: whoami прошёл — права шире задуманного" || echo "  OK: посторонние команды требуют пароль"
