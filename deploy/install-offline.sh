#!/usr/bin/env bash
# Офлайн-установка Orchestra из комплекта поставки: без uv, без git, без доступа в сеть.
# Запускать из распакованного архива: sudo ./deploy/install-offline.sh [--dir /opt/orchestra]
#   [--user orchestra] [--port 8888] [--no-service]
# Нужны только python3.12 с модулем venv (пакет python3.12-venv) и wheels/ рядом.
set -euo pipefail

BUNDLE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR=/opt/orchestra
RUN_USER=orchestra
PORT=8888
SERVICE=1
while [ $# -gt 0 ]; do
    case "$1" in
        --dir) INSTALL_DIR="$2"; shift 2 ;;
        --user) RUN_USER="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --no-service) SERVICE=0; shift ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

[ -d "$BUNDLE/wheels" ] || { echo "wheels/ not found in $BUNDLE" >&2; exit 1; }
command -v python3.12 >/dev/null || { echo "python3.12 required" >&2; exit 1; }
command -v git >/dev/null || { echo "git required (the task store is a local git repository)" >&2; exit 1; }
VENV="$INSTALL_DIR/.venv"

echo "[1/5] User and directories..."
if ! id "$RUN_USER" &>/dev/null; then
    useradd --system --shell /bin/bash --home-dir "/home/$RUN_USER" --create-home "$RUN_USER"
fi
mkdir -p "$INSTALL_DIR"
if [ "$BUNDLE" != "$INSTALL_DIR" ]; then
    # .env и data/ существующей установки не трогаем.
    tar -C "$BUNDLE" --exclude=./.env --exclude=./data --exclude=./.venv -cf - . | tar -C "$INSTALL_DIR" -xf -
fi
mkdir -p "$INSTALL_DIR/data/uploads" "$INSTALL_DIR/worktrees"
chown -R "$RUN_USER:$RUN_USER" "$INSTALL_DIR"

echo "[2/5] Virtualenv + dependencies from wheels/ (no network)..."
run() { if [ "$(id -u)" = 0 ]; then runuser -u "$RUN_USER" -- "$@"; else "$@"; fi; }
# Хранилище задач — локальный git-репозиторий, коммиты идут от имени пользователя сервиса.
run git config --global --get user.email >/dev/null 2>&1 || {
    run git config --global user.name "Orchestra"
    run git config --global user.email "orchestra@localhost"
}
[ -d "$VENV" ] || run python3.12 -m venv "$VENV"
run "$VENV/bin/pip" install --no-index --find-links "$INSTALL_DIR/wheels" \
    --require-hashes -r "$INSTALL_DIR/requirements-offline.txt"

# Каталог проектов обязателен при старте; наш собственный в комплект не входит.
if [ ! -f "$INSTALL_DIR/.orchestra/projects.yaml" ]; then
    mkdir -p "$INSTALL_DIR/.orchestra"
    printf 'version: 1\nprojects: []\n' > "$INSTALL_DIR/.orchestra/projects.yaml"
    chown -R "$RUN_USER:$RUN_USER" "$INSTALL_DIR/.orchestra"
fi

echo "[3/5] .env..."
if [ ! -f "$INSTALL_DIR/.env" ]; then
    DASH_PASS=$(openssl rand -hex 16)
    INT_TOKEN=$(openssl rand -hex 32)
    cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
    sed -i "s/change-me-use-openssl-rand-hex-32/$INT_TOKEN/; s/change-me-use-openssl-rand/$DASH_PASS/" "$INSTALL_DIR/.env"
    chown "$RUN_USER:$RUN_USER" "$INSTALL_DIR/.env"
    chmod 600 "$INSTALL_DIR/.env"
    echo "  Dashboard: admin / $DASH_PASS"
else
    echo "  .env exists, kept"
fi

if [ "$SERVICE" = 1 ]; then
    echo "[4/5] systemd service..."
    # Юнит из шаблона без `uv sync`: uv в комплекте нет и не нужен.
    sed -e '/^ExecStartPre=/d' \
        -e "s#/opt/orchestra#$INSTALL_DIR#g" -e "s#--port 8888#--port $PORT#" \
        -e "s#^User=.*#User=$RUN_USER#" -e "s#^Group=.*#Group=$RUN_USER#" \
        "$INSTALL_DIR/deploy/orchestra.service.template" > /etc/systemd/system/orchestra.service
    systemctl daemon-reload
    systemctl enable --now orchestra
else
    echo "[4/5] systemd skipped (--no-service). Start manually:"
    echo "  cd $INSTALL_DIR && set -a && . ./.env && set +a && $VENV/bin/uvicorn app.main:app --host 127.0.0.1 --port $PORT"
fi

echo "[5/5] Done. Nginx/TLS are optional and not configured."
