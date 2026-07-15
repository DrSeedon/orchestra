#!/bin/bash
# Проверяет все прокси из PROXY_LIST и переключает Orchestra+TG на первый рабочий.
# Claude/Codex/Cursor читают тот же .env при запуске, отдельно их переписывать не надо.
# Запускай при смене сети (сменил WiFi / выключил VPN): bash scripts/check-proxies.sh
#
# WHY: все прокси = ssh -L туннели к VPS, маршрут к которым иногда идёт через tun0 (Reality VPN).
# При смене сети часть туннелей дохнет. Скрипт находит живой и переключает на него всё.

set -uo pipefail
ENV_FILE="/mnt/data/Projects/Python/orchestra/.env"
PROXYCHAINS="/etc/proxychains4.conf"

# Единственный реестр маршрутов и их приоритета — PROXY_LIST в .env.
PROXY_LIST=$(sed -n 's/^PROXY_LIST=//p' "$ENV_FILE" | head -1)
[[ -n "$PROXY_LIST" ]] || { echo "🚨 PROXY_LIST отсутствует в $ENV_FILE"; exit 1; }

CANDIDATE_NAMES=()
CANDIDATE_URLS=()
CANDIDATE_PORTS=()
IFS=',' read -ra PROXY_ENTRIES <<< "$PROXY_LIST"
for item in "${PROXY_ENTRIES[@]}"; do
    [[ "$item" == *"|"* ]] || continue
    name="${item%%|*}"
    url="${item#*|}"
    [[ "$url" == "direct" ]] && continue
    port="${url##*:}"
    [[ "$port" =~ ^[0-9]+$ ]] || continue
    CANDIDATE_NAMES+=("$name")
    CANDIDATE_URLS+=("$url")
    CANDIDATE_PORTS+=("$port")
done
(( ${#CANDIDATE_PORTS[@]} > 0 )) || { echo "🚨 В PROXY_LIST нет прокси-кандидатов"; exit 1; }

TEST_URL="https://api.anthropic.com"
echo "🔍 Проверяю прокси (цель: $TEST_URL)..."
echo "   (SSH туннели после смены сети встают ~5-30с — жду до 60с)"
echo ""

# WHY: при смене сети/выключении VPN Orchestra пересоздаёт SSH туннели по одному
# с задержкой 5с. Разовая проверка ловит окно когда туннели ещё не встали → ложная паника.
# Ретраим полный цикл до 60с, пока хоть один прокси не оживёт.
# WHY приоритетный выбор: PROXY_LIST уже отсортирован по приоритету.
# На старте туннели встают 5-30с в РАЗНОМ порядке — низкоприоритетный Hiddify может
# ожить раньше Contabo. Берём ПЕРВЫЙ живой в проходе (он приоритетнее по позиции),
# НО пока не истёк GRACE (30с) — ждём топовый, не хватаем первый попавшийся живой
# если это не голова списка. После GRACE соглашаемся на любой живой.
WORKING_PORT=""
WORKING_NAME=""
DEADLINE=$(( $(date +%s) + 60 ))
GRACE_UNTIL=$(( $(date +%s) + 30 ))
attempt=0
while :; do
    attempt=$(( attempt + 1 ))
    # первый живой в порядке приоритета за этот проход
    for i in "${!CANDIDATE_PORTS[@]}"; do
        name="${CANDIDATE_NAMES[$i]}"
        url="${CANDIDATE_URLS[$i]}"
        port="${CANDIDATE_PORTS[$i]}"
        ss -tlnH "sport = :$port" 2>/dev/null | grep -q ":$port" || continue
        code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 8 -x "$url" "$TEST_URL" 2>/dev/null)
        [[ "$code" =~ ^(200|401|403|404)$ ]] || continue
        WORKING_PORT="$port"; WORKING_NAME="$name"; WORKING_URL="$url"
        break
    done
    if [[ -n "$WORKING_PORT" ]]; then
        # Первые два маршрута из PROXY_LIST → берём сразу. Ниже → только после GRACE.
        top2="${CANDIDATE_PORTS[0]} ${CANDIDATE_PORTS[1]:-}"
        if [[ " $top2 " == *" $WORKING_PORT "* ]] || [[ $(date +%s) -ge $GRACE_UNTIL ]]; then
            printf "  ✅ %-12s (:%s) — работает\n" "$WORKING_NAME" "$WORKING_PORT"
            break
        fi
        printf "  ⏳ жив %s, но жду топовый (grace)...\n" "$WORKING_NAME"
        WORKING_PORT=""; WORKING_NAME=""
    fi
    [[ $(date +%s) -ge $DEADLINE ]] && break
    printf "  ⏳ попытка %s — жду 5с пока туннели встают...\n" "$attempt"
    sleep 5
done

echo ""
if [[ -z "$WORKING_PORT" ]]; then
    echo "🚨 За 60с НИ ОДИН прокси не поднялся. Проверь:"
    echo "   • Orchestra запущена? (sudo systemctl status orchestra)"
    echo "   • Есть выход наружу? (Anthropic API заблокирован в РФ без VPN/прокси)"
    echo "   • VPS живы? (ssh root@158.220.127.161)"
    exit 1
fi

echo "🎯 Рабочий прокси: $WORKING_NAME (:$WORKING_PORT)"

# Текущий прокси в .env
CURRENT=$(sed -n 's/^HTTPS_PROXY=//p' "$ENV_FILE" | head -1)
if [[ "$CURRENT" == "$WORKING_URL" ]]; then
    echo "✅ Orchestra уже на :$WORKING_PORT — ничего менять не нужно"
else
    echo "🔧 Переключаю Orchestra → $WORKING_NAME (:$WORKING_PORT)"
    escaped_url=${WORKING_URL//&/\\&}
    sed -i "s|^HTTPS_PROXY=.*|HTTPS_PROXY=$escaped_url|" "$ENV_FILE"
    sed -i "s|^HTTP_PROXY=.*|HTTP_PROXY=$escaped_url|" "$ENV_FILE"
    echo "   → нужен рестарт: sudo systemctl restart orchestra"
    NEED_ORCH_RESTART=1
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
else
    echo "⚠️  TG proxychains не проверен: нет доступа к изменению $PROXYCHAINS"
fi

echo ""
if [[ "${NEED_ORCH_RESTART:-0}" == "1" ]]; then
    echo "⚠️  Orchestra прокси сменился — рестартни: sudo systemctl restart orchestra"
else
    echo "✅ Orchestra и launchers Claude/Codex/Cursor используют :$WORKING_PORT; рестарт Orchestra не нужен"
fi
