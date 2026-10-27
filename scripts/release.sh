#!/usr/bin/env bash
# Ship a new version to everyone who has the app: bumps the version, tags it and pushes.
# GitHub Actions then builds both installers and publishes a Release with the signed update
# files; installed apps offer the update in the sidebar. See docs/RELEASING.md.
#
#   scripts/release.sh 0.3.0
set -euo pipefail
VERSION="${1:?usage: scripts/release.sh <version, e.g. 0.3.0>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Version must look like 0.3.0" >&2; exit 1; }
[ "$(git branch --show-current)" = main ] || { echo "Release from main." >&2; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "Commit or stash your changes first." >&2; exit 1; }
git pull --ff-only

python3 - "$VERSION" <<'PY'
import json, re, sys
v = sys.argv[1]
for path in ("app/src-tauri/tauri.conf.json", "app/package.json"):
    data = json.load(open(path))
    data["version"] = v
    open(path, "w").write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
path = "app/src-tauri/Cargo.toml"
text = open(path).read()
open(path, "w").write(re.sub(r'(?m)^version = "[^"]+"', f'version = "{v}"', text, count=1))
PY
(cd app && npm install --package-lock-only --silent)
if command -v cargo >/dev/null || [ -x "$(brew --prefix rustup 2>/dev/null)/bin/cargo" ]; then
  PATH="$(brew --prefix rustup 2>/dev/null)/bin:$PATH" cargo update -q -p voice-studio --manifest-path app/src-tauri/Cargo.toml
fi

git commit -qam "Version $VERSION"
git tag "v$VERSION"
git push -q origin main "v$VERSION"
echo "Pushed v$VERSION. The release appears in a few minutes:"
echo "  https://github.com/matijalekovic/VoiceOver-App/actions"
