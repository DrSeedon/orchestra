#!/bin/bash
# Проверяет все прокси Orchestra и переключает Orchestra+Codex+TG на первый рабочий.
# Запускай при смене сети (сменил WiFi / выключил VPN): bash scripts/check-proxies.sh
#
# WHY: все прокси = ssh -L туннели к VPS, маршрут к которым иногда идёт через tun0 (Reality VPN).
# При смене сети часть туннелей дохнет. Скрипт находит живой и переключает на него всё.

set -uo pipefail
ENV_FILE="/mnt/data/Projects/Python/orchestra/.env"
CODEX_WRAPPER="/home/maxim/.local/bin/codex"
PROXYCHAINS="/etc/proxychains4.conf"

# Прокси-кандидаты: name:port (порядок = приоритет)
CANDIDATES=(
    "Contabo-DE:12343"
    "Hiddify:12334"
    "Fornex-NL:12342"
    "Timeweb-NL:12341"
    "Ezhik:12340"
)

TEST_URL="https://api.anthropic.com"
echo "🔍 Проверяю прокси (цель: $TEST_URL)..."
echo ""

WORKING_PORT=""
WORKING_NAME=""
for entry in "${CANDIDATES[@]}"; do
    name="${entry%%:*}"
    port="${entry##*:}"
    # порт слушает?
    if ! ss -tlnH "sport = :$port" 2>/dev/null | grep -q ":$port"; then
        printf "  ❌ %-12s (:%s) — порт не слушает\n" "$name" "$port"
        continue
    fi
    # реально ходит наружу?
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 8 -x "http://127.0.0.1:$port" "$TEST_URL" 2>/dev/null)
    if [[ "$code" =~ ^(200|401|403|404)$ ]]; then
        printf "  ✅ %-12s (:%s) — работает (HTTP %s)\n" "$name" "$port" "$code"
        [[ -z "$WORKING_PORT" ]] && { WORKING_PORT="$port"; WORKING_NAME="$name"; }
    else
        printf "  ❌ %-12s (:%s) — нет ответа (code=%s)\n" "$name" "$port" "${code:-timeout}"
    fi
done

echo ""
if [[ -z "$WORKING_PORT" ]]; then
    echo "🚨 НИ ОДИН прокси не работает. Включи VPN/Reality или подними туннель."
    echo "   (Anthropic API заблокирован в РФ без выхода наружу)"
    exit 1
fi

echo "🎯 Рабочий прокси: $WORKING_NAME (:$WORKING_PORT)"

# Текущий прокси в .env
CURRENT=$(grep -oP 'HTTPS_PROXY=http://127.0.0.1:\K[0-9]+' "$ENV_FILE" | head -1)
if [[ "$CURRENT" == "$WORKING_PORT" ]]; then
    echo "✅ Orchestra уже на :$WORKING_PORT — ничего менять не нужно"
else
    echo "🔧 Переключаю Orchestra :$CURRENT → :$WORKING_PORT"
    sed -i "s|HTTPS_PROXY=http://127.0.0.1:[0-9]*|HTTPS_PROXY=http://127.0.0.1:$WORKING_PORT|" "$ENV_FILE"
    sed -i "s|HTTP_PROXY=http://127.0.0.1:[0-9]*|HTTP_PROXY=http://127.0.0.1:$WORKING_PORT|" "$ENV_FILE"
    echo "   → нужен рестарт: sudo systemctl restart orchestra"
    NEED_ORCH_RESTART=1
fi

# Codex wrapper
CODEX_CURRENT=$(grep -oP 'HTTPS_PROXY=http://127.0.0.1:\K[0-9]+' "$CODEX_WRAPPER" | head -1)
if [[ "$CODEX_CURRENT" != "$WORKING_PORT" ]]; then
    echo "🔧 Переключаю Codex :$CODEX_CURRENT → :$WORKING_PORT"
    sed -i "s|HTTPS_PROXY=http://127.0.0.1:[0-9]*|HTTPS_PROXY=http://127.0.0.1:$WORKING_PORT|" "$CODEX_WRAPPER"
fi

# TG: proxychains для telegram-bot-api. Hiddify (12334) = socks5, остальные = http.
if [[ -w "$PROXYCHAINS" ]] || sudo -n true 2>/dev/null; then
    if [[ "$WORKING_PORT" == "12334" ]]; then
        PC_LINE="socks5 127.0.0.1 12334"
    else
        PC_LINE="http 127.0.0.1 $WORKING_PORT"
    fi
    PC_CURRENT=$(grep -E '^(socks5|http) 127.0.0.1' "$PROXYCHAINS" 2>/dev/null | head -1)
    if [[ "$PC_CURRENT" != "$PC_LINE" ]]; then
        echo "🔧 Переключаю TG proxychains → $PC_LINE"
        printf 'strict_chain\nproxy_dns\n[ProxyList]\n%s\n' "$PC_LINE" | sudo -n tee "$PROXYCHAINS" > /dev/null 2>&1 \
            && sudo -n systemctl restart telegram-bot-api 2>/dev/null \
            && echo "   → telegram-bot-api рестартнут" \
            || echo "   ⚠️  нет sudo — TG не переключён"
    fi
fi

echo ""
if [[ "${NEED_ORCH_RESTART:-0}" == "1" ]]; then
    echo "⚠️  Orchestra прокси сменился — рестартни: sudo systemctl restart orchestra"
else
    echo "✅ Всё на :$WORKING_PORT, рестарт Orchestra не нужен"
fi
