#!/usr/bin/env bash
# Install Fireraven Windsurf hooks from a local clone (development).

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"

# shellcheck source=scripts/lib.sh
. "${REPO_ROOT}/scripts/lib.sh"

main() {
    info "Installing Fireraven Windsurf FireGuard hooks (local)"
    info "Source: ${REPO_ROOT}/hooks"
    info "Install directory: ${FIRERAVEN_INSTALL_DIR}"

    check_python3
    copy_hook_files_from_dir "${REPO_ROOT}/hooks"
    finalize_install
    fireraven_install_complete_message
}

main "$@"
