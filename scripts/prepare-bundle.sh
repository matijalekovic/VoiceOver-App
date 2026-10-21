#!/usr/bin/env bash
# Stages what the .app carries besides the UI: the backend source (installed on first launch
# with uv) and the uv binary itself. Run automatically by `npm run tauri build`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAURI="$ROOT/app/src-tauri"

# Pinned uv release and its published SHA-256 checksums. (No associative arrays: macOS
# ships bash 3.2.)
UV_VERSION="0.12.22"
uv_sha256() {
  case "$1" in
    aarch64-apple-darwin) echo "5d714de09501a59393ceca78f4bc232a50478729640d251907160299b2a93ddd" ;;
    x86_64-apple-darwin) echo "1b8a5b316883df2daf20fb9a446e5b230e01d947d57aba2694977c5ac5a7e98c" ;;
  esac
}

# 1. Backend source, without caches or the development environment.
DEST="$TAURI/resources/backend"
rm -rf "$DEST"
mkdir -p "$DEST"
cp "$ROOT/backend/pyproject.toml" "$ROOT/backend/uv.lock" "$ROOT/backend/.python-version" "$ROOT/backend/README.md" "$DEST/"
cp -R "$ROOT/backend/src" "$DEST/"
find "$DEST" -name '__pycache__' -type d -prune -exec rm -rf {} +
echo "Staged backend source in $DEST"

# 2. uv, named with the target triple as Tauri expects for external binaries.
TRIPLE="${TAURI_ENV_TARGET_TRIPLE:-$(rustc -vV | sed -n 's/^host: //p')}"
BIN="$TAURI/binaries/uv-$TRIPLE"
if [[ -x "$BIN" ]] && "$BIN" --version | grep -q "uv $UV_VERSION"; then
  echo "uv $UV_VERSION already staged for $TRIPLE"
  exit 0
fi
EXPECTED="$(uv_sha256 "$TRIPLE")"
if [[ -z "$EXPECTED" ]]; then
  echo "No pinned uv build for $TRIPLE (Voice Studio targets macOS)." >&2
  exit 1
fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
ARCHIVE="uv-$TRIPLE.tar.gz"
curl -fsSL "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$ARCHIVE" -o "$TMP/$ARCHIVE"
ACTUAL="$(shasum -a 256 "$TMP/$ARCHIVE" | cut -d' ' -f1)"
if [[ "$ACTUAL" != "$EXPECTED" ]]; then
  echo "Checksum mismatch for $ARCHIVE: expected $EXPECTED, got $ACTUAL" >&2
  exit 1
fi
tar -xzf "$TMP/$ARCHIVE" -C "$TMP"
mkdir -p "$TAURI/binaries"
install -m 755 "$TMP/uv-$TRIPLE/uv" "$BIN"
echo "Staged uv $UV_VERSION at $BIN"
