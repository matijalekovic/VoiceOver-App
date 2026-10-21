# 1PAX Voice Studio

A desktop app for Mac and Windows for cloning authorised voices from recordings and producing
voiceovers, in the manner of an ElevenLabs studio, with everything running locally: inference
(Qwen3-TTS: on Apple's MLX on Macs, PyTorch with CUDA on Windows), reference audio, projects and
exports. No accounts, no API subscription.

Targets: Macs with Apple Silicon on macOS 14 or newer (developed on a MacBook Pro M5, 16 GB);
Windows 10/11 PCs, ideally with an NVIDIA GPU.

**Installing a release:** see [docs/INSTALL.md](docs/INSTALL.md). Installers for both platforms
are built by GitHub Actions and published to Releases when a version tag is pushed.

## Developing (Mac)

| Step | What | Where |
|---|---|---|
| 1 | Install the toolchain and environments | `scripts/setup-mac.sh` |
| 2 | Download a model and **validate cloning on the Mac (milestone M1)** | [docs/SETUP.md](docs/SETUP.md#3-download-a-model), [docs/VALIDATION.md](docs/VALIDATION.md) |
| 3 | Run the app in development | `cd app && npm run tauri dev` |
| 4 | Build and install the `.app` | `scripts/build-app.sh --install` |

[docs/SETUP.md](docs/SETUP.md) walks through all of it. [docs/DECISIONS.md](docs/DECISIONS.md)
lists where this build differs from the specification, and why.

## How it fits together

```
1PAX Voice Studio.app (Tauri 2 + React)
   │  starts and stops ▼, passes a free port and a per-launch token
Python backend (FastAPI on 127.0.0.1)          ~/Library/Application Support/1PAX Voice Studio/
   ├─ voices, references, projects, history ──▶ database/voice_studio.sqlite + audio files
   ├─ job queue (one job at a time)
   ├─ FFmpeg conversion, trimming, assembly, WAV/MP3 export
   └─ inference worker process  ──▶ engine adapter ──▶ Qwen3-TTS Base on mlx-audio (MLX / Metal)
```

- The model runs in its own **worker process**: unloading a model ends the process, so its memory
  always goes back to macOS, and an out-of-memory crash becomes an error with a Retry button
  instead of taking the app down.
- Inference sits behind an **adapter** (`backend/src/voice_studio/worker/engine.py`); a
  different runtime later means one new class.
- On first launch the app installs a private Python runtime with a bundled `uv`, then works
  offline. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Repository

| Path | Contents |
|---|---|
| `backend/` | Python package `voice_studio`: API, storage, job queue, audio pipeline, inference worker, `voice-studio-validate` |
| `backend/tests/` | API and pipeline tests (they use a stand-in engine that is not part of the app) |
| `app/src/` | React + TypeScript UI (Tailwind, shadcn-style components, WaveSurfer.js) |
| `app/src-tauri/` | Tauri 2 shell: backend lifecycle, first-run runtime install, bundle config |
| `scripts/` | Mac setup, model download, bundle preparation, app build |
| `docs/` | Setup, architecture, decisions, validation |

## Everyday commands

```bash
cd backend && uv run pytest                 # backend tests
cd backend && uv run voice-studio-validate --help
cd app && npm run tauri dev                 # app with hot reload, backend from source
scripts/download-model.sh                   # fetch the 1.7B Base checkpoint into the app
scripts/build-app.sh --install              # build and copy to /Applications
```

The local API is documented at `http://127.0.0.1:<port>/docs` while the backend runs (every
request needs the token; see docs/ARCHITECTURE.md).

## Voice rights

Every voice profile records the speaker's name, the uses they agreed to and when. Cloning is
blocked without that confirmation, and deleting a voice deletes its recordings and everything
derived from them. Use cloned voices only within the speaker's permission.
