# Releasing an update

Installed copies of the app check GitHub Releases at launch (and every six hours) and offer a
newer version in the sidebar: **Install update** downloads it, installs it and restarts. Nobody
has to download an installer again.

## Ship a version

From an up-to-date `main` with nothing uncommitted:

```bash
scripts/release.sh 0.3.0
```

That sets the version in `tauri.conf.json`, `Cargo.toml` and `package.json`, commits
"Version 0.3.0", tags `v0.3.0` and pushes. GitHub Actions then builds the Mac and Windows
installers, signs the update files and publishes the Release with a `latest.json` that the
installed apps read. It takes about 15 minutes; watch it under the repository's Actions tab.

The version must be higher than the one people have, or the app will not offer it.

## What gets updated

The whole app, including the bundled backend: on the first launch after an update the app sees
the new backend and refreshes its private Python runtime (the same step as first install).
Downloaded models and everything in the library stay as they are.

## The signing key

Updates are signed so an installed app only accepts updates made by you. The key pair lives in
`~/.tauri/` on the Mac it was made on:

| File | What it is |
|---|---|
| `voice-studio.key` | private key: keep it secret |
| `voice-studio.key.password` | its password |
| `voice-studio.key.pub` | public key, also in `tauri.conf.json` → `plugins.updater.pubkey` |

GitHub Actions signs with the private key from two repository secrets,
`TAURI_SIGNING_PRIVATE_KEY` and `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`. To set them:

```bash
gh secret set TAURI_SIGNING_PRIVATE_KEY < ~/.tauri/voice-studio.key
```

```bash
gh secret set TAURI_SIGNING_PRIVATE_KEY_PASSWORD < ~/.tauri/voice-studio.key.password
```

**Back the key up** (a password manager is fine). If it is lost, installed apps cannot accept
any future update: everyone would have to install a new build by hand once, with a new key.

## First time

Copies installed before in-app updates existed (0.2.0 and earlier) have no updater. Send those
people the installer from the first release that has it, once; from then on updates arrive in
the app.

## Platform notes

- **Mac:** the update replaces `/Applications/1PAX Voice Studio.app`. The app is not
  Apple-notarised, but an update downloaded by the app itself does not trigger the Gatekeeper
  prompt that a browser download does.
- **Windows:** the update runs the new installer in passive mode (a progress bar, no questions).
