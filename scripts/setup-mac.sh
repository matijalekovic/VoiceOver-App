#!/usr/bin/env bash
# One-time developer setup on the target Mac (Apple Silicon, macOS 14+).
# Installs the toolchain, the backend environment (including MLX) and the UI dependencies.
# It does not download a model; see docs/SETUP.md step 3.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "Voice Studio needs a Mac with Apple Silicon (MLX runs on the Apple GPU)." >&2
  exit 1
fi
MACOS_MAJOR="$(sw_vers -productVersion | cut -d. -f1)"
if (( MACOS_MAJOR < 14 )); then
  echo "macOS 14 (Sonoma) or newer is required; this Mac runs $(sw_vers -productVersion)." >&2
  exit 1
fi

say "1/5 Xcode Command Line Tools"
if ! xcode-select -p >/dev/null 2>&1; then
  xcode-select --install || true
  echo "Finish the Command Line Tools installer that just opened, then run this script again."
  exit 1
fi
echo "present at $(xcode-select -p)"

say "2/5 Homebrew"
if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is not installed. Install it from https://brew.sh, then run this script again:"
  echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  exit 1
fi
echo "present: $(brew --version | head -1)"

say "3/5 Tools: uv, Node.js, Rust (rustup), git"
# Python itself is installed and managed by uv (pinned in backend/.python-version), and FFmpeg
# comes with the backend's Python dependencies, so neither needs Homebrew.
brew install uv node rustup git
# Homebrew keeps rustup out of PATH (keg-only); add it for this script and tell the user.
export PATH="$(brew --prefix rustup)/bin:$PATH"
rustup toolchain list | grep -q '^stable' || rustup default stable
if ! grep -qs 'rustup/bin' "$HOME/.zprofile"; then
  echo "Tip: add Rust to new terminals with:"
  echo "  echo 'export PATH=\"\$(brew --prefix rustup)/bin:\$PATH\"' >> ~/.zprofile"
fi
echo "uv $(uv --version | cut -d' ' -f2) · node $(node --version) · $(rustc --version)"

say "4/5 Backend environment (Python 3.12, FastAPI, MLX, mlx-audio)"
cd "$ROOT/backend"
uv sync
uv run python -c "import mlx.core as mx, mlx_audio; from importlib.metadata import version; print('mlx', mx.__version__, '· mlx-audio', version('mlx-audio'), '· device', mx.default_device())"
uv run pytest -q

say "5/5 Desktop UI dependencies"
cd "$ROOT/app"
npm ci

say "Done."
cat <<EOF
Next steps (details in docs/SETUP.md):
  1. Validate the model on this Mac (milestone M1):
       cd backend && uv run voice-studio-validate --download \\
         --reference ~/path/to/consented-voice.wav --transcript "Exact words spoken." \\
         --speaker "Full Name" --scope "Internal tests"
  2. Run the app in development:   cd app && npm run tauri dev
  3. Build the .app and .dmg:       scripts/build-app.sh
EOF
