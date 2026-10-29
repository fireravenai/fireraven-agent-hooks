#!/usr/bin/env sh
# Regression: download_file must not clobber caller's dest (POSIX sh has no local).
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
. "$ROOT/scripts/lib.sh"

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

# Stub network: honor curl's -o and create an empty file at that path.
curl() {
    out=""
    prev=""
    for arg in "$@"; do
        if [ "$prev" = "-o" ]; then
            out="$arg"
            break
        fi
        prev="$arg"
    done
    [ -n "$out" ] || return 1
    : >"$out"
}

CHANNEL=github
RAW_BASE="https://example.invalid/raw"
FIRERAVEN_HOOKS_REPO="fireravenai/fireraven-agent-hooks"
FIRERAVEN_HOOKS_REF="main"

# Same variable name as install.sh _install_tree historically used.
dest="$tmpdir/hooks"
download_package_tree "$dest"
write_install_meta "$dest" "cursor"

if [ "$dest" != "$tmpdir/hooks" ]; then
    printf 'FAIL: dest clobbered to %s\n' "$dest" >&2
    exit 1
fi
if [ ! -f "$tmpdir/hooks/install_meta.json" ]; then
    printf 'FAIL: missing install_meta.json under hooks dir\n' >&2
    exit 1
fi
if [ ! -f "$tmpdir/hooks/README.md" ]; then
    printf 'FAIL: README.md missing or not a regular file\n' >&2
    exit 1
fi

printf 'ok\n'
