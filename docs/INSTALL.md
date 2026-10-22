# Installing 1PAX Voice Studio

Download the installer for your computer from the project's **Releases** page on GitHub:

| Computer | File | Needs |
|---|---|---|
| Mac with Apple Silicon (M1–M5) | `1PAX Voice Studio_<version>_aarch64.dmg` | macOS 14 or newer, 16 GB of memory recommended |
| Windows PC | `1PAX Voice Studio_<version>_x64-setup.exe` | Windows 10 or 11 (64-bit). An NVIDIA graphics card with 8 GB or more is strongly recommended; without one the app runs on the processor and is much slower |

Plan for about 15 GB of free disk: the runtime (1.5 GB on Mac, about 4 GB on Windows) plus the
models you choose (2–4.5 GB each, 1.6 GB for speech recognition).

## Mac

1. Open the `.dmg` and drag **1PAX Voice Studio** to **Applications**.
2. Open it from Applications. Because this build is not signed by Apple yet, macOS stops it
   the first time:
   - **macOS 15 and newer:** click **Done**, open **System Settings → Privacy & Security**,
     scroll down to the message about 1PAX Voice Studio and click **Open Anyway**, then
     confirm.
   - **macOS 14:** right-click the app in Applications, choose **Open**, then **Open**.
   - If macOS says the app **is damaged**, run this once in Terminal, then open it again:
     ```bash
     xattr -dr com.apple.quarantine "/Applications/1PAX Voice Studio.app"
     ```

## Windows

1. Run the `-setup.exe` installer. Because it is not signed yet, Windows SmartScreen may show
   **Windows protected your PC**: click **More info**, then **Run anyway**.
2. The installer installs for your user account only (no administrator rights needed) and
   adds Voice Studio to the Start menu. If Microsoft Edge WebView2 is missing (rare on
   Windows 10/11), it is downloaded during installation.

## First launch (both)

1. **Setting up Voice Studio** installs the private Python runtime. This happens once, needs
   an internet connection and takes a few minutes (longer on Windows, which downloads PyTorch
   with NVIDIA GPU support, about 2.5 GB).
2. **Choose your voice models**: tick **Lightweight**, **Quality** or both. Speech recognition
   is always included because creating a voice needs it. Downloads run one after another; you
   can start working as soon as the first voice model is ready, and add or remove models later
   in **Settings → Models**.

After that, everything runs offline on your computer: recordings, voices and generated audio
never leave it.

## Uninstalling

- **Mac:** delete the app from Applications. Your voices, recordings and models are in
  `~/Library/Application Support/1PAX Voice Studio`; delete that folder too to remove everything.
- **Windows:** uninstall from **Settings → Apps**. Tick **Delete the application data** in the
  uninstaller to also remove your voices, recordings and models, which live in
  `%LOCALAPPDATA%\com.onepax.voicestudio`.

## For maintainers: publishing a release

1. Bump the version in `app/src-tauri/tauri.conf.json`, `app/src-tauri/Cargo.toml` and
   `app/package.json`, and merge to `main`.
2. Tag and push: `git tag v0.2.0 && git push origin v0.2.0`.
3. The **Build** workflow builds the Mac and Windows installers and publishes them to a GitHub
   Release named after the tag. Every pull request builds both installers too (downloadable
   from the workflow run's artifacts), so a broken build shows up before it is merged.
   Before anything is published, CI installs each installer on a clean GitHub machine, opens
   the app until its first-run setup has the engine running, then uses that runtime to download
   the lightweight model and speech recognition, create a voice from a recording and generate
   speech (`scripts/smoke_test.py`).

**Signing later.** To remove the security prompts, sign the builds:
- Mac: an Apple Developer ID (Apple Developer Program). Add the certificate and notarization
  credentials as repository secrets and pass them to the build step as Tauri's
  `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`, `APPLE_ID`,
  `APPLE_PASSWORD` and `APPLE_TEAM_ID` environment variables.
- Windows: a code-signing certificate, configured under `bundle.windows` in
  `app/src-tauri/tauri.windows.conf.json`.
