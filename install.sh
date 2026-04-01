#!/usr/bin/env bash
set -euo pipefail

REPO_SLUG="unlikefraction/glass"
ARCHIVE_URL="https://codeload.github.com/${REPO_SLUG}/tar.gz/refs/heads/main"
INSTALL_DIR="$HOME/.glass"
BIN_DIR="$HOME/.local/bin"
WRAPPER_PATH="$BIN_DIR/glass"

error() { printf "glass install: %s\n" "$*" >&2; }
info() { printf "glass install: %s\n" "$*" >&2; }

if ! command -v python3 >/dev/null 2>&1; then
    error "python3 is required."
    exit 1
fi

mkdir -p "$INSTALL_DIR" "$BIN_DIR"

SCRIPT_DIR=""
if [ "${BASH_SOURCE:-}" != "" ] && [ -e "${BASH_SOURCE:-}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE:-}")" && pwd)"
fi

copy_tree() {
    local from="$1"
    local to="$2"
    rm -rf "$to"
    mkdir -p "$to"
    (
        cd "$from"
        tar \
            --exclude='.git' \
            --exclude='__pycache__' \
            --exclude='*.pyc' \
            -cf - .
    ) | (
        cd "$to"
        tar -xf -
    )
}

if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/glass_cli.py" ] && [ -f "$SCRIPT_DIR/glass" ]; then
    info "installing from local checkout"
    copy_tree "$SCRIPT_DIR" "$INSTALL_DIR"
else
    if ! command -v curl >/dev/null 2>&1; then
        error "curl is required to download glass."
        exit 1
    fi
    if ! command -v tar >/dev/null 2>&1; then
        error "tar is required to unpack glass."
        exit 1
    fi

    info "downloading latest glass"
    TMP_DIR="$(mktemp -d /tmp/glass-install-XXXXXX)"
    trap 'rm -rf "$TMP_DIR"' EXIT
    curl -fsSL "$ARCHIVE_URL" | tar -xzf - -C "$TMP_DIR"
    SRC_DIR="$(find "$TMP_DIR" -mindepth 1 -maxdepth 1 -type d -name 'glass-*' | head -1)"
    if [ -z "$SRC_DIR" ]; then
        error "failed to unpack glass archive."
        exit 1
    fi
    copy_tree "$SRC_DIR" "$INSTALL_DIR"
fi

chmod +x "$INSTALL_DIR/glass" "$INSTALL_DIR/install.sh"
ln -sf "$INSTALL_DIR/glass" "$WRAPPER_PATH"

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        info "add this to your shell profile if needed:"
        info "export PATH=\"$BIN_DIR:\$PATH\""
        ;;
esac

info "installed glass at $WRAPPER_PATH"
