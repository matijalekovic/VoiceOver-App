# Setting up Voice Studio on the Mac

Everything below runs on the target Mac (Apple Silicon, macOS 14+). Allow about 15 GB of free
disk: ~4.5 GB per model, ~1.5 GB for the Python runtime, the rest for builds and audio.

## 1. Toolchain and environments

```bash
git clone https://github.com/matijalekovic/VoiceOver-App.git
cd VoiceOver-App
git checkout claude/zen-cannon-xtzenp
scripts/setup-mac.sh
```

The script checks the Mac, then installs:

| Tool | Why | How |
|---|---|---|
| Xcode Command Line Tools | compilers for Rust/Tauri | `xcode-select --install` (it prompts) |
| Homebrew | package manager | asks you to install it from brew.sh if missing |
| uv | Python and its packages | `brew install uv` |
| Python 3.12 | backend | installed by uv, pinned in `backend/.python-version` |
| Node.js | UI build | `brew install node` |
| Rust (rustup) | Tauri shell | `brew install rustup` |
| FFmpeg | audio conversion | comes with the Python dependencies (`imageio-ffmpeg`); no Homebrew FFmpeg needed |
| MLX, mlx-audio | inference on the Apple GPU | `uv sync` in `backend/` |

It ends by printing the MLX version and running the backend tests.

## 2. What to check first

Before relying on the app, prove the model works on this Mac (spec stage 2 / milestone M1).
That needs a model and a consented recording, so do steps 3 and 4 next.

## 3. Download a model

Pick one (you can add the others later):

| Model id | Use | Download |
|---|---|---|
| `qwen3-tts-1.7b-base-bf16` | primary, quality | ~4.5 GB |
| `qwen3-tts-1.7b-base-8bit` | quantised; compare with bf16 first | ~2.5 GB |
| `qwen3-tts-0.6b-base-bf16` | lightweight fallback | ~2 GB |

Any of these works:

```bash
scripts/download-model.sh                              # 1.7B bf16 into the app's model folder
scripts/download-model.sh qwen3-tts-0.6b-base-bf16
```

or let the validation tool fetch it (`--download`), or press **Download** in the app under
Settings → Models. All three put the files in
`~/Library/Application Support/1PAX Voice Studio/models/<model id>/` and resume if interrupted.
The app checks the folder is a complete **Base** checkpoint (it rejects CustomVoice and
VoiceDesign checkpoints, which cannot clone).

## 4. Validate cloning (milestone M1)

Record 10–30 seconds of clean speech from someone who has agreed to be cloned (WAV, MP3, M4A
or FLAC) and write down exactly what they say. Then:

```bash
cd backend
uv run voice-studio-validate \
  --reference ~/Desktop/marie.wav \
  --transcript "Exactly the words spoken in the recording." \
  --speaker "Marie Dupont" --scope "Internal narration tests"
```

It saves the voice to the app's library, generates about 30 seconds each of English, French and
Spanish, and writes `validation-<date>/report.md` with load time, generation time, real-time
factor and memory figures, plus the WAV files and a listening checklist. Then quit, run it again
with `--reuse-voice <id>` (printed at the end) to check the saved voice still works. To compare
models in one go: `--models qwen3-tts-1.7b-base-bf16,qwen3-tts-1.7b-base-8bit,qwen3-tts-0.6b-base-bf16`.

[VALIDATION.md](VALIDATION.md) has the full M1 checklist and the acceptance tests.

## 5. Run the app in development

```bash
cd app
npm run tauri dev
```

This starts the Vite dev server, builds the Tauri shell, and runs the backend straight from
`backend/` with `uv run`, so UI and Python changes apply on reload. The first run downloads the
pinned `uv` binary into `app/src-tauri/binaries/` (checksum-verified) and compiles Rust for a few
minutes.

UI-only work in a browser is also possible: start the backend with a fixed token and point Vite
at it:

```bash
cd backend && VOICE_STUDIO_TOKEN=dev-token uv run python -m voice_studio      # port 8765
cd app && VITE_API_URL=http://127.0.0.1:8765 VITE_API_TOKEN=dev-token npm run dev
```

## 6. Build and install the app

```bash
scripts/build-app.sh --install
```

This builds `1PAX Voice Studio.app` and a `.dmg` under
`app/src-tauri/target/aarch64-apple-darwin/release/bundle/`, then copies the app to
/Applications. Open it from Launchpad or Spotlight; no terminal is needed from here on.

**First launch** shows a setup screen while it installs the Python runtime into
`~/Library/Application Support/1PAX Voice Studio/runtime/` (a few minutes, needs internet once).
Later launches start in a few seconds. App updates that change Python dependencies reinstall the
runtime automatically.

**Offline:** once the runtime and a model are installed, disconnect from the network and check
that cloning, generation and export still work (acceptance test "Offline").

**Signing:** a locally built app runs on the Mac that built it. To install it on other Macs,
sign and notarise it with an Apple Developer ID (Tauri supports this through
`APPLE_SIGNING_IDENTITY` and related variables).

## Where things are

| What | Where |
|---|---|
| Library (database, voices, projects, generated audio, models, logs) | `~/Library/Application Support/1PAX Voice Studio/` |
| Python runtime of the installed app | `…/1PAX Voice Studio/runtime/` |
| Exports | `~/Music/1PAX Voice Studio/` (change in Settings → Audio & exports) |
| Logs | Settings → Storage & logs, or `…/1PAX Voice Studio/logs/` |

To start over, quit the app and delete `~/Library/Application Support/1PAX Voice Studio/`
(models included).

## Troubleshooting

| Symptom | What to do |
|---|---|
| Setup screen says the runtime failed | Check the internet connection, press Try again. The log on the screen shows uv's output. |
| "Not installed" next to a model | Settings → Models → Download, or `scripts/download-model.sh`. "Incomplete" lists the missing files; Resume download fixes it. |
| "The inference process stopped unexpectedly" | If it mentions memory: close other apps, use the 0.6B model, or lower Settings → Audio → Max characters per pass. Otherwise see Settings → Storage & logs → Engine. |
| Microphone recording does nothing | Allow Voice Studio in System Settings → Privacy & Security → Microphone, or upload a file instead. |
| Clone sounds wrong | The transcript must match the cleaned reference word for word; trim the reference to clean speech; try a different 10–30 s excerpt. |
