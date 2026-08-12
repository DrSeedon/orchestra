#!/usr/bin/env bash
set -euo pipefail
umask 0077

usage() {
    echo "Usage: $0 {install|rollback}" >&2
    exit 2
}

[[ $# -eq 1 ]] || usage
ACTION=$1
case "$ACTION" in
    install|rollback) ;;
    *) usage ;;
esac

SOURCE_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
DESTDIR=${DESTDIR:-}
SYSTEMCTL=${SYSTEMCTL:-systemctl}
SYSTEMD_ANALYZE=${SYSTEMD_ANALYZE:-systemd-analyze}

if [[ -n "$DESTDIR" && "$DESTDIR" != /* ]]; then
    echo "DESTDIR must be absolute" >&2
    exit 2
fi
if [[ -z "$DESTDIR" && $EUID -ne 0 ]]; then
    echo "Run as root (or set DESTDIR for an isolated test)" >&2
    exit 1
fi

HOOK_DEST="$DESTDIR/etc/orchestra/claude-env.sh"
DROPIN_DEST="$DESTDIR/etc/systemd/system/orchestra.service.d/211-claude-env.conf"
STATE_ROOT="$DESTDIR/var/lib/orchestra-claude-env-hook"
STATE_DIR="$STATE_ROOT/deploy-state"

SOURCES=(
    "$SOURCE_ROOT/deploy/orchestra-claude-env.sh"
    "$SOURCE_ROOT/deploy/orchestra-claude-env.conf"
)
DESTINATIONS=("$HOOK_DEST" "$DROPIN_DEST")
KEYS=(hook dropin)
MODES=(0644 0644)

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

save_previous_files() {
    mkdir -p "$STATE_DIR/backup"
    local index destination key
    for index in "${!DESTINATIONS[@]}"; do
        destination=${DESTINATIONS[$index]}
        key=${KEYS[$index]}
        if [[ -e "$destination" || -L "$destination" ]]; then
            cp -a -- "$destination" "$STATE_DIR/backup/$key"
            printf 'present\n' > "$STATE_DIR/$key.state"
        else
            printf 'absent\n' > "$STATE_DIR/$key.state"
        fi
    done
}

record_expected_hashes() {
    local index source source_hash
    : > "$STATE_DIR/installed.sha256"
    for index in "${!SOURCES[@]}"; do
        source=${SOURCES[$index]}
        source_hash=$(sha256sum "$source" | awk '{print $1}')
        printf '%s  %s\n' "$source_hash" "${KEYS[$index]}" >> "$STATE_DIR/installed.sha256"
    done
}

verify_installed_hashes() {
    local index destination key expected destination_hash
    for index in "${!DESTINATIONS[@]}"; do
        destination=${DESTINATIONS[$index]}
        key=${KEYS[$index]}
        expected=$(awk -v key="$key" '$2 == key { print $1 }' "$STATE_DIR/installed.sha256")
        destination_hash=$(sha256sum "$destination" | awk '{print $1}')
        if [[ -z "$expected" || "$expected" != "$destination_hash" ]]; then
            echo "Installed hash mismatch: $destination" >&2
            exit 1
        fi
    done
}

CLAIMS=()

restore_claims() {
    local index destination claim failed=false
    for index in "${!DESTINATIONS[@]}"; do
        destination=${DESTINATIONS[$index]}
        claim=${CLAIMS[$index]:-}
        [[ -n "$claim" ]] || continue
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

claim_matches_saved() {
    local index=$1 claim=$2 key=${KEYS[$1]} state backup
    state=$(<"$STATE_DIR/$key.state")
    [[ "$state" == present ]] || return 1
    backup="$STATE_DIR/backup/$key"
    if [[ -L "$claim" && -L "$backup" ]]; then
        [[ "$(readlink -- "$claim")" == "$(readlink -- "$backup")" ]]
    elif [[ -f "$claim" && ! -L "$claim" && -f "$backup" && ! -L "$backup" ]]; then
        cmp -s -- "$claim" "$backup"
    else
        return 1
    fi
}

claim_and_verify_install() {
    local index destination claim key expected actual
    CLAIMS=()
    for index in "${!DESTINATIONS[@]}"; do
        destination=${DESTINATIONS[$index]}
        key=${KEYS[$index]}
        CLAIMS[$index]=""
        if [[ ! -e "$destination" && ! -L "$destination" ]]; then
            if [[ "$(<"$STATE_DIR/$key.state")" == absent ]]; then
                continue
            fi
            echo "Managed file disappeared since install: $destination" >&2
            restore_claims || true
            exit 1
        fi

        claim="${destination}.rollback-claim.$$"
        mv -Tn "$destination" "$claim" || true
        if [[ -e "$destination" || -L "$destination" ]]; then
            echo "Could not claim managed file without overwriting retained data: $destination" >&2
            restore_claims || true
            exit 1
        fi
        if [[ ! -e "$claim" && ! -L "$claim" ]]; then
            echo "Managed file vanished while claiming: $destination" >&2
            restore_claims || true
            exit 1
        fi
        CLAIMS[$index]=$claim

        if claim_matches_saved "$index" "$claim"; then
            continue
        fi
        expected=""
        if [[ -f "$STATE_DIR/installed.sha256" ]]; then
            expected=$(awk -v key="$key" '$2 == key { print $1 }' "$STATE_DIR/installed.sha256")
        fi
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

install_hook() {
    if [[ -e "$STATE_DIR" ]]; then
        echo "Existing deploy state: $STATE_DIR (rollback before reinstalling)" >&2
        exit 1
    fi
    for source in "${SOURCES[@]}"; do
        [[ -f "$source" ]] || { echo "Missing source: $source" >&2; exit 1; }
    done
    bash -n "${SOURCES[0]}"

    save_previous_files
    record_expected_hashes
    local index
    for index in "${!SOURCES[@]}"; do
        atomic_install "${SOURCES[$index]}" "${DESTINATIONS[$index]}" "${MODES[$index]}"
    done
    verify_installed_hashes
    "$SYSTEMD_ANALYZE" verify orchestra.service
    "$SYSTEMCTL" daemon-reload
    echo "Installed Claude env hook; Orchestra restart is required and was NOT performed"
}

restore_one() {
    local index=$1 destination=${DESTINATIONS[$1]} key=${KEYS[$1]} claim=${CLAIMS[$1]:-} state removed
    [[ -n "$claim" ]] || return 0
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
    removed="$STATE_DIR/removed/$key"
    mv -Tn "$claim" "$removed" || true
    if [[ -e "$claim" || -L "$claim" ]]; then
        echo "Could not archive claimed file without overwriting retained data: $removed" >&2
        exit 1
    fi
}

validate_restore_hook() {
    local state
    state=$(<"$STATE_DIR/hook.state")
    case "$state" in
        present) bash -n "$STATE_DIR/backup/hook" ;;
        absent) ;;
        *) echo "Invalid saved state for hook: $state" >&2; exit 1 ;;
    esac
}

rollback_hook() {
    [[ -d "$STATE_DIR" ]] || { echo "No deploy state: $STATE_DIR" >&2; exit 1; }
    validate_restore_hook
    claim_and_verify_install
    local index
    for index in "${!DESTINATIONS[@]}"; do
        restore_one "$index"
    done
    "$SYSTEMCTL" daemon-reload

    local archive="$STATE_ROOT/rollback-$(date -u +%Y%m%dT%H%M%SZ)"
    mv -Tn "$STATE_DIR" "$archive" || true
    if [[ -e "$STATE_DIR" || -L "$STATE_DIR" ]]; then
        echo "Could not archive deploy state without overwriting retained data: $archive" >&2
        exit 1
    fi
    echo "Rolled back Claude env hook; Orchestra restart is required and was NOT performed"
}

case "$ACTION" in
    install) install_hook ;;
    rollback) rollback_hook ;;
esac
