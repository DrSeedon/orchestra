#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: $0 {install|disable|rollback}" >&2
    exit 2
}

[[ $# -eq 1 ]] || usage
ACTION=$1
case "$ACTION" in
    install|disable|rollback) ;;
    *) usage ;;
esac

SOURCE_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
DESTDIR=${DESTDIR:-}
SYSTEMCTL=${SYSTEMCTL:-systemctl}
SYSTEMD_ANALYZE=${SYSTEMD_ANALYZE:-systemd-analyze}
SERVICE=orchestra-process-guard.service

if [[ -n "$DESTDIR" && "$DESTDIR" != /* ]]; then
    echo "DESTDIR must be absolute" >&2
    exit 2
fi
if [[ -z "$DESTDIR" && $EUID -ne 0 ]]; then
    echo "Run as root (or set DESTDIR for an isolated test)" >&2
    exit 1
fi

SCRIPT_DEST="$DESTDIR/usr/local/libexec/orchestra-process-guard"
UNIT_DEST="$DESTDIR/etc/systemd/system/$SERVICE"
CONFIG_DEST="$DESTDIR/etc/orchestra-process-guard.conf"
STATE_ROOT="$DESTDIR/var/lib/orchestra-process-guard"
STATE_DIR="$STATE_ROOT/deploy-state"

SOURCES=(
    "$SOURCE_ROOT/scripts/orchestra_process_guard.py"
    "$SOURCE_ROOT/deploy/orchestra-process-guard.service"
    "$SOURCE_ROOT/deploy/orchestra-process-guard.conf"
)
DESTINATIONS=("$SCRIPT_DEST" "$UNIT_DEST" "$CONFIG_DEST")
KEYS=(script unit config)
MODES=(0755 0644 0600)

atomic_install() {
    local source=$1 destination=$2 mode=$3 temporary
    mkdir -p "$(dirname "$destination")"
    temporary="${destination}.new.$$"
    install -m "$mode" "$source" "$temporary"
    mv -f "$temporary" "$destination"
}

atomic_restore() {
    local source=$1 destination=$2 temporary
    mkdir -p "$(dirname "$destination")"
    temporary="${destination}.restore.$$"
    cp -a -- "$source" "$temporary"
    mv -Tf "$temporary" "$destination"
}

save_previous_state() {
    mkdir -p "$STATE_DIR/backup"
    local enabled=disabled active=inactive
    if "$SYSTEMCTL" is-enabled --quiet "$SERVICE" 2>/dev/null; then
        enabled=enabled
    fi
    if "$SYSTEMCTL" is-active --quiet "$SERVICE" 2>/dev/null; then
        active=active
    fi
    printf 'enabled=%s\nactive=%s\n' "$enabled" "$active" > "$STATE_DIR/service.state"

    local index destination key
    for index in "${!DESTINATIONS[@]}"; do
        destination=${DESTINATIONS[$index]}
        key=${KEYS[$index]}
        if [[ -e "$destination" || -L "$destination" ]]; then
            cp -a "$destination" "$STATE_DIR/backup/$key"
            printf 'present\n' > "$STATE_DIR/$key.state"
        else
            printf 'absent\n' > "$STATE_DIR/$key.state"
        fi
    done
}

verify_installed_hashes() {
    local index source destination source_hash destination_hash
    : > "$STATE_DIR/installed.sha256"
    for index in "${!SOURCES[@]}"; do
        source=${SOURCES[$index]}
        destination=${DESTINATIONS[$index]}
        source_hash=$(sha256sum "$source" | awk '{print $1}')
        destination_hash=$(sha256sum "$destination" | awk '{print $1}')
        if [[ "$source_hash" != "$destination_hash" ]]; then
            echo "Installed hash mismatch: $destination" >&2
            exit 1
        fi
        printf '%s  %s\n' "$destination_hash" "${KEYS[$index]}" >> "$STATE_DIR/installed.sha256"
    done
}

install_guard() {
    if [[ -e "$STATE_DIR" ]]; then
        echo "Existing deploy state: $STATE_DIR (rollback before reinstalling)" >&2
        exit 1
    fi
    for source in "${SOURCES[@]}"; do
        [[ -f "$source" ]] || { echo "Missing source: $source" >&2; exit 1; }
    done

    save_previous_state
    local index
    for index in "${!SOURCES[@]}"; do
        atomic_install "${SOURCES[$index]}" "${DESTINATIONS[$index]}" "${MODES[$index]}"
    done
    verify_installed_hashes
    "$SYSTEMD_ANALYZE" verify "$UNIT_DEST"
    "$SYSTEMCTL" daemon-reload
    "$SYSTEMCTL" enable --now "$SERVICE"
    echo "Installed $SERVICE in observe-only defaults. State: $STATE_DIR"
}

disable_guard() {
    "$SYSTEMCTL" disable --now "$SERVICE"
    echo "Disabled $SERVICE; installed files and deploy state were kept"
}

restore_one() {
    local index=$1 destination=${DESTINATIONS[$1]} key=${KEYS[$1]} state
    state=$(<"$STATE_DIR/$key.state")
    if [[ "$state" == present ]]; then
        atomic_restore "$STATE_DIR/backup/$key" "$destination"
    elif [[ "$state" == absent ]]; then
        if [[ -e "$destination" || -L "$destination" ]]; then
            mkdir -p "$STATE_DIR/removed"
            mv "$destination" "$STATE_DIR/removed/$key"
        fi
    else
        echo "Invalid saved state for $key: $state" >&2
        exit 1
    fi
}

rollback_guard() {
    [[ -d "$STATE_DIR" ]] || { echo "No deploy state: $STATE_DIR" >&2; exit 1; }
    "$SYSTEMCTL" disable --now "$SERVICE" 2>/dev/null || true

    local index
    for index in "${!DESTINATIONS[@]}"; do
        restore_one "$index"
    done
    "$SYSTEMCTL" daemon-reload

    # shellcheck disable=SC1090
    source "$STATE_DIR/service.state"
    if [[ "$enabled" == enabled ]]; then
        "$SYSTEMCTL" enable "$SERVICE"
    fi
    if [[ "$active" == active ]]; then
        "$SYSTEMCTL" start "$SERVICE"
    fi

    local archive="$STATE_ROOT/rollback-$(date -u +%Y%m%dT%H%M%SZ)"
    mv "$STATE_DIR" "$archive"
    echo "Rolled back $SERVICE. Audit state: $archive"
}

case "$ACTION" in
    install) install_guard ;;
    disable) disable_guard ;;
    rollback) rollback_guard ;;
esac
