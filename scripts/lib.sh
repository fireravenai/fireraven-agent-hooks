#!/usr/bin/env sh
# Shared install/uninstall helpers for Fireraven agent hooks.

FIRERAVEN_HOOKS_REPO="${FIRERAVEN_HOOKS_REPO:-fireravenai/fireraven-agent-hooks}"
FIRERAVEN_HOOKS_REF="${FIRERAVEN_HOOKS_REF:-main}"
FIRERAVEN_AGENT="${FIRERAVEN_AGENT:-windsurf}"

WINDSURF_INSTALL_DIR="${FIRERAVEN_INSTALL_DIR:-$HOME/.codeium/windsurf}"
CURSOR_INSTALL_DIR="${FIRERAVEN_CURSOR_INSTALL_DIR:-$HOME/.cursor}"
CLAUDE_INSTALL_DIR="${FIRERAVEN_CLAUDE_INSTALL_DIR:-$HOME/.claude}"

WINDSURF_SCRIPT="windsurf_guardrail.py"
CURSOR_SCRIPT="cursor_guardrail.py"
CLAUDE_SCRIPT="claude_guardrail.py"
MARKER="fireraven"
FIRERAVEN_ENTRY_PATTERN="fireraven|windsurf_guardrail.py|cursor_guardrail.py|run_cursor_guardrail.ps1|claude_guardrail.py|fireraven_input_guardrail.py"

WINDSURF_PRE_EVENTS="pre_user_prompt pre_run_command pre_mcp_tool_use pre_write_code pre_read_code"
WINDSURF_POST_EVENTS="post_cascade_response post_write_code"

CURSOR_EVENTS="beforeSubmitPrompt beforeShellExecution beforeMCPExecution beforeReadFile"

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
    raw_base="$1"
    dest_dir="$2"
    mkdir -p "$dest_dir"
    for file in jsonc_modify.py merge_hooks_config.py; do
        url="${raw_base}/scripts/${file}"
        info "Downloading scripts/${file}"
        curl -fsSL "$url" -o "${dest_dir}/${file}" || error "Failed to download $url"
    done
}

run_merge_hooks_config() {
    scripts_dir="$(merge_hooks_scripts_dir)"
    python3 "${scripts_dir}/merge_hooks_config.py" "$@"
}

windsurf_hooks_dir() { printf '%s/hooks' "$WINDSURF_INSTALL_DIR"; }
cursor_hooks_dir() { printf '%s/hooks' "$CURSOR_INSTALL_DIR"; }
claude_hooks_dir() { printf '%s/hooks' "$CLAUDE_INSTALL_DIR"; }

setup_config_env() {
    dest_dir="$1"
    config_env="${dest_dir}/config.env"
    example_env="${dest_dir}/config.example.env"

    if [ -f "$config_env" ]; then
        info "Keeping existing config: $config_env"
        return 0
    fi
    [ -f "$example_env" ] || error "Missing config template: $example_env"
    cp "$example_env" "$config_env"
    chmod 600 "$config_env"
    warn "Created $config_env — add FIRERAVEN_GUARDRAILS_API_KEY and FIRERAVEN_PROJECT_ID"
}

copy_package_tree() {
    src_root="$1"
    dest_dir="$2"
    mkdir -p "$dest_dir"

    rm -rf "${dest_dir}/core" "${dest_dir}/adapters"
    cp -R "${src_root}/core" "${src_root}/adapters" "${dest_dir}/"

    for file in windsurf_guardrail.py cursor_guardrail.py run_cursor_guardrail.ps1 claude_guardrail.py \
        fireraven_input_guardrail.py _bootstrap.py config.example.env README.md; do
        if [ -f "${src_root}/hooks/${file}" ]; then
            cp "${src_root}/hooks/${file}" "${dest_dir}/${file}"
        fi
    done

    chmod +x "${dest_dir}/"*.py 2>/dev/null || true
}

download_package_tree() {
    raw_base="$1"
    dest_dir="$2"
    mkdir -p "$dest_dir"

    for path in \
        core/__init__.py core/config.py core/session_store.py core/fireraven_client.py \
        core/serializers.py core/guardrail.py \
        adapters/__init__.py adapters/windsurf.py adapters/cursor.py adapters/claude.py; do
        url="${raw_base}/${path}"
        mkdir -p "${dest_dir}/$(dirname "$path")"
        info "Downloading ${path}"
        curl -fsSL "$url" -o "${dest_dir}/${path}" || error "Failed to download $url"
    done

    for file in _bootstrap.py windsurf_guardrail.py cursor_guardrail.py run_cursor_guardrail.ps1 claude_guardrail.py \
        fireraven_input_guardrail.py config.example.env README.md; do
        url="${raw_base}/hooks/${file}"
        info "Downloading hooks/${file}"
        curl -fsSL "$url" -o "${dest_dir}/${file}" || error "Failed to download $url"
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

install_agent() {
    agent="$1"
    case "$agent" in
        windsurf) install_windsurf ;;
        cursor) install_cursor ;;
        claude) install_claude ;;
        copilot) info "Copilot uses connector topics in adapters/copilot/ (no local hook install)" ;;
        *) error "Unknown agent: $agent" ;;
    esac
}

install_all_agents() {
    install_windsurf
    install_cursor
    install_claude
    info "Copilot: see adapters/copilot/README.md for Studio setup"
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
}

fireraven_install_complete_message() {
    echo ""
    warn "Edit config.env in each installed hooks/ directory with FIRERAVEN_* credentials"
    info "Restart your IDE(s) to load hook configuration"
    echo ""
}
