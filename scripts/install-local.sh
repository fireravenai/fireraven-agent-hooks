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

resolve_channel
if [ "$CHANNEL" = "gitlab_api" ]; then
    require_gitlab_token
    info "Install meta channel=gitlab_api project=${GITLAB_PROJECT} ref=${GITLAB_REF}"
else
    info "Install meta channel=github raw_base=${RAW_BASE}"
fi

_meta() {
    write_install_meta "$1" "$2"
}

case "$agent" in
    all)
        copy_package_tree "$REPO_ROOT" "$(windsurf_hooks_dir)"
        _meta "$(windsurf_hooks_dir)" "all"
        mkdir -p "$(cursor_hooks_dir)" "$(claude_hooks_dir)" "$(devin_hooks_dir)" "$(github_copilot_hooks_dir)"
        copy_package_tree "$REPO_ROOT" "$(cursor_hooks_dir)"
        _meta "$(cursor_hooks_dir)" "all"
        copy_package_tree "$REPO_ROOT" "$(claude_hooks_dir)"
        _meta "$(claude_hooks_dir)" "all"
        copy_package_tree "$REPO_ROOT" "$(devin_hooks_dir)"
        _meta "$(devin_hooks_dir)" "all"
        copy_package_tree "$REPO_ROOT" "$(github_copilot_hooks_dir)"
        _meta "$(github_copilot_hooks_dir)" "all"
        install_all_agents
        ;;
    windsurf)
        copy_package_tree "$REPO_ROOT" "$(windsurf_hooks_dir)"
        _meta "$(windsurf_hooks_dir)" "windsurf"
        install_windsurf
        ;;
    cursor)
        copy_package_tree "$REPO_ROOT" "$(cursor_hooks_dir)"
        _meta "$(cursor_hooks_dir)" "cursor"
        install_cursor
        ;;
    claude)
        copy_package_tree "$REPO_ROOT" "$(claude_hooks_dir)"
        _meta "$(claude_hooks_dir)" "claude"
        install_claude
        ;;
    devin)
        copy_package_tree "$REPO_ROOT" "$(devin_hooks_dir)"
        _meta "$(devin_hooks_dir)" "devin"
        install_devin
        ;;
    github-copilot)
        if [ "$project_install" = "1" ]; then
            copy_package_tree "$REPO_ROOT" "$(github_copilot_project_hooks_dir)"
            _meta "$(github_copilot_project_hooks_dir)" "github-copilot"
            install_github_copilot_project
        else
            copy_package_tree "$REPO_ROOT" "$(github_copilot_hooks_dir)"
            _meta "$(github_copilot_hooks_dir)" "github-copilot"
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
