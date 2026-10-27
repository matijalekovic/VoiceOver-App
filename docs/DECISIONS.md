# Decisions and departures from the specification

The build follows the specification. Where it differs, or where the specification left a choice
open, this is what was chosen and why.

## Runtime and packaging

**Python runtime installed by a bundled `uv`, not frozen with PyInstaller.**
The spec asks for "a managed Python runtime/sidecar with pinned dependencies". Freezing MLX,
Metal shader libraries, transformers and tokenizers into a PyInstaller binary is fragile and
has to be redone for every dependency bump. Instead the `.app` carries the backend source, the
exact `uv.lock` and a checksum-pinned `uv` binary; the first launch builds a private Python 3.12
environment in Application Support (a few minutes, once, with a progress screen). Same pinned
versions, no system Python involved, and updates are a re-sync. Cost: the first launch needs
internet, which it needs anyway to download a model.

**mlx-audio 0.6.1 as the MLX implementation.** It is maintained, ships Qwen3-TTS Base cloning
(`ref_audio` + `ref_text`, in-context mode), loads `mlx-community` conversions, and was the one
implementation checked here line by line (see `worker/mlx_qwen3.py` for what is relied on). It is
pinned exactly; upgrade deliberately and re-run validation.

**Checkpoints from `mlx-community`.** The official `Qwen/Qwen3-TTS-12Hz-1.7B-Base` weights are
PyTorch; mlx-audio's documented path uses the MLX conversions
`mlx-community/Qwen3-TTS-12Hz-{1.7B,0.6B}-Base-bf16` (and `-8bit`). The 8-bit 1.7B model is in
the catalog but labelled for comparison first, as the spec asks.

**Designed voices use the Voice Design checkpoint, not Base.** Qwen3-TTS Base only clones from
`ref_audio` + `ref_text`; a description-only voice is the separate
`Qwen3-TTS-12Hz-1.7B-VoiceDesign` checkpoint, whose `instruct` field is a natural-language voice
description. The catalog records each checkpoint's `capability` (`clone` or `design`), the API
refuses to run a voice on the wrong one, and the UI filters model pickers by the voice's mode. A
designed profile stores its description instead of recordings; three takes are generated from
different seeds so the user can pick one, and that choice becomes the voice's preview. CustomVoice
checkpoints remain unsupported because they only apply style to a fixed preset speaker.

**FFmpeg from the `imageio-ffmpeg` wheel.** A static FFmpeg (with LAME for MP3) arrives with the
Python dependencies, so the installed app does not depend on Homebrew. `VOICE_STUDIO_FFMPEG`
overrides it.

## Architecture

**Inference in a separate worker process.** Unloading kills the process, so memory is returned
for certain; Metal out-of-memory kills only the worker and is reported (with Retry); "Stop now"
can end a stuck generation. Model switching stops the old worker before starting the new one,
which enforces "never load both simultaneously".

**Polling plus real progress.** Jobs return an id at once; the UI polls every 0.5 s. Progress is
"chunk n of m" and seconds of audio produced, never an estimated percentage (spec: no fabricated
progress).

**Per-launch token, loopback Host check, Origin allow-list.** Binding to 127.0.0.1 alone does not
stop a web page in Safari from calling the API; these do.

## Storage

- Preferences live in the SQLite `settings` table; there is no separate `settings.json`.
- A voice can hold several recordings: `voices/<id>/references/<ref-id>/` keeps the original
  upload, the full converted `source.wav` (so trimming can be redone), and the trimmed,
  normalised `reference.wav` the model hears, plus `transcript.txt`.
- **Reference conditioning is cached in memory, not on disk.** mlx-audio caches the encoded
  reference for as long as the model is loaded; encoding a 10–30 s reference is quick, so v1
  saves and reuses the recording and transcript, which the spec allows ("otherwise save and
  re-use the sample and transcript"). `voices/<id>/conditioning/` is not created.
- Standalone generations live in `generations/`; project takes in `projects/<id>/segments/`.
- Exports are written to an output folder (default `~/Downloads/1PAX Voice Studio`) with a
  "Show in Finder" action, rather than asking for a location each time.
- Generate drafts get their own small `drafts` table.

## Product

- **Languages:** all ten Qwen3-TTS languages are enabled by default (at first only English,
  French and Spanish were, the three the spec asked to evaluate). Each can be switched off in
  Settings → Languages, where it also records an evaluation status and notes.
- **One voice across languages:** a cloned voice gets a profile per language: a scored take it
  continues in every generation (native accent) or the original recording (the speaker's own
  accent), plus that language's delivery. Every chunk is checked against the real recordings and
  regenerated when off-voice. Measurements and reasoning: [MULTILINGUAL.md](MULTILINGUAL.md).
- **No style sliders.** Only controls that are implemented and verifiable: voice, language, model,
  pauses, chunk size, take selection. A per-generation seed is stored for traceability.
- **Reference quality checks:** duration (10–30 s recommended, <3 s or >60 s blocked), clipping,
  speech level, and an estimate of the noise floor. Silence at both ends is trimmed on upload; the
  user can adjust the selection on the waveform.
- **Text splitting:** Generate and project segments are synthesised in passes of at most 350
  characters at sentence boundaries (EN/FR/ES abbreviations handled), which bounds memory and
  makes progress and cancel meaningful.

## Not done here, and why

- Real-model runs: this repository was built in a Linux container without Apple Silicon. All
  model-independent behaviour is tested; the M1 validation on the Mac is the first real-model
  run (see VALIDATION.md).
- Microphone recording uses the webview's `getUserMedia`; it is wired up with the macOS usage
  string and entitlement but has to be confirmed on the Mac. Uploading a file always works.
- Code signing and notarisation: only needed to run the app on other Macs.

## Open questions for you

1. **Auto-transcription.** The spec excludes it from v1, but a wrong transcript is the most common
   cause of poor clones. A local Whisper model on MLX (`mlx-whisper`, ~1.5 GB) could pre-fill the
   transcript for you to correct. Worth adding?
2. **Model choice by default.** Keep 1.7B bf16 as default, or switch to 8-bit if your listening
   tests can't tell them apart (less memory, faster load)?
3. **Who uses it.** Just you on one Mac, or colleagues too? If others, signing/notarisation and a
   shared voice-library export flow become worth doing.
4. **Export defaults.** 24 kHz is the model's native rate; video work usually wants 48 kHz WAV
   (offered in every export menu). Should 48 kHz be the default?
5. **Branding.** The UI reuses the Tenders app's 1PAX palette and mark. Any other brand assets
   to use?
