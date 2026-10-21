#!/usr/bin/env bash
# Builds "1PAX Voice Studio.app" (and a .dmg) for this Mac. With --install it also copies the
# app into /Applications. The app is not signed for distribution; that only matters when it is
# installed on other Macs (see docs/SETUP.md).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if command -v brew >/dev/null 2>&1 && [[ -d "$(brew --prefix rustup 2>/dev/null)/bin" ]]; then
  export PATH="$(brew --prefix rustup)/bin:$PATH"  # Homebrew's rustup is keg-only
fi
cd "$ROOT/app"
npm ci
npm run tauri build -- --target aarch64-apple-darwin

BUNDLE="$ROOT/app/src-tauri/target/aarch64-apple-darwin/release/bundle"
APP="$BUNDLE/macos/1PAX Voice Studio.app"
echo
echo "Built: $APP"
ls "$BUNDLE/dmg/"*.dmg 2>/dev/null | sed 's/^/Disk image: /' || true

if [[ "${1:-}" == "--install" ]]; then
  osascript -e 'tell application "1PAX Voice Studio" to quit' >/dev/null 2>&1 || true
  rm -rf "/Applications/1PAX Voice Studio.app"
  cp -R "$APP" /Applications/
  echo "Installed to /Applications. Open it from Launchpad or Spotlight."
fi
