#!/usr/bin/env sh
# Shared install/uninstall helpers for Fireraven Windsurf hooks.

FIRERAVEN_HOOKS_REPO="${FIRERAVEN_HOOKS_REPO:-fireravenai/windsurf-fireguard-hooks}"
FIRERAVEN_HOOKS_REF="${FIRERAVEN_HOOKS_REF:-main}"
FIRERAVEN_INSTALL_DIR="${FIRERAVEN_INSTALL_DIR:-$HOME/.codeium/windsurf}"

HOOK_SCRIPT_NAME="fireraven_input_guardrail.py"
HOOK_FILES="fireraven_input_guardrail.py config.example.env README.md"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() {
    printf "${GREEN}[INFO]${NC} %s\n" "$1"
}

warn() {
    printf "${YELLOW}[WARN]${NC} %s\n" "$1"
}

error() {
    printf "${RED}[ERROR]${NC} %s\n" "$1"
    exit 1
}

check_python3() {
    if ! command -v python3 >/dev/null 2>&1; then
        error "python3 is required but was not found on PATH"
    fi
}

hooks_dir() {
    printf '%s/hooks' "$FIRERAVEN_INSTALL_DIR"
}

hooks_json_path() {
    printf '%s/hooks.json' "$FIRERAVEN_INSTALL_DIR"
}

hook_script_path() {
    printf '%s/%s' "$(hooks_dir)" "$HOOK_SCRIPT_NAME"
}

setup_config_env() {
    config_env="$(hooks_dir)/config.env"
    example_env="$(hooks_dir)/config.example.env"

    if [ -f "$config_env" ]; then
        info "Keeping existing config: $config_env"
        return 0
    fi

    if [ ! -f "$example_env" ]; then
        error "Missing config template: $example_env"
    fi

    cp "$example_env" "$config_env"
    chmod 600 "$config_env"
    warn "Created $config_env — add your FIRERAVEN_GUARDRAILS_API_KEY and FIRERAVEN_PROJECT_ID"
}

merge_hooks_json() {
    hooks_json="$(hooks_json_path)"
    script_path="$(hook_script_path)"

    python3 - "$hooks_json" "$script_path" <<'PY'
import json
import os
import sys

hooks_json_path, script_path = sys.argv[1:3]
marker = "fireraven_input_guardrail.py"
hook_command = f"python3 {script_path}"
new_entry = {"command": hook_command}

if os.path.isfile(hooks_json_path) and os.path.getsize(hooks_json_path) > 0:
    with open(hooks_json_path, encoding="utf-8") as handle:
        data = json.load(handle)
else:
    data = {}

hooks = data.setdefault("hooks", {})
entries = hooks.setdefault("pre_user_prompt", [])
filtered = [entry for entry in entries if marker not in entry.get("command", "")]
filtered.append(new_entry)
hooks["pre_user_prompt"] = filtered

os.makedirs(os.path.dirname(hooks_json_path), exist_ok=True)
with open(hooks_json_path, "w", encoding="utf-8") as handle:
    json.dump(data, handle, indent=2)
    handle.write("\n")
PY
}

remove_hooks_json_entry() {
    hooks_json="$(hooks_json_path)"

    if [ ! -f "$hooks_json" ]; then
        return 0
    fi

    python3 - "$hooks_json" <<'PY'
import json
import os
import sys

hooks_json_path = sys.argv[1]
marker = "fireraven_input_guardrail.py"

with open(hooks_json_path, encoding="utf-8") as handle:
    data = json.load(handle)

hooks = data.get("hooks", {})
entries = hooks.get("pre_user_prompt", [])
filtered = [entry for entry in entries if marker not in entry.get("command", "")]

if filtered:
    hooks["pre_user_prompt"] = filtered
elif "pre_user_prompt" in hooks:
    del hooks["pre_user_prompt"]

if not hooks:
    os.remove(hooks_json_path)
else:
    data["hooks"] = hooks
    with open(hooks_json_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
PY
}

finalize_install() {
    chmod +x "$(hook_script_path)"
    setup_config_env
    merge_hooks_json
}

copy_hook_files_from_dir() {
    src_dir="$1"
    dest_dir="$(hooks_dir)"
    mkdir -p "$dest_dir"

    for file in $HOOK_FILES; do
        if [ ! -f "$src_dir/$file" ]; then
            error "Missing source file: $src_dir/$file"
        fi
        cp "$src_dir/$file" "$dest_dir/$file"
    done
}

download_hook_files() {
    raw_base="$1"
    dest_dir="$(hooks_dir)"
    mkdir -p "$dest_dir"

    for file in $HOOK_FILES; do
        url="${raw_base}/hooks/${file}"
        info "Downloading $file"
        if ! curl -fsSL "$url" -o "$dest_dir/$file"; then
            error "Failed to download $url"
        fi
    done
}

fireraven_install_complete_message() {
    echo ""
    info "Installed to $(hooks_dir)/"
    info "Registered hook in $(hooks_json_path)"
    warn "Edit $(hooks_dir)/config.env with your FIRERAVEN_* credentials if you have not already"
    info "Restart Windsurf to load hooks.json"
    echo ""
}
