#!/usr/bin/env sh
# Fireraven Windsurf FireGuard hooks installer
# Usage: curl -fsSL https://raw.githubusercontent.com/fireravenai/windsurf-fireguard-hooks/refs/heads/main/install.sh | sh

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

if ! command -v curl >/dev/null 2>&1; then
    printf '\033[0;31m[ERROR]\033[0m curl is required but was not found on PATH\n'
    exit 1
fi

TEMP_DIR="$(mktemp -d)"
RAW_BASE="https://raw.githubusercontent.com/${FIRERAVEN_HOOKS_REPO}/refs/heads/${FIRERAVEN_HOOKS_REF}"

if ! curl -fsSL "${RAW_BASE}/scripts/lib.sh" -o "${TEMP_DIR}/lib.sh"; then
    printf '\033[0;31m[ERROR]\033[0m Failed to download install library from %s\n' "$RAW_BASE/scripts/lib.sh"
    exit 1
fi

# shellcheck source=/dev/null
. "${TEMP_DIR}/lib.sh"

main() {
    info "Installing Fireraven Windsurf FireGuard hooks"
    info "Repository: ${FIRERAVEN_HOOKS_REPO} (${FIRERAVEN_HOOKS_REF})"
    info "Install directory: ${FIRERAVEN_INSTALL_DIR}"

    check_python3
    download_hook_files "$RAW_BASE"
    finalize_install
    fireraven_install_complete_message
}

main
