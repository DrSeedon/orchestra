#!/usr/bin/env bash
set -euo pipefail
umask 0077

usage() {
    echo "Usage: $0 {stage|activate|install|disable|rollback}" >&2
    exit 2
}

[[ $# -eq 1 ]] || usage
ACTION=$1
case "$ACTION" in
    stage|activate|install|disable|rollback) ;;
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

atomic_restore_noreplace() {
    local source=$1 destination=$2 temporary
    mkdir -p "$(dirname "$destination")"
    temporary="${destination}.restore.$$"
    cp -a -- "$source" "$temporary"
    mv -Tn "$temporary" "$destination" || true
    if [[ -e "$temporary" || -L "$temporary" ]]; then
        echo "Destination appeared during rollback; preserved both files: $destination" >&2
        return 1
    fi
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

record_installed_hashes() {
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

verify_staged_files() {
    local index source destination key expected source_hash destination_hash
    for index in "${!SOURCES[@]}"; do
        source=${SOURCES[$index]}
        destination=${DESTINATIONS[$index]}
        key=${KEYS[$index]}
        expected=$(awk -v key="$key" '$2 == key { print $1 }' "$STATE_DIR/installed.sha256")
        source_hash=$(sha256sum "$source" | awk '{print $1}')
        destination_hash=$(sha256sum "$destination" | awk '{print $1}')
        if [[ -z "$expected" || "$source_hash" != "$expected" || "$destination_hash" != "$expected" ]]; then
            echo "Staged file changed: $destination" >&2
            exit 1
        fi
    done
}

verify_observe_only_config() {
    local enabled dry_run rss_action
    enabled=$(awk -F= '$1 == "ENABLED" { print $2 }' "$CONFIG_DEST")
    dry_run=$(awk -F= '$1 == "DRY_RUN" { print $2 }' "$CONFIG_DEST")
    rss_action=$(awk -F= '$1 == "RSS_ACTION" { print $2 }' "$CONFIG_DEST")
    if [[ "$enabled" != false || "$dry_run" != true || "$rss_action" != log ]]; then
        echo "Refusing non-observe policy: ENABLED=$enabled DRY_RUN=$dry_run RSS_ACTION=$rss_action" >&2
        exit 1
    fi
}

stage_guard() {
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
    record_installed_hashes
    "$SYSTEMD_ANALYZE" verify "$UNIT_DEST"
    "$SYSTEMCTL" daemon-reload
    echo "Staged $SERVICE in observe-only defaults; service was NOT enabled or started"
}

activate_guard() {
    [[ -d "$STATE_DIR" ]] || { echo "No staged deploy state: $STATE_DIR" >&2; exit 1; }
    verify_staged_files
    verify_observe_only_config
    "$SYSTEMCTL" enable --now "$SERVICE"
    echo "Activated $SERVICE in observe-only mode. State: $STATE_DIR"
}

install_guard() {
    stage_guard
    activate_guard
}

disable_guard() {
    "$SYSTEMCTL" disable --now "$SERVICE"
    echo "Disabled $SERVICE; installed files and deploy state were kept"
}

CLAIMS=()

restore_claims() {
    local index destination claim failed=false
    for index in "${!CLAIMS[@]}"; do
        destination=${DESTINATIONS[$index]}
        claim=${CLAIMS[$index]}
        if [[ -e "$claim" || -L "$claim" ]]; then
            mv -Tn "$claim" "$destination" || true
            if [[ -e "$claim" || -L "$claim" ]]; then
                echo "Could not restore claimed file without overwriting: $destination" >&2
                failed=true
            fi
        fi
    done
    [[ "$failed" == false ]]
}

claim_and_verify_install() {
    local index destination claim key expected actual
    for index in "${!DESTINATIONS[@]}"; do
        destination=${DESTINATIONS[$index]}
        claim="${destination}.rollback-claim.$$"
        CLAIMS+=("$claim")
        mv -Tn "$destination" "$claim" || true
        if [[ -e "$destination" || -L "$destination" ]]; then
            echo "Could not claim managed file without overwriting retained data: $destination" >&2
            restore_claims || true
            exit 1
        fi
    done

    for index in "${!CLAIMS[@]}"; do
        claim=${CLAIMS[$index]}
        key=${KEYS[$index]}
        expected=$(awk -v key="$key" '$2 == key { print $1 }' "$STATE_DIR/installed.sha256")
        if [[ -z "$expected" || ! -f "$claim" || -L "$claim" ]]; then
            echo "Managed file was replaced since install: ${DESTINATIONS[$index]}" >&2
            restore_claims || true
            exit 1
        fi
        actual=$(sha256sum "$claim" | awk '{print $1}')
        if [[ "$actual" != "$expected" ]]; then
            echo "Managed file changed since install: ${DESTINATIONS[$index]}" >&2
            restore_claims || true
            exit 1
        fi
    done
}

restore_one() {
    local index=$1 destination=${DESTINATIONS[$1]} key=${KEYS[$1]} claim=${CLAIMS[$1]} state
    state=$(<"$STATE_DIR/$key.state")
    if [[ "$state" == present ]]; then
        atomic_restore_noreplace "$STATE_DIR/backup/$key" "$destination"
    elif [[ "$state" == absent ]]; then
        :
    else
        echo "Invalid saved state for $key: $state" >&2
        exit 1
    fi
    mkdir -p "$STATE_DIR/removed"
    mv -T "$claim" "$STATE_DIR/removed/$key"
}

rollback_guard() {
    [[ -d "$STATE_DIR" ]] || { echo "No deploy state: $STATE_DIR" >&2; exit 1; }
    "$SYSTEMCTL" disable --now "$SERVICE" 2>/dev/null || true
    claim_and_verify_install

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
    stage) stage_guard ;;
    activate) activate_guard ;;
    install) install_guard ;;
    disable) disable_guard ;;
    rollback) rollback_guard ;;
esac
