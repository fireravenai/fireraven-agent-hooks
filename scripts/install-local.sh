#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
FIRERAVEN_SCRIPTS_DIR="$SCRIPT_DIR"
export FIRERAVEN_SCRIPTS_DIR

# shellcheck source=lib.sh
. "${SCRIPT_DIR}/lib.sh"

agent="${FIRERAVEN_AGENT:-windsurf}"
project_install="${FIRERAVEN_PROJECT_INSTALL:-0}"

while [ $# -gt 0 ]; do
    case "$1" in
        --agent) agent="$2"; shift 2 ;;
        --project) project_install=1; shift ;;
        *) shift ;;
    esac
done

export FIRERAVEN_PROJECT_INSTALL="$project_install"

info "Installing from local repo: ${REPO_ROOT}"
check_python3

case "$agent" in
    all)
        copy_package_tree "$REPO_ROOT" "$(windsurf_hooks_dir)"
        mkdir -p "$(cursor_hooks_dir)" "$(claude_hooks_dir)" "$(github_copilot_hooks_dir)"
        copy_package_tree "$REPO_ROOT" "$(cursor_hooks_dir)"
        copy_package_tree "$REPO_ROOT" "$(claude_hooks_dir)"
        copy_package_tree "$REPO_ROOT" "$(github_copilot_hooks_dir)"
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
    github-copilot)
        if [ "$project_install" = "1" ]; then
            copy_package_tree "$REPO_ROOT" "$(github_copilot_project_hooks_dir)"
            install_github_copilot_project
        else
            copy_package_tree "$REPO_ROOT" "$(github_copilot_hooks_dir)"
            install_github_copilot
        fi
        ;;
    copilot)
        info "See adapters/copilot/ for Copilot Studio topics"
        ;;
    *)
        error "Unknown agent: $agent"
        ;;
esac

fireraven_install_complete_message
