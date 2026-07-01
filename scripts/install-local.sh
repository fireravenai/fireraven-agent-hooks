#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
FIRERAVEN_SCRIPTS_DIR="$SCRIPT_DIR"
export FIRERAVEN_SCRIPTS_DIR

# shellcheck source=lib.sh
. "${SCRIPT_DIR}/lib.sh"

agent="${FIRERAVEN_AGENT:-windsurf}"

info "Installing from local repo: ${REPO_ROOT}"
check_python3

case "$agent" in
    all)
        copy_package_tree "$REPO_ROOT" "$(windsurf_hooks_dir)"
        mkdir -p "$(cursor_hooks_dir)" "$(claude_hooks_dir)"
        copy_package_tree "$REPO_ROOT" "$(cursor_hooks_dir)"
        copy_package_tree "$REPO_ROOT" "$(claude_hooks_dir)"
        install_all_agents
        ;;
    windsurf)
        copy_package_tree "$REPO_ROOT" "$(windsurf_hooks_dir)"
        install_windsurf
        ;;
    cursor)
        copy_package_tree "$REPO_ROOT" "$(cursor_hooks_dir)"
        install_cursor
        ;;
    claude)
        copy_package_tree "$REPO_ROOT" "$(claude_hooks_dir)"
        install_claude
        ;;
    *)
        error "Unknown agent: $agent"
        ;;
esac

fireraven_install_complete_message
