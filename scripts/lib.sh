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

    python3 - "$hooks_json" "$script_path" "$WINDSURF_PRE_EVENTS" "$WINDSURF_POST_EVENTS" "$FIRERAVEN_ENTRY_PATTERN" <<'PY'
import json, os, sys
hooks_json_path, script_path, pre_events, post_events, owned_pattern = sys.argv[1:6]
owned_markers = owned_pattern.split("|")
entry = {"command": f"python3 {script_path}"}

data = {}
if os.path.isfile(hooks_json_path) and os.path.getsize(hooks_json_path) > 0:
    with open(hooks_json_path, encoding="utf-8") as f:
        data = json.load(f)

hooks = data.setdefault("hooks", {})
for event in (pre_events + " " + post_events).split():
    entries = hooks.setdefault(event, [])
    hooks[event] = [
        e for e in entries if not any(marker in json.dumps(e) for marker in owned_markers)
    ]
    hooks[event].append(entry)

os.makedirs(os.path.dirname(hooks_json_path), exist_ok=True)
with open(hooks_json_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY
}

merge_cursor_hooks_json() {
    hooks_json="${CURSOR_INSTALL_DIR}/hooks.json"
    script_path="$(cursor_hooks_dir)/${CURSOR_SCRIPT}"

    python3 - "$hooks_json" "$script_path" "$CURSOR_EVENTS" "$FIRERAVEN_ENTRY_PATTERN" <<'PY'
import json, os, sys
hooks_json_path, script_path, events, owned_pattern = sys.argv[1:5]
owned_markers = owned_pattern.split("|")
entry = {"command": f"python3 {script_path}"}

data = {"version": 1, "hooks": {}}
if os.path.isfile(hooks_json_path) and os.path.getsize(hooks_json_path) > 0:
    with open(hooks_json_path, encoding="utf-8") as f:
        data = json.load(f)
data.setdefault("version", 1)
hooks = data.setdefault("hooks", {})

for event in events.split():
    entries = hooks.setdefault(event, [])
    hooks[event] = [
        e for e in entries if not any(marker in json.dumps(e) for marker in owned_markers)
    ]
    hooks[event].append(entry)

os.makedirs(os.path.dirname(hooks_json_path), exist_ok=True)
with open(hooks_json_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY
}

merge_claude_settings_json() {
    settings_json="${CLAUDE_INSTALL_DIR}/settings.json"
    script_path="$(claude_hooks_dir)/${CLAUDE_SCRIPT}"

    python3 - "$settings_json" "$script_path" <<'PY'
import json, os, sys
settings_path, script_path = sys.argv[1:3]
marker = "fireraven"
entry = {
    "matcher": ".*",
    "hooks": [{"type": "command", "command": f"python3 {script_path}"}],
}

data = {}
if os.path.isfile(settings_path) and os.path.getsize(settings_path) > 0:
    with open(settings_path, encoding="utf-8") as f:
        data = json.load(f)

hooks = data.setdefault("hooks", {})
pre = hooks.setdefault("PreToolUse", [])
pre = [e for e in pre if marker not in json.dumps(e)]
pre.append(entry)
hooks["PreToolUse"] = pre

os.makedirs(os.path.dirname(settings_path), exist_ok=True)
with open(settings_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY
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
    python3 - "$agent" "$WINDSURF_INSTALL_DIR" "$CURSOR_INSTALL_DIR" "$CLAUDE_INSTALL_DIR" "$FIRERAVEN_ENTRY_PATTERN" <<'PY'
import json, os, sys
agent, ws, cur, claude, owned_pattern = sys.argv[1:6]
owned_markers = owned_pattern.split("|")

def scrub_json(path, events):
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    hooks = data.get("hooks", {})
    for event in events:
        if event not in hooks:
            continue
        hooks[event] = [
            e for e in hooks[event] if not any(marker in json.dumps(e) for marker in owned_markers)
        ]
        if not hooks[event]:
            del hooks[event]
    if not hooks:
        os.remove(path)
    else:
        data["hooks"] = hooks
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")

if agent in ("windsurf", "all"):
    scrub_json(os.path.join(ws, "hooks.json"), [
        "pre_user_prompt","pre_run_command","pre_mcp_tool_use","pre_write_code","pre_read_code",
        "post_cascade_response","post_write_code"])
if agent in ("cursor", "all"):
    scrub_json(os.path.join(cur, "hooks.json"), [
        "beforeSubmitPrompt","beforeShellExecution","beforeMCPExecution","beforeReadFile"])
if agent in ("claude", "all"):
    path = os.path.join(claude, "settings.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        hooks = data.get("hooks", {})
        pre = hooks.get("PreToolUse", [])
        pre = [e for e in pre if not any(marker in json.dumps(e) for marker in owned_markers)]
        if pre:
            hooks["PreToolUse"] = pre
        elif "PreToolUse" in hooks:
            del hooks["PreToolUse"]
        if not hooks.get("hooks") and not hooks:
            if not data.get("hooks"):
                pass
        data["hooks"] = hooks
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
PY
}

fireraven_install_complete_message() {
    echo ""
    warn "Edit config.env in each installed hooks/ directory with FIRERAVEN_* credentials"
    info "Restart your IDE(s) to load hook configuration"
    echo ""
}
