# Architecture

## Processes

| Process | Started by | Role |
|---|---|---|
| `1PAX Voice Studio` (Rust, Tauri 2) | the user | window and webview; installs, starts and stops the backend |
| `python -m voice_studio` (FastAPI/uvicorn) | the shell, in its own process group | API on `127.0.0.1:<free port>`, storage, job queue, audio processing, downloads |
| inference worker (Python) | the backend, on demand | holds the one loaded model; synthesises text chunks |
| download worker (Python) | the backend, on demand | `huggingface_hub.snapshot_download` of a checkpoint |

Shutdown: quitting sends SIGTERM to the backend's process group (server and worker), waits up
to 10 s, then SIGKILLs anything left. If the shell dies without that, the backend notices within
a second (`VOICE_STUDIO_PARENT_PID`) and shuts down; the worker likewise exits when the backend
disappears. The model's memory is always returned.

## Inference

`worker/engine.py` defines the adapter every runtime implements:

```python
class TTSEngine(Protocol):
    def load(self, model_dir: Path) -> EngineInfo: ...
    def synthesize(self, request: ChunkRequest) -> np.ndarray: ...  # float32 mono, one chunk
    def memory(self) -> dict: ...
```

`worker/mlx_qwen3.py` implements it with mlx-audio 0.6.1. Passing both `ref_audio` and
`ref_text` selects Qwen3-TTS's in-context (ICL) cloning path. After loading it verifies the
checkpoint is a Base model and that the text tokenizer and speech-tokenizer encoder actually
loaded (mlx-audio downgrades some loading failures to printed warnings, which would otherwise
silently disable cloning).

Rules from the specification enforced here:
- one model loaded and one synthesis running at a time (switching models ends the worker first);
- inference never touches the network (`HF_HUB_OFFLINE=1` in the worker);
- load on demand, unload after an idle period (default 15 min) and on critical macOS memory
  pressure (`kern.memorystatus_vm_pressure_level`).

## A generation, step by step

1. `POST /api/generate` checks the voice has a reference and transcript, then inserts a job and
   returns its id immediately (HTTP 202).
2. The job runner (one thread) picks the oldest queued job: **loading** (starts the worker and
   loads the model if needed) → **synthesizing** → **processing** → **completed**.
3. The text is split into chunks of at most *Max characters per pass* (default 350) at sentence
   boundaries, never across paragraphs. Progress reports chunks done and seconds of audio
   produced; there is no estimated percentage.
4. Each chunk is written as float WAV by the worker. Processing trims chunk edges, joins them with
   the sentence/paragraph pauses, adds short fades, peak-normalises to −1 dBFS and writes a 16-bit
   24 kHz WAV.
5. Cancel stops after the current chunk and keeps the model loaded; "Stop now" ends the worker.
   Jobs interrupted by quitting are marked `interrupted` with Retry on the next start; queued jobs
   carry on.

Project segments are separate jobs, one per segment, each producing a new **take**. The segment's
active take can be switched back; editing a segment's text marks its take as stale.

## Storage

```
~/Library/Application Support/1PAX Voice Studio/      (0700)
  database/voice_studio.sqlite                        (WAL; schema in db.py)
  models/<model-id>/                                  (+ .voice-studio.json marker)
  voices/<voice-id>/references/<ref-id>/original.*    as uploaded
                                       /source.wav    mono 24 kHz, full length
                                       /reference.wav trimmed + normalised: what the model hears
                                       /transcript.txt
  projects/<project-id>/script.json                   readable copy of the script and order
                       /segments/<segment-id>/<generation-id>.wav
                       /exports/assembly.wav          last assembled preview
  generations/<generation-id>.wav                     Generate and voice tests
  cache/  logs/  runtime/ (installed app only)
```

Tables: `voices` (with consent fields), `reference_recordings`, `projects`, `segments`,
`generations`, `jobs`, `drafts`, `settings`. Only relative paths are stored and every resolved
path is checked to stay inside the data folder. Large files are written to a temp file, fsynced
and renamed.

Exports go straight into the output folder (default `~/Downloads`), with no subfolders:
generations by date, voice and opening words; projects as `<Project name>.wav` and, for
segments, `<Project name> 001 ….wav`; voice backups as `.voice.zip` (importable from My Voices).

## API

All routes are under `/api` and need the per-launch token (`Authorization: Bearer …`; media GETs
may pass `?token=` because `<audio>` cannot send headers). The Host header must be a loopback
name and any `Origin` must be the app's webview, which blocks web pages and DNS rebinding.
Errors are `{"error": {"code", "message", "details?"}}`.

| Method | Path | |
|---|---|---|
| GET/POST | `/voices` | list / create (consent required) |
| GET/PATCH/DELETE | `/voices/{id}` | read / update (incl. `status: ready`) / delete with data |
| POST | `/voices/{id}/references` | upload a recording (multipart, ≤100 MB) |
| PATCH/DELETE | `/voices/{id}/references/{ref}` | transcript, trim / delete |
| GET | `/voices/{id}/references/{ref}/audio?which=reference\|source` | audio |
| POST | `/voices/{id}/test` | test line → job |
| POST | `/voices/{id}/export`, `/voices/import` | backup archive |
| POST | `/generate` | job |
| GET | `/jobs?status=active\|all`, `/jobs/{id}` | job state |
| POST | `/jobs/{id}/cancel?force=`, `/jobs/{id}/retry` | |
| GET | `/generations`, `/generations/{id}`, `/generations/{id}/audio` | history |
| POST/DELETE | `/generations/{id}/export`, `/generations/{id}` | WAV/MP3 export, delete |
| GET/POST/PUT/DELETE | `/drafts…` | Generate drafts |
| GET/POST | `/projects` | |
| GET/PUT/DELETE | `/projects/{id}` | |
| POST | `/projects/{id}/script` | re-split the script (keeps takes of unchanged text) |
| POST/PATCH/DELETE | `/projects/{id}/segments[/{sid}]` | add / edit text, pause, active take / delete |
| POST | `/projects/{id}/reorder`, `/generate`, `/preview`, `/export` | |
| GET | `/models` | catalog with install state |
| POST | `/models/download`, `/models/download/cancel`, `/models/load` (job), `/models/unload` | |
| DELETE | `/models/{id}` | remove files |
| GET/PUT | `/settings` | preferences |
| GET | `/languages` | enabled + evaluation notes |
| GET | `/system/status`, `/system/storage`, `/system/logs`, `/health` | |
| POST | `/system/reveal`, `/system/clear-cache` | |

Typed schemas are in `schemas.py`; FastAPI serves them at `/docs` and `/openapi.json`. The UI's
mirror is `app/src/lib/types.ts`.

## UI

React 19 + TypeScript, Tailwind 4, Radix primitives styled in shadcn fashion, TanStack Query for
data and polling, WaveSurfer.js for waveforms, trimming (regions) and microphone recording.
Pages: Dashboard, Generate, My Voices (+ voice editor), Clone Voice, Projects (+ editor),
History, Settings. Hash routing, because the bundle is served from `tauri://localhost`.

## Tests

`backend/tests` exercises the API through the real job queue and a real spawned worker process,
with a stand-in engine that produces tones (it lives only in the tests). Covered: auth and
origin checks, consent, upload/convert/trim/analyse, generation, export to WAV and MP3, queued
and mid-synthesis cancel, worker crash and retry, interrupted-job recovery, project
segmentation/takes/regeneration/reorder/preview/export, voice export/import/delete, model
load/unload, settings, upload limits, and the validation CLI. Real-model behaviour is validated
on the Mac with `voice-studio-validate`.
