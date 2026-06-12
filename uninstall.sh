#!/usr/bin/env sh
# Fireraven Windsurf FireGuard hooks uninstaller
# Usage: curl -fsSL https://raw.githubusercontent.com/fireravenai/windsurf-fireguard-hooks/refs/heads/main/uninstall.sh | sh

set -e

FIRERAVEN_HOOKS_REPO="${FIRERAVEN_HOOKS_REPO:-fireravenai/windsurf-fireguard-hooks}"
FIRERAVEN_HOOKS_REF="${FIRERAVEN_HOOKS_REF:-main}"
FIRERAVEN_INSTALL_DIR="${FIRERAVEN_INSTALL_DIR:-$HOME/.codeium/windsurf}"

TEMP_DIR=""
cleanup() {
    if [ -n "$TEMP_DIR" ] && [ -d "$TEMP_DIR" ]; then
        rm -rf "$TEMP_DIR"
    fi
}
trap cleanup EXIT

load_lib() {
    SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd || true)"
    if [ -n "$SCRIPT_DIR" ] && [ -f "${SCRIPT_DIR}/scripts/lib.sh" ]; then
        # shellcheck source=scripts/lib.sh
        . "${SCRIPT_DIR}/scripts/lib.sh"
        return 0
    fi

    if ! command -v curl >/dev/null 2>&1; then
        printf '\033[0;31m[ERROR]\033[0m curl is required but was not found on PATH\n'
        exit 1
    fi

    TEMP_DIR="$(mktemp -d)"
    RAW_BASE="https://raw.githubusercontent.com/${FIRERAVEN_HOOKS_REPO}/refs/heads/${FIRERAVEN_HOOKS_REF}"
    if ! curl -fsSL "${RAW_BASE}/scripts/lib.sh" -o "${TEMP_DIR}/lib.sh"; then
        printf '\033[0;31m[ERROR]\033[0m Failed to download uninstall library from %s\n' "$RAW_BASE/scripts/lib.sh"
        exit 1
    fi

    # shellcheck source=/dev/null
    . "${TEMP_DIR}/lib.sh"
}

load_lib

main() {
    info "Uninstalling Fireraven Windsurf FireGuard hooks from ${FIRERAVEN_INSTALL_DIR}"

    remove_hooks_json_entry

    for file in $HOOK_FILES; do
        target="$(hooks_dir)/$file"
        if [ -f "$target" ]; then
            rm -f "$target"
            info "Removed $target"
        fi
    done

    if [ -d "$(hooks_dir)" ] && [ -z "$(ls -A "$(hooks_dir)" 2>/dev/null)" ]; then
        rmdir "$(hooks_dir)" 2>/dev/null || true
    fi

    warn "config.env was not removed (may contain secrets): $(hooks_dir)/config.env"
    info "Restart Windsurf to apply hook changes"
}

main
