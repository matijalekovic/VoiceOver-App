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
    x86_64-pc-windows-msvc) echo "ea1397797a0ca15f63516dd0f49c2dde9776db9be5861cab152ebe8ad199894d" ;;
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
EXE=""
[[ "$TRIPLE" == *windows* ]] && EXE=".exe"
BIN="$TAURI/binaries/uv-$TRIPLE$EXE"
# Runnable only on its own platform; when staging for another (a cross check), trust the file.
if [[ -f "$BIN" ]] && { ! "$BIN" --version >/dev/null 2>&1 || "$BIN" --version | grep -q "uv $UV_VERSION"; }; then
  echo "uv $UV_VERSION already staged for $TRIPLE"
  exit 0
fi
EXPECTED="$(uv_sha256 "$TRIPLE")"
if [[ -z "$EXPECTED" ]]; then
  echo "No pinned uv build for $TRIPLE (Voice Studio targets macOS and Windows)." >&2
  exit 1
fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
ARCHIVE="uv-$TRIPLE.tar.gz"
[[ -n "$EXE" ]] && ARCHIVE="uv-$TRIPLE.zip"
curl -fsSL "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$ARCHIVE" -o "$TMP/$ARCHIVE"
if command -v shasum >/dev/null 2>&1; then
  ACTUAL="$(shasum -a 256 "$TMP/$ARCHIVE" | cut -d' ' -f1)"
else
  ACTUAL="$(sha256sum "$TMP/$ARCHIVE" | cut -d' ' -f1)"  # Git Bash on Windows
fi
if [[ "$ACTUAL" != "$EXPECTED" ]]; then
  echo "Checksum mismatch for $ARCHIVE: expected $EXPECTED, got $ACTUAL" >&2
  exit 1
fi
mkdir -p "$TAURI/binaries"
if [[ -n "$EXE" ]]; then
  unzip -q -o "$TMP/$ARCHIVE" -d "$TMP/uv"
  cp "$(find "$TMP/uv" -name uv.exe | head -1)" "$BIN"
else
  tar -xzf "$TMP/$ARCHIVE" -C "$TMP"
  install -m 755 "$TMP/uv-$TRIPLE/uv" "$BIN"
fi
echo "Staged uv $UV_VERSION at $BIN"
