#!/usr/bin/env sh
# Shared install/uninstall helpers for Fireraven agent hooks.

FIRERAVEN_HOOKS_REPO="${FIRERAVEN_HOOKS_REPO:-fireravenai/fireraven-agent-hooks}"
# REF default is channel-specific (main for GitHub, dev for GitLab) — set in resolve_channel.
FIRERAVEN_AGENT="${FIRERAVEN_AGENT:-windsurf}"
FIRERAVEN_HOOKS_GITLAB_HOST="${FIRERAVEN_HOOKS_GITLAB_HOST:-https://gitlab.com}"

# Channel globals set by resolve_channel: CHANNEL, RAW_BASE, GITLAB_HOST, GITLAB_PROJECT, GITLAB_REF
CHANNEL="github"
RAW_BASE=""
GITLAB_HOST=""
GITLAB_PROJECT=""
GITLAB_REF=""

urlencode() {
    python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$1"
}

# Parse https://gitlab.com/group/proj/-/raw/ref → project + ref (stdout: project\nref\nhost)
parse_gitlab_raw_base() {
    raw="$1"
    python3 -c '
import re, sys
u = sys.argv[1].rstrip("/")
m = re.match(
    r"^(https?://[^/]+)/(.+)/-/raw/([^/]+)$",
    u,
)
if not m:
    sys.exit(1)
host, project, ref = m.group(1), m.group(2), m.group(3)
print(host)
print(project)
print(ref)
' "$raw"
}

resolve_channel() {
    CHANNEL="github"
    RAW_BASE=""
    GITLAB_HOST=""
    GITLAB_PROJECT=""
    GITLAB_REF=""

    if [ -n "${FIRERAVEN_HOOKS_GITLAB_PROJECT:-}" ]; then
        CHANNEL="gitlab_api"
        GITLAB_HOST="${FIRERAVEN_HOOKS_GITLAB_HOST%/}"
        GITLAB_PROJECT="${FIRERAVEN_HOOKS_GITLAB_PROJECT}"
        # When only project is set, prefer dev (GitLab testing). Explicit FIRERAVEN_HOOKS_REF wins.
        GITLAB_REF="${FIRERAVEN_HOOKS_REF:-dev}"
        return 0
    fi

    if [ -n "${FIRERAVEN_HOOKS_RAW_BASE:-}" ]; then
        case "${FIRERAVEN_HOOKS_RAW_BASE}" in
            *gitlab*"/-/raw/"*|*"/-/raw/"*)
                parsed="$(parse_gitlab_raw_base "${FIRERAVEN_HOOKS_RAW_BASE%/}" 2>/dev/null)" || {
                    error "Could not parse GitLab RAW_BASE (expected …/group/project/-/raw/<ref>)"
                }
                CHANNEL="gitlab_api"
                GITLAB_HOST="$(printf '%s\n' "$parsed" | sed -n '1p')"
                GITLAB_PROJECT="$(printf '%s\n' "$parsed" | sed -n '2p')"
                GITLAB_REF="$(printf '%s\n' "$parsed" | sed -n '3p')"
                return 0
                ;;
            *)
                CHANNEL="github"
                RAW_BASE="${FIRERAVEN_HOOKS_RAW_BASE%/}"
                FIRERAVEN_HOOKS_REF="${FIRERAVEN_HOOKS_REF:-main}"
                return 0
                ;;
        esac
    fi

    CHANNEL="github"
    FIRERAVEN_HOOKS_REF="${FIRERAVEN_HOOKS_REF:-main}"
    RAW_BASE="https://raw.githubusercontent.com/${FIRERAVEN_HOOKS_REPO}/refs/heads/${FIRERAVEN_HOOKS_REF}"
}

require_gitlab_token() {
    if [ "$CHANNEL" = "gitlab_api" ] && [ -z "${FIRERAVEN_HOOKS_TOKEN:-}" ]; then
        error "FIRERAVEN_HOOKS_TOKEN is required for private GitLab installs (PRIVATE-TOKEN)"
    fi
}

file_url() {
    # Prefixed names: POSIX sh has no local; avoid clobbering callers' path/dest.
    _fr_path="$1"
    if [ "$CHANNEL" = "gitlab_api" ]; then
        enc_project="$(urlencode "$GITLAB_PROJECT")"
        enc_path="$(urlencode "$_fr_path")"
        printf '%s/api/v4/projects/%s/repository/files/%s/raw?ref=%s' \
            "$GITLAB_HOST" "$enc_project" "$enc_path" "$GITLAB_REF"
        return 0
    fi
    printf '%s/%s' "${RAW_BASE%/}" "$_fr_path"
}

download_file() {
    # Prefixed names: POSIX sh has no local; avoid clobbering callers' path/dest.
    _fr_path="$1"
    _fr_dest="$2"
    _fr_url="$(file_url "$_fr_path")"
    mkdir -p "$(dirname "$_fr_dest")"
    info "Downloading ${_fr_path}"
    if [ "$CHANNEL" = "gitlab_api" ]; then
        curl -fsSL -H "PRIVATE-TOKEN: ${FIRERAVEN_HOOKS_TOKEN}" "$_fr_url" -o "$_fr_dest" \
            || error "Failed to download $_fr_path"
    else
        curl -fsSL "$_fr_url" -o "$_fr_dest" || error "Failed to download $_fr_url"
    fi
}

# Compat: resolve_raw_base still used by older callers / local install messaging
resolve_raw_base() {
    resolve_channel
    if [ "$CHANNEL" = "gitlab_api" ]; then
        printf '%s' "$GITLAB_HOST"
        return 0
    fi
    printf '%s' "$RAW_BASE"
}

write_install_meta() {
    dest_dir="$1"
    agents="$2"
    mkdir -p "$dest_dir"
    meta_path="${dest_dir}/install_meta.json"
    esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
    esc_agents="$(esc "$agents")"
    esc_channel="$(esc "$CHANNEL")"
    esc_base="$(esc "$RAW_BASE")"
    esc_repo="$(esc "${FIRERAVEN_HOOKS_REPO}")"
    esc_ref="$(esc "${FIRERAVEN_HOOKS_REF}")"
    esc_host="$(esc "$GITLAB_HOST")"
    esc_project="$(esc "$GITLAB_PROJECT")"
    esc_gref="$(esc "$GITLAB_REF")"
    if [ "$CHANNEL" = "gitlab_api" ]; then
        printf '{\n  "agents": "%s",\n  "channel": "%s",\n  "gitlab_host": "%s",\n  "project": "%s",\n  "ref": "%s",\n  "raw_base": ""\n}\n' \
            "$esc_agents" "$esc_channel" "$esc_host" "$esc_project" "$esc_gref" >"$meta_path"
    else
        printf '{\n  "agents": "%s",\n  "channel": "%s",\n  "raw_base": "%s",\n  "repo": "%s",\n  "ref": "%s"\n}\n' \
            "$esc_agents" "$esc_channel" "$esc_base" "$esc_repo" "$esc_ref" >"$meta_path"
    fi
}

ensure_hooks_token_in_config() {
    dest_dir="$1"
    config_env="${dest_dir}/config.env"
    [ -f "$config_env" ] || return 0
    [ -n "${FIRERAVEN_HOOKS_TOKEN:-}" ] || return 0
    if grep -q '^FIRERAVEN_HOOKS_TOKEN=' "$config_env" 2>/dev/null; then
        return 0
    fi
    printf '\nFIRERAVEN_HOOKS_TOKEN=%s\n' "$FIRERAVEN_HOOKS_TOKEN" >>"$config_env"
    chmod 600 "$config_env"
    info "Wrote FIRERAVEN_HOOKS_TOKEN into $config_env for update checks"
}

WINDSURF_INSTALL_DIR="${FIRERAVEN_INSTALL_DIR:-$HOME/.codeium/windsurf}"
CURSOR_INSTALL_DIR="${FIRERAVEN_CURSOR_INSTALL_DIR:-$HOME/.cursor}"
CLAUDE_INSTALL_DIR="${FIRERAVEN_CLAUDE_INSTALL_DIR:-$HOME/.claude}"
GITHUB_COPILOT_INSTALL_DIR="${FIRERAVEN_GITHUB_COPILOT_INSTALL_DIR:-$HOME/.copilot}"
DEVIN_INSTALL_DIR="${FIRERAVEN_DEVIN_INSTALL_DIR:-$HOME/.config/devin}"

WINDSURF_SCRIPT="windsurf_guardrail.py"
CURSOR_SCRIPT="cursor_guardrail.py"
CLAUDE_SCRIPT="claude_guardrail.py"
GITHUB_COPILOT_SCRIPT="github_copilot_guardrail.py"
DEVIN_SCRIPT="devin_guardrail.py"
MARKER="fireraven"
FIRERAVEN_ENTRY_PATTERN="fireraven|windsurf_guardrail.py|cursor_guardrail.py|run_cursor_guardrail.ps1|claude_guardrail.py|fireraven_input_guardrail.py|github_copilot_guardrail.py|run_github_copilot_guardrail.ps1|devin_guardrail.py"

WINDSURF_PRE_EVENTS="pre_user_prompt pre_run_command pre_mcp_tool_use pre_write_code pre_read_code"
WINDSURF_POST_EVENTS="post_cascade_response post_write_code"

CURSOR_EVENTS="beforeSubmitPrompt beforeShellExecution beforeMCPExecution beforeReadFile preToolUse subagentStart afterFileEdit"
GITHUB_COPILOT_EVENTS="userPromptSubmitted preToolUse postToolUse"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { printf "${GREEN}[INFO]${NC} %s\n" "$1"; }
warn() { printf "${YELLOW}[WARN]${NC} %s\n" "$1"; }
error() { printf "${RED}[ERROR]${NC} %s\n" "$1"; exit 1; }

check_python3() {
    command -v python3 >/dev/null 2>&1 || error "python3 is required but was not found on PATH"
}

merge_hooks_scripts_dir() {
    if [ -n "${FIRERAVEN_SCRIPTS_DIR:-}" ] && [ -f "${FIRERAVEN_SCRIPTS_DIR}/merge_hooks_config.py" ]; then
        printf '%s' "$FIRERAVEN_SCRIPTS_DIR"
        return 0
    fi
    error "Missing merge_hooks_config.py (set FIRERAVEN_SCRIPTS_DIR)"
}

download_merge_scripts() {
    dest_dir="$1"
    mkdir -p "$dest_dir"
    for file in jsonc_modify.py merge_hooks_config.py; do
        download_file "scripts/${file}" "${dest_dir}/${file}"
    done
}

run_merge_hooks_config() {
    scripts_dir="$(merge_hooks_scripts_dir)"
    python3 "${scripts_dir}/merge_hooks_config.py" "$@"
}

windsurf_hooks_dir() { printf '%s/hooks' "$WINDSURF_INSTALL_DIR"; }
cursor_hooks_dir() { printf '%s/hooks' "$CURSOR_INSTALL_DIR"; }
claude_hooks_dir() { printf '%s/hooks' "$CLAUDE_INSTALL_DIR"; }
devin_hooks_dir() { printf '%s/hooks' "$DEVIN_INSTALL_DIR"; }
github_copilot_hooks_dir() { printf '%s/hooks/fireraven' "$GITHUB_COPILOT_INSTALL_DIR"; }
github_copilot_hooks_json() { printf '%s/hooks/fireraven-fireguard.json' "$GITHUB_COPILOT_INSTALL_DIR"; }
github_copilot_project_hooks_dir() { printf '%s/.github/hooks/fireraven' "$(pwd)"; }
github_copilot_project_hooks_json() { printf '%s/.github/hooks/fireraven-fireguard.json' "$(pwd)"; }

setup_config_env() {
    dest_dir="$1"
    config_env="${dest_dir}/config.env"
    example_env="${dest_dir}/config.example.env"

    if [ -f "$config_env" ]; then
        info "Keeping existing config: $config_env"
        ensure_hooks_token_in_config "$dest_dir"
        return 0
    fi
    [ -f "$example_env" ] || error "Missing config template: $example_env"
    cp "$example_env" "$config_env"
    chmod 600 "$config_env"
    warn "Created $config_env — add FIRERAVEN_GUARDRAILS_API_KEY and FIRERAVEN_PROJECT_ID"
    ensure_hooks_token_in_config "$dest_dir"
}

copy_package_tree() {
    src_root="$1"
    dest_dir="$2"
    mkdir -p "$dest_dir"

    rm -rf "${dest_dir}/core" "${dest_dir}/adapters" "${dest_dir}/assets"
    cp -R "${src_root}/core" "${src_root}/adapters" "${dest_dir}/"
    if [ -d "${src_root}/assets" ]; then
        cp -R "${src_root}/assets" "${dest_dir}/"
    fi

    for file in windsurf_guardrail.py cursor_guardrail.py run_cursor_guardrail.ps1 claude_guardrail.py \
        github_copilot_guardrail.py run_github_copilot_guardrail.ps1 \
        devin_guardrail.py \
        fireraven_input_guardrail.py _bootstrap.py config.example.env README.md; do
        if [ -f "${src_root}/hooks/${file}" ]; then
            cp "${src_root}/hooks/${file}" "${dest_dir}/${file}"
        fi
    done

    if [ -f "${src_root}/VERSION" ]; then
        cp "${src_root}/VERSION" "${dest_dir}/VERSION"
    fi

    chmod +x "${dest_dir}/"*.py 2>/dev/null || true
}

download_package_tree() {
    dest_dir="$1"
    mkdir -p "$dest_dir"

    for path in \
        VERSION \
        core/__init__.py core/config.py core/session_store.py core/fireraven_client.py \
        core/serializers.py core/guardrail.py core/human_override.py core/hook_io.py \
        core/unavailable_notice.py core/secured_notice.py core/update_check.py \
        adapters/__init__.py adapters/windsurf.py adapters/cursor.py adapters/claude.py \
        adapters/github_copilot.py adapters/devin.py \
        assets/fireraven.ico; do
        download_file "$path" "${dest_dir}/${path}"
    done

    for file in _bootstrap.py windsurf_guardrail.py cursor_guardrail.py run_cursor_guardrail.ps1 claude_guardrail.py \
        github_copilot_guardrail.py run_github_copilot_guardrail.ps1 \
        devin_guardrail.py \
        fireraven_input_guardrail.py config.example.env README.md; do
        download_file "hooks/${file}" "${dest_dir}/${file}"
    done
    chmod +x "${dest_dir}/"*.py 2>/dev/null || true
}

merge_windsurf_hooks_json() {
    hooks_json="${WINDSURF_INSTALL_DIR}/hooks.json"
    script_path="$(windsurf_hooks_dir)/${WINDSURF_SCRIPT}"
    events="${WINDSURF_PRE_EVENTS} ${WINDSURF_POST_EVENTS}"

    run_merge_hooks_config merge-windsurf \
        --path "$hooks_json" \
        --script-path "$script_path" \
        --events "$events" \
        --owned-pattern "$FIRERAVEN_ENTRY_PATTERN"
}

merge_cursor_hooks_json() {
    hooks_json="${CURSOR_INSTALL_DIR}/hooks.json"
    script_path="$(cursor_hooks_dir)/${CURSOR_SCRIPT}"

    run_merge_hooks_config merge-cursor \
        --path "$hooks_json" \
        --script-path "$script_path" \
        --events "$CURSOR_EVENTS" \
        --owned-pattern "$FIRERAVEN_ENTRY_PATTERN"
}

merge_claude_settings_json() {
    settings_json="${CLAUDE_INSTALL_DIR}/settings.json"
    script_path="$(claude_hooks_dir)/${CLAUDE_SCRIPT}"

    run_merge_hooks_config merge-claude \
        --path "$settings_json" \
        --script-path "$script_path"
}

merge_devin_config_json() {
    config_json="${DEVIN_INSTALL_DIR}/config.json"
    script_path="$(devin_hooks_dir)/${DEVIN_SCRIPT}"

    run_merge_hooks_config merge-devin \
        --path "$config_json" \
        --script-path "$script_path"
}

merge_github_copilot_hooks_json() {
    target="${1:-user}"
    events="${GITHUB_COPILOT_EVENTS}"

    if [ "$target" = "project" ]; then
        hooks_json="$(github_copilot_project_hooks_json)"
        script_path=".github/hooks/fireraven/${GITHUB_COPILOT_SCRIPT}"
    else
        hooks_json="$(github_copilot_hooks_json)"
        script_path="$(github_copilot_hooks_dir)/${GITHUB_COPILOT_SCRIPT}"
    fi

    bash_cmd="python3 ${script_path}"
    ps_cmd="py -3 ${script_path}"

    run_merge_hooks_config merge-github-copilot \
        --path "$hooks_json" \
        --script-path "$script_path" \
        --events "$events" \
        --owned-pattern "$FIRERAVEN_ENTRY_PATTERN" \
        --bash-command "$bash_cmd" \
        --powershell-command "$ps_cmd" \
        --cwd "."
}

install_windsurf() {
    info "Installing Windsurf hooks to $(windsurf_hooks_dir)"
    setup_config_env "$(windsurf_hooks_dir)"
    merge_windsurf_hooks_json
    info "Registered Windsurf hooks in ${WINDSURF_INSTALL_DIR}/hooks.json"
}

install_cursor() {
    info "Installing Cursor hooks to $(cursor_hooks_dir)"
    setup_config_env "$(cursor_hooks_dir)"
    merge_cursor_hooks_json
    info "Registered Cursor hooks in ${CURSOR_INSTALL_DIR}/hooks.json"
}

install_claude() {
    info "Installing Claude Code hooks to $(claude_hooks_dir)"
    setup_config_env "$(claude_hooks_dir)"
    merge_claude_settings_json
    info "Registered Claude hooks in ${CLAUDE_INSTALL_DIR}/settings.json"
}

install_devin() {
    info "Installing Devin Local hooks to $(devin_hooks_dir)"
    setup_config_env "$(devin_hooks_dir)"
    merge_devin_config_json
    info "Registered Devin Local hooks in ${DEVIN_INSTALL_DIR}/config.json"
}

install_github_copilot() {
    info "Installing GitHub Copilot hooks to $(github_copilot_hooks_dir)"
    setup_config_env "$(github_copilot_hooks_dir)"
    merge_github_copilot_hooks_json user
    info "Registered GitHub Copilot hooks in $(github_copilot_hooks_json)"
}

install_github_copilot_project() {
    info "Installing GitHub Copilot project hooks to $(github_copilot_project_hooks_dir)"
    setup_config_env "$(github_copilot_project_hooks_dir)"
    merge_github_copilot_hooks_json project
    info "Registered GitHub Copilot hooks in $(github_copilot_project_hooks_json)"
    warn "Commit .github/hooks/fireraven-fireguard.json and .github/hooks/fireraven/ to your default branch for Copilot cloud agent"
}

install_agent() {
    agent="$1"
    case "$agent" in
        windsurf) install_windsurf ;;
        cursor) install_cursor ;;
        claude) install_claude ;;
        devin) install_devin ;;
        github-copilot)
            if [ "${FIRERAVEN_PROJECT_INSTALL:-0}" = "1" ]; then
                install_github_copilot_project
            else
                install_github_copilot
            fi
            ;;
        copilot) info "Copilot Studio uses connector topics in adapters/copilot/ (see README)" ;;
        *) error "Unknown agent: $agent" ;;
    esac
}

install_all_agents() {
    install_windsurf
    install_cursor
    install_claude
    install_devin
    install_github_copilot
    info "Copilot Studio: see adapters/copilot/README.md for Studio setup"
}

remove_agent_hooks() {
    agent="$1"
    windsurf_events="${WINDSURF_PRE_EVENTS} ${WINDSURF_POST_EVENTS}"

    case "$agent" in
        windsurf|all)
            run_merge_hooks_config scrub-windsurf \
                --path "${WINDSURF_INSTALL_DIR}/hooks.json" \
                --events "$windsurf_events" \
                --owned-pattern "$FIRERAVEN_ENTRY_PATTERN"
            ;;
    esac
    case "$agent" in
        cursor|all)
            run_merge_hooks_config scrub-cursor \
                --path "${CURSOR_INSTALL_DIR}/hooks.json" \
                --events "$CURSOR_EVENTS" \
                --owned-pattern "$FIRERAVEN_ENTRY_PATTERN"
            ;;
    esac
    case "$agent" in
        claude|all)
            run_merge_hooks_config scrub-claude \
                --path "${CLAUDE_INSTALL_DIR}/settings.json" \
                --owned-pattern "$FIRERAVEN_ENTRY_PATTERN"
            ;;
    esac
    case "$agent" in
        devin|all)
            run_merge_hooks_config scrub-devin \
                --path "${DEVIN_INSTALL_DIR}/config.json" \
                --owned-pattern "$FIRERAVEN_ENTRY_PATTERN"
            ;;
    esac
    case "$agent" in
        github-copilot|all)
            if [ -f "$(github_copilot_hooks_json)" ]; then
                run_merge_hooks_config scrub-github-copilot \
                    --path "$(github_copilot_hooks_json)" \
                    --events "$GITHUB_COPILOT_EVENTS" \
                    --owned-pattern "$FIRERAVEN_ENTRY_PATTERN"
            fi
            if [ "${FIRERAVEN_PROJECT_INSTALL:-0}" = "1" ] && [ -f "$(github_copilot_project_hooks_json)" ]; then
                run_merge_hooks_config scrub-github-copilot \
                    --path "$(github_copilot_project_hooks_json)" \
                    --events "$GITHUB_COPILOT_EVENTS" \
                    --owned-pattern "$FIRERAVEN_ENTRY_PATTERN"
            fi
            ;;
    esac
}

fireraven_install_complete_message() {
    echo ""
    warn "Edit config.env in each installed hooks/ directory with FIRERAVEN_* credentials"
    info "Restart your IDE(s) to load hook configuration"
    echo ""
}
