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
    install -o root -g root -m 0600 "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
    DASH_PASS="$DASH_PASS" INT_TOKEN="$INT_TOKEN" python3 - "$INSTALL_DIR/.env" << 'ENVPY'
import os, pathlib, sys
env_path = pathlib.Path(sys.argv[1])
dash_pass = os.environ["DASH_PASS"]
int_token = os.environ["INT_TOKEN"]
out = []
for line in env_path.read_text(encoding="utf-8").splitlines(keepends=True):
    if line.startswith("DASHBOARD_PASSWORD="):
        out.append(f"DASHBOARD_PASSWORD={dash_pass}\n")
    elif line.startswith("INTERNAL_TOKEN="):
        out.append(f"INTERNAL_TOKEN={int_token}\n")
    elif line.startswith("# COOKIE_SECURE="):
        out.append("COOKIE_SECURE=1\n")
    else:
        out.append(line)
env_path.write_text("".join(out), encoding="utf-8")
ENVPY
    chown $USER:$USER "$INSTALL_DIR/.env"
    chmod 600 "$INSTALL_DIR/.env"
    echo "  .env created with random secrets at $INSTALL_DIR/.env (mode 0600); inspect securely if needed"
else
    echo "  .env already exists, skipping"
fi

echo "[6/8] Data directory..."
sudo -u $USER mkdir -p "$INSTALL_DIR/data/uploads"
sudo -u $USER mkdir -p "$INSTALL_DIR/worktrees"

echo "[7/8] Systemd service..."
# Keep root-owned clean templates separately from the unprivileged runtime checkout.
SYS_TEMPLATE="/usr/local/share/orchestra/orchestra.service"
mkdir -p /usr/local/share/orchestra
chown root:root /usr/local/share/orchestra
chmod 0755 /usr/local/share/orchestra
if [ ! -f "$SYS_TEMPLATE" ]; then
    cat > "$SYS_TEMPLATE" << 'UNITEOF'
[Unit]
Description=Orchestra AI Agent Orchestrator
After=network.target

[Service]
Type=simple
User=orchestra
Group=orchestra
WorkingDirectory=/opt/orchestra
Environment=PATH=/opt/orchestra/.venv/bin:/usr/local/bin:/usr/bin:/bin
EnvironmentFile=/opt/orchestra/.env
StateDirectory=orchestra
StateDirectoryMode=0700
ExecStartPre=/usr/local/bin/uv sync --quiet
ExecStart=/opt/orchestra/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8888 --timeout-graceful-shutdown 5
Restart=always
RestartSec=5
TimeoutStopSec=30
KillMode=control-group
SendSIGKILL=yes
Delegate=yes
FileDescriptorStoreMax=0
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNITEOF
fi
[ "$(stat -c '%u' "$SYS_TEMPLATE")" = "0" ] && [ ! -L "$SYS_TEMPLATE" ]
install -o root -g root -m 0644 "$SYS_TEMPLATE" /etc/systemd/system/orchestra.service
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
NGINX_TPL="/usr/local/share/orchestra/nginx.conf"
if [ ! -f "$NGINX_TPL" ]; then
    cat > "$NGINX_TPL" << 'NGXEOF'
server {
    listen 127.0.0.1:80;
    listen [::1]:80;
    server_name _;

    client_max_body_size 50M;

    location = /login {
        proxy_pass http://127.0.0.1:8888;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:8888;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
        proxy_buffering off;
    }
}
NGXEOF
fi
[ "$(stat -c '%u' "$NGINX_TPL")" = "0" ] && [ ! -L "$NGINX_TPL" ]
install -o root -g root -m 0644 "$NGINX_TPL" /etc/nginx/sites-available/orchestra
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
# The TG bridge refuses to start unless systemd socket-activated the process itself
# (app/tg_bridge.py, #324). orchestra.service.template binds --host/--port, so setting the token
# on this installation would produce a bridge that never starts and says so only in the journal.
# Say what it costs instead of inviting a dead configuration.
echo "  4. (Optional) TG bot: NOT available with this unit template — it binds --host/--port,"
echo "     and the bridge only runs under socket activation (deploy/orchestra.socket +"
echo "     ExecStart=<venv>/bin/python -m uvicorn app.main:app --fd 3, interpreter exec'd"
echo "     directly, no 'uv run'). Setting TG_BRIDGE_TOKEN alone will NOT start it."
