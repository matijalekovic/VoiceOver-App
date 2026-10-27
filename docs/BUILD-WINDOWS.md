# Building and testing the Windows installer on a Windows PC

Instructions for building `1PAX Voice Studio_<version>_x64-setup.exe` on a Windows 10/11 PC
and checking it works there. Written so an assistant (e.g. Claude Code) on that PC can follow
it step by step. Run every command in **Git Bash** unless a step says otherwise.

## 1. Prerequisites (one time)

Check each with the command shown; install only what is missing.

| Tool | Check | Install |
|---|---|---|
| Git for Windows (includes Git Bash) | `git --version` | https://git-scm.com/download/win |
| Node.js 22 | `node --version` | https://nodejs.org (LTS 22) |
| Rust + MSVC build tools | `rustc --version` | https://rustup.rs — accept the offer to install the Visual Studio C++ Build Tools ("Desktop development with C++") |

After installing Rust, open a new Git Bash so `cargo` is on the PATH, then add the target:

```bash
rustup target add x86_64-pc-windows-msvc
```

Nothing else is needed: the build downloads the pinned `uv` and the NSIS installer tools.

## 2. Build

GitHub Actions already builds the Windows installer for every release (it is on the release
page next to the `.dmg`), so a PC build is for testing on real hardware or building a version
yourself. Build the released version by checking out its tag (here `v0.3.1`):

```bash
git clone https://github.com/matijalekovic/VoiceOver-App.git
cd VoiceOver-App
git checkout v0.3.1
TAURI_ENV_TARGET_TRIPLE=x86_64-pc-windows-msvc bash scripts/prepare-bundle.sh
cd app
npm ci
npx tauri build --target x86_64-pc-windows-msvc
```

The installer is in `app/src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/`.
The first build compiles Rust for several minutes.

## 3. Test on this PC

1. Run the `-setup.exe`. If SmartScreen appears: **More info → Run anyway**.
2. Open **1PAX Voice Studio** from the Start menu. The first launch installs the engine
   (about 4 GB with PyTorch for NVIDIA GPUs): wait until the app shows **Choose your voice
   models**. If it fails, the log is `%LOCALAPPDATA%\com.onepax.voicestudio\logs\runtime-install.log`.
3. Tick **Lightweight**, download it (speech recognition comes along), then:
   - **Voices → Clone voice**: add a recording of 30 s or more of clean speech, **Create voice**,
     pick a take with **Use this voice**.
   - **Text to Speech**: generate a short line in the recording's language, then in another
     language (e.g. Spanish), then with a **Tone** (e.g. Cheerful), then with a **Target length**.
   - **Audio library**: open a take, export it as WAV and MP3.
4. Report anything that fails with the backend log: `%LOCALAPPDATA%\com.onepax.voicestudio\logs\backend.log`.

A quicker automated check of the installed runtime (downloads the lightweight model and
speech recognition, clones a voice from a recording, generates speech):

```bash
PY="$LOCALAPPDATA/com.onepax.voicestudio/runtime/venv/Scripts/python.exe"
"$PY" scripts/smoke_test.py --reference path/to/a-recording.wav
```

(Run it from the repo folder, after the app's first launch has finished installing the engine.
Without an NVIDIA GPU, generation is several times slower than real time; that is expected.)

## 4. Where to put the result

Copy the `-setup.exe` next to the Mac `.dmg` you share with colleagues. The install guide for
users is [INSTALL.md](INSTALL.md).

From 0.3.0 the app updates itself from GitHub Releases ([RELEASING.md](RELEASING.md)). An
installer built on this PC from a release tag works the same as the one on the release page:
once installed, later versions arrive in the app's sidebar. Only GitHub Actions signs the
update files, so a PC build is never needed to ship an update.

## If something fails

- **Build errors** mentioning `link.exe` or MSVC: the Visual Studio C++ Build Tools are missing;
  rerun the Rust installer or install "Build Tools for Visual Studio" with the C++ workload.
- **`prepare-bundle.sh` checksum mismatch**: a download was corrupted; run it again.
- Fixes to the app should go to a branch and a pull request on GitHub as usual.
