#!/usr/bin/env sh
# Fireraven agent hooks installer
# Usage: curl -fsSL https://raw.githubusercontent.com/fireravenai/fireraven-agent-hooks/refs/heads/main/install.sh | sh
#        curl ... | sh -s -- --agent all

set -e

FIRERAVEN_HOOKS_REPO="${FIRERAVEN_HOOKS_REPO:-fireravenai/fireraven-agent-hooks}"
FIRERAVEN_AGENT="${FIRERAVEN_AGENT:-windsurf}"
FIRERAVEN_PROJECT_INSTALL=0
FIRERAVEN_HOOKS_GITLAB_HOST="${FIRERAVEN_HOOKS_GITLAB_HOST:-https://gitlab.com}"

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
command -v python3 >/dev/null 2>&1 || { printf '[ERROR] python3 required\n'; exit 1; }

TEMP_DIR="$(mktemp -d)"

_urlencode() {
    python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$1"
}

# Bootstrap lib.sh from the same channel we will install from.
if [ -n "${FIRERAVEN_HOOKS_GITLAB_PROJECT:-}" ]; then
    _host="${FIRERAVEN_HOOKS_GITLAB_HOST%/}"
    _ref="${FIRERAVEN_HOOKS_REF:-dev}"
    [ -n "${FIRERAVEN_HOOKS_TOKEN:-}" ] || { printf '[ERROR] FIRERAVEN_HOOKS_TOKEN required for GitLab\n'; exit 1; }
    _lib_url="${_host}/api/v4/projects/$(_urlencode "$FIRERAVEN_HOOKS_GITLAB_PROJECT")/repository/files/$(_urlencode scripts/lib.sh)/raw?ref=${_ref}"
    curl -fsSL -H "PRIVATE-TOKEN: ${FIRERAVEN_HOOKS_TOKEN}" "$_lib_url" -o "${TEMP_DIR}/lib.sh" || exit 1
elif [ -n "${FIRERAVEN_HOOKS_RAW_BASE:-}" ]; then
    case "${FIRERAVEN_HOOKS_RAW_BASE}" in
        *gitlab*"/-/raw/"*|*"/-/raw/"*)
            [ -n "${FIRERAVEN_HOOKS_TOKEN:-}" ] || { printf '[ERROR] FIRERAVEN_HOOKS_TOKEN required for private GitLab\n'; exit 1; }
            # Parse …/group/proj/-/raw/ref then fetch lib via API (/-/raw returns 403 on private).
            _parsed="$(python3 -c '
import re, sys
u = sys.argv[1].rstrip("/")
m = re.match(r"^(https?://[^/]+)/(.+)/-/raw/([^/]+)$", u)
if not m:
    sys.exit(1)
print(m.group(1)); print(m.group(2)); print(m.group(3))
' "${FIRERAVEN_HOOKS_RAW_BASE%/}")" || { printf '[ERROR] bad GitLab RAW_BASE\n'; exit 1; }
            export FIRERAVEN_HOOKS_GITLAB_HOST="$(printf '%s\n' "$_parsed" | sed -n '1p')"
            export FIRERAVEN_HOOKS_GITLAB_PROJECT="$(printf '%s\n' "$_parsed" | sed -n '2p')"
            export FIRERAVEN_HOOKS_REF="$(printf '%s\n' "$_parsed" | sed -n '3p')"
            unset FIRERAVEN_HOOKS_RAW_BASE
            _host="${FIRERAVEN_HOOKS_GITLAB_HOST%/}"
            _lib_url="${_host}/api/v4/projects/$(_urlencode "$FIRERAVEN_HOOKS_GITLAB_PROJECT")/repository/files/$(_urlencode scripts/lib.sh)/raw?ref=${FIRERAVEN_HOOKS_REF}"
            curl -fsSL -H "PRIVATE-TOKEN: ${FIRERAVEN_HOOKS_TOKEN}" "$_lib_url" -o "${TEMP_DIR}/lib.sh" || exit 1
            ;;
        *)
            curl -fsSL "${FIRERAVEN_HOOKS_RAW_BASE%/}/scripts/lib.sh" -o "${TEMP_DIR}/lib.sh" || exit 1
            ;;
    esac
else
    _ref="${FIRERAVEN_HOOKS_REF:-main}"
    curl -fsSL "https://raw.githubusercontent.com/${FIRERAVEN_HOOKS_REPO}/refs/heads/${_ref}/scripts/lib.sh" \
        -o "${TEMP_DIR}/lib.sh" || exit 1
fi

# shellcheck source=/dev/null
. "${TEMP_DIR}/lib.sh"
resolve_channel
require_gitlab_token
download_merge_scripts "$TEMP_DIR"
FIRERAVEN_SCRIPTS_DIR="$TEMP_DIR"
export FIRERAVEN_SCRIPTS_DIR

info "Installing Fireraven agent hooks (${FIRERAVEN_AGENT})"
if [ "$CHANNEL" = "gitlab_api" ]; then
    info "Channel: gitlab_api project=${GITLAB_PROJECT} ref=${GITLAB_REF}"
else
    info "Channel: github raw_base=${RAW_BASE}"
fi
check_python3

_install_tree() {
    tree_dest="$1"
    agents_meta="$2"
    download_package_tree "$tree_dest"
    write_install_meta "$tree_dest" "$agents_meta"
}

case "$FIRERAVEN_AGENT" in
    all)
        _install_tree "$(windsurf_hooks_dir)" "all"
        _install_tree "$(cursor_hooks_dir)" "all"
        _install_tree "$(claude_hooks_dir)" "all"
        _install_tree "$(devin_hooks_dir)" "all"
        _install_tree "$(github_copilot_hooks_dir)" "all"
        install_all_agents
        ;;
    windsurf)
        _install_tree "$(windsurf_hooks_dir)" "windsurf"
        install_windsurf
        ;;
    cursor)
        _install_tree "$(cursor_hooks_dir)" "cursor"
        install_cursor
        ;;
    claude)
        _install_tree "$(claude_hooks_dir)" "claude"
        install_claude
        ;;
    devin)
        _install_tree "$(devin_hooks_dir)" "devin"
        install_devin
        ;;
    github-copilot)
        if [ "$FIRERAVEN_PROJECT_INSTALL" = "1" ]; then
            _install_tree "$(github_copilot_project_hooks_dir)" "github-copilot"
            install_github_copilot_project
        else
            _install_tree "$(github_copilot_hooks_dir)" "github-copilot"
            install_github_copilot
        fi
        ;;
    copilot)
        info "See adapters/copilot/ in the repository for Copilot Studio topics"
        ;;
    *)
        error "Unknown --agent value: $FIRERAVEN_AGENT (use windsurf, cursor, claude, devin, github-copilot, copilot, all)"
        ;;
esac

fireraven_install_complete_message
