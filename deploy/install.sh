#!/usr/bin/env bash
set -euo pipefail

REPO="https://github.com/DrSeedon/orchestra.git"
INSTALL_DIR="/opt/orchestra"
VENV="$INSTALL_DIR/.venv"
SERVICE_NAME="orchestra"
NGINX_CONF="/etc/nginx/sites-available/orchestra"
USER="orchestra"

if [ $# -lt 1 ]; then
    echo "Usage: $0 <ssh-target> [git-branch]"
    echo "  ssh-target: user@ip (must have root/sudo)"
    echo "  git-branch: branch to checkout (default: main)"
    exit 1
fi

SSH_TARGET="$1"
GIT_BRANCH="${2:-main}"

echo "=== Orchestra Installer ==="
echo "Target: $SSH_TARGET"
echo "Branch: $GIT_BRANCH"
echo ""

ssh "$SSH_TARGET" bash -s "$GIT_BRANCH" << 'REMOTE_SCRIPT'
set -euo pipefail
GIT_BRANCH="$1"

REPO="https://github.com/DrSeedon/orchestra.git"
INSTALL_DIR="/opt/orchestra"
VENV="$INSTALL_DIR/.venv"
USER="orchestra"

echo "[1/8] System packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3.12 python3.12-venv python3-pip git nginx curl > /dev/null

echo "[2/8] Create user..."
if ! id "$USER" &>/dev/null; then
    useradd --system --shell /bin/bash --home-dir /home/$USER --create-home $USER
fi

echo "[3/8] Clone repo..."
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "  repo exists, pulling..."
    cd "$INSTALL_DIR"
    sudo -u $USER git fetch origin
    sudo -u $USER git checkout "$GIT_BRANCH"
    sudo -u $USER git pull origin "$GIT_BRANCH"
else
    git clone "$REPO" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
    git checkout "$GIT_BRANCH"
    chown -R $USER:$USER "$INSTALL_DIR"
fi

echo "[4/8] Python venv + dependencies..."
if [ ! -d "$VENV" ]; then
    sudo -u $USER python3.12 -m venv "$VENV"
fi
sudo -u $USER "$VENV/bin/pip" install --quiet --upgrade pip
sudo -u $USER "$VENV/bin/pip" install --quiet -e "$INSTALL_DIR"

echo "[5/8] .env configuration..."
if [ ! -f "$INSTALL_DIR/.env" ]; then
    DASH_PASS=$(openssl rand -hex 16)
    INT_TOKEN=$(openssl rand -hex 32)
    cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
    sed -i "s/change-me-use-openssl-rand/$DASH_PASS/" "$INSTALL_DIR/.env"
    sed -i "s/change-me-use-openssl-rand-hex-32/$INT_TOKEN/" "$INSTALL_DIR/.env"
    chown $USER:$USER "$INSTALL_DIR/.env"
    chmod 600 "$INSTALL_DIR/.env"
    echo "  .env created with random secrets"
    echo "  Dashboard: admin / $DASH_PASS"
else
    echo "  .env already exists, skipping"
fi

echo "[6/8] Data directory..."
sudo -u $USER mkdir -p "$INSTALL_DIR/data/uploads"
sudo -u $USER mkdir -p "$INSTALL_DIR/worktrees"

echo "[7/8] Systemd service..."
cp "$INSTALL_DIR/deploy/orchestra.service.template" /etc/systemd/system/orchestra.service
systemctl daemon-reload
systemctl enable orchestra
systemctl restart orchestra
sleep 2
if systemctl is-active --quiet orchestra; then
    echo "  orchestra service: running"
else
    echo "  WARNING: orchestra service failed to start"
    journalctl -u orchestra -n 10 --no-pager
fi

echo "[8/8] Nginx..."
cp "$INSTALL_DIR/deploy/nginx.conf.template" /etc/nginx/sites-available/orchestra
ln -sf /etc/nginx/sites-available/orchestra /etc/nginx/sites-enabled/orchestra
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
echo "  nginx configured"

echo ""
echo "=== Done ==="
echo "Orchestra: http://$(hostname -I | awk '{print $1}')"
echo ""
STATUS=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8888/ || echo "failed")
if [ "$STATUS" = "200" ] || [ "$STATUS" = "302" ]; then
    echo "Health check: OK (HTTP $STATUS)"
else
    echo "Health check: FAILED (HTTP $STATUS)"
    echo "Check: journalctl -u orchestra -f"
fi

REMOTE_SCRIPT

echo ""
echo "=== Install complete ==="
echo "SSH: ssh $SSH_TARGET"
echo "Logs: ssh $SSH_TARGET journalctl -u orchestra -f"
echo ""
echo "Next steps:"
echo "  1. Set up Claude Code auth: claude setup-token (on laptop)"
echo "  2. Copy token to VPS: ssh $SSH_TARGET 'echo CLAUDE_CODE_OAUTH_TOKEN=sk-ant-... >> /opt/orchestra/.env'"
echo "  3. (Optional) Add domain + SSL: certbot --nginx -d your-domain.com"
echo "  4. (Optional) TG bot: add TG_BRIDGE_TOKEN + TG_BRIDGE_GROUP to .env"
