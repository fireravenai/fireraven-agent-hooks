#!/usr/bin/env sh
# Fireraven agent hooks installer
# Usage: curl -fsSL https://raw.githubusercontent.com/fireravenai/fireraven-agent-hooks/refs/heads/main/install.sh | sh
#        curl ... | sh -s -- --agent all

set -e

FIRERAVEN_HOOKS_REPO="${FIRERAVEN_HOOKS_REPO:-fireravenai/fireraven-agent-hooks}"
FIRERAVEN_HOOKS_REF="${FIRERAVEN_HOOKS_REF:-main}"
FIRERAVEN_AGENT="${FIRERAVEN_AGENT:-windsurf}"
FIRERAVEN_PROJECT_INSTALL=0

while [ $# -gt 0 ]; do
    case "$1" in
        --agent)
            FIRERAVEN_AGENT="$2"
            shift 2
            ;;
        --project)
            FIRERAVEN_PROJECT_INSTALL=1
            shift
            ;;
        *)
            shift
            ;;
    esac
done

export FIRERAVEN_PROJECT_INSTALL

TEMP_DIR=""
cleanup() {
    [ -n "$TEMP_DIR" ] && [ -d "$TEMP_DIR" ] && rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

command -v curl >/dev/null 2>&1 || { printf '[ERROR] curl required\n'; exit 1; }

TEMP_DIR="$(mktemp -d)"
RAW_BASE="https://raw.githubusercontent.com/${FIRERAVEN_HOOKS_REPO}/refs/heads/${FIRERAVEN_HOOKS_REF}"

curl -fsSL "${RAW_BASE}/scripts/lib.sh" -o "${TEMP_DIR}/lib.sh" || exit 1
download_merge_scripts "$RAW_BASE" "$TEMP_DIR"
FIRERAVEN_SCRIPTS_DIR="$TEMP_DIR"
export FIRERAVEN_SCRIPTS_DIR
# shellcheck source=/dev/null
. "${TEMP_DIR}/lib.sh"

info "Installing Fireraven agent hooks (${FIRERAVEN_AGENT})"
check_python3

case "$FIRERAVEN_AGENT" in
    all)
        download_package_tree "$RAW_BASE" "$(windsurf_hooks_dir)"
        download_package_tree "$RAW_BASE" "$(cursor_hooks_dir)"
        download_package_tree "$RAW_BASE" "$(claude_hooks_dir)"
        download_package_tree "$RAW_BASE" "$(github_copilot_hooks_dir)"
        install_all_agents
        ;;
    windsurf)
        download_package_tree "$RAW_BASE" "$(windsurf_hooks_dir)"
        install_windsurf
        ;;
    cursor)
        download_package_tree "$RAW_BASE" "$(cursor_hooks_dir)"
        install_cursor
        ;;
    claude)
        download_package_tree "$RAW_BASE" "$(claude_hooks_dir)"
        install_claude
        ;;
    github-copilot)
        if [ "$FIRERAVEN_PROJECT_INSTALL" = "1" ]; then
            download_package_tree "$RAW_BASE" "$(github_copilot_project_hooks_dir)"
            install_github_copilot_project
        else
            download_package_tree "$RAW_BASE" "$(github_copilot_hooks_dir)"
            install_github_copilot
        fi
        ;;
    copilot)
        info "See adapters/copilot/ in the repository for Copilot Studio topics"
        ;;
    *)
        error "Unknown --agent value: $FIRERAVEN_AGENT (use windsurf, cursor, claude, github-copilot, copilot, all)"
        ;;
esac

fireraven_install_complete_message
