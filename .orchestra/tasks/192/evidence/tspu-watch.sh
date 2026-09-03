#!/bin/bash
# #192 — непрерывный замер обрыва к orc.seedon.ru по НАСТОЯЩЕМУ каналу РФ.
#
# Зачем: решение «нужен ли CDN» нельзя принимать по одному срезу времени. 20.08.2026 утром
# 144 пробы дали 0 обрывов, а постановка задачи (написанная накануне) фиксировала ~17%.
# Либо правило ТСПУ сняли, либо оно плавает. Этот скрипт отвечает на вопрос данными.
#
# Две ловушки, которые он обходит (обе стоили нам замеров в прошлом):
#  1. VPN. На ноуте весь трафик уходит в tun0 — мимо ТСПУ. Признак подделки: conn≈0.0003 с
#     до Москвы. Поэтому пробы прибиты к физическому интерфейсу и прокси снят.
#  2. Проверка через прокладку. Код 200 и латентность подделывает любой релей, поэтому
#     ассерт стоит на БАЙТЕ бэкенда — favicon.svg в 2851-байтной странице логина Orchestra.
#
# Запуск (раз в 10 мин через cron, лог растёт медленно):
#   */10 * * * * /path/to/tspu-watch.sh >> /var/log/tspu-watch.log 2>&1
# Разбор:
#   awk '{print $3}' /var/log/tspu-watch.log | sort | uniq -c

set -u
IFACE="${IFACE:-wlp4s0}"
HOST="${HOST:-orc.seedon.ru}"
BIG="${BIG:-/static/js/app.js}"   # тяжёлый ответ: ловит обрыв тела, а не только хендшейка

# Прокси снять обязательно — иначе меряется 127.0.0.1, а не канал.
unset HTTPS_PROXY HTTP_PROXY https_proxy http_proxy ALL_PROXY all_proxy

TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
BODY=$(mktemp); trap 'rm -f "$BODY"' EXIT

# --- проба 1: страница логина, ассерт на байт бэкенда ---
M=$(curl -sS --interface "$IFACE" -L --max-time 12 -o "$BODY" \
    -w '%{http_code} %{time_connect} %{time_appconnect} %{time_total} %{size_download}' \
    "https://$HOST/" 2>/dev/null)
RC=$?
if [ $RC -ne 0 ]; then
    echo "$TS login FAIL rc=$RC (обрыв: хендшейк или таймаут)"
elif grep -qa 'favicon.svg' "$BODY"; then
    echo "$TS login OK $M"
else
    # 200 без байта бэкенда = ответила прокладка, а не Orchestra
    echo "$TS login IMPOSTOR $M (нет favicon.svg — отвечал не бэкенд)"
fi

# --- проба 2: тяжёлый ответ, ловит обрезание тела (механизм «16384 Б» и «доносит 19–23 КБ») ---
SZ=$(curl -sS --interface "$IFACE" --max-time 25 -o /dev/null -w '%{size_download}' \
     "https://$HOST$BIG" 2>/dev/null)
RC=$?
if [ $RC -ne 0 ]; then
    echo "$TS big FAIL rc=$RC"
elif [ "${SZ:-0}" -lt 400000 ]; then
    echo "$TS big TRUNCATED size=$SZ (тело обрезано — это и есть искомый обрыв)"
else
    echo "$TS big OK size=$SZ"
fi
