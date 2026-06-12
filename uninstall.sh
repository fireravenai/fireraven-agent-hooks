#!/usr/bin/env sh
# Fireraven agent hooks uninstaller

set -e

FIRERAVEN_HOOKS_REPO="${FIRERAVEN_HOOKS_REPO:-fireravenai/fireraven-agent-hooks}"
FIRERAVEN_HOOKS_REF="${FIRERAVEN_HOOKS_REF:-main}"
FIRERAVEN_AGENT="${FIRERAVEN_AGENT:-all}"

while [ $# -gt 0 ]; do
    case "$1" in
        --agent) FIRERAVEN_AGENT="$2"; shift 2 ;;
        *) shift ;;
    esac
done

load_lib() {
    SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd || true)"
    if [ -n "$SCRIPT_DIR" ] && [ -f "${SCRIPT_DIR}/scripts/lib.sh" ]; then
        # shellcheck source=scripts/lib.sh
        . "${SCRIPT_DIR}/scripts/lib.sh"
        return 0
    fi
    TEMP_DIR="$(mktemp -d)"
    RAW_BASE="https://raw.githubusercontent.com/${FIRERAVEN_HOOKS_REPO}/refs/heads/${FIRERAVEN_HOOKS_REF}"
    curl -fsSL "${RAW_BASE}/scripts/lib.sh" -o "${TEMP_DIR}/lib.sh"
    # shellcheck source=/dev/null
    . "${TEMP_DIR}/lib.sh"
}

load_lib
info "Uninstalling Fireraven hooks (agent=${FIRERAVEN_AGENT})"
remove_agent_hooks "$FIRERAVEN_AGENT"
warn "config.env files were not removed (may contain secrets)"
info "Restart your IDE(s) to apply changes"
