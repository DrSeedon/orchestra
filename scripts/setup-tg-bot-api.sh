#!/bin/bash
set -e

echo "=== Installing Telegram Local Bot API Server ==="
echo "This enables file downloads up to 2GB (vs 20MB on public API)"
echo ""

if command -v telegram-bot-api &>/dev/null; then
    echo "telegram-bot-api already installed at $(which telegram-bot-api)"
    echo "To reinstall, remove it first: sudo rm $(which telegram-bot-api)"
    exit 0
fi

read -p "Enter api_id (from https://my.telegram.org): " API_ID
read -p "Enter api_hash: " API_HASH

if [ -z "$API_ID" ] || [ -z "$API_HASH" ]; then
    echo "ERROR: api_id and api_hash required. Get them at https://my.telegram.org → API Development Tools"
    exit 1
fi

echo "Installing build dependencies..."
apt install -y make git g++ cmake libssl-dev zlib1g-dev gperf

echo "Cloning telegram-bot-api..."
cd /opt
git clone --recursive https://github.com/tdlib/telegram-bot-api.git
cd telegram-bot-api
mkdir -p build && cd build
echo "Building (this takes 5-15 minutes)..."
cmake -DCMAKE_BUILD_TYPE=Release ..
cmake --build . --target install -j$(nproc)

DATADIR="/mnt/data/Projects/Python/orchestra/data/tg-bot-api"
mkdir -p "$DATADIR"

cat > /etc/systemd/system/telegram-bot-api.service << EOF
[Unit]
Description=Telegram Bot API Server
After=network.target

[Service]
ExecStart=/usr/local/bin/telegram-bot-api --api-id=$API_ID --api-hash=$API_HASH --local --http-port=8081 --dir=$DATADIR
Restart=always
User=$(logname)
WorkingDirectory=$DATADIR

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now telegram-bot-api

echo ""
echo "=== Done! ==="
echo "Telegram Bot API Server running on http://localhost:8081"
echo ""
echo "Add to your .env:"
echo "TG_LOCAL_API_URL=http://localhost:8081"
echo ""
echo "Then restart Orchestra: sudo systemctl restart orchestra"
