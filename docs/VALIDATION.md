# Validation and acceptance

## Milestone M1: proof of concept on the M5

Definition of done (spec): verified model loads on M5/16 GB; consented voice cloned; narration
generated and exported; memory and speed recorded.

| # | Check | How | Result |
|---|---|---|---|
| 1 | Checkpoint loads | `voice-studio-validate` prints "loaded in …s" | |
| 2 | Voice cloned from a consented 10–30 s recording + exact transcript | validation run; voice appears in My Voices | |
| 3 | ~30 s of English | `validation-*/…-english.wav`, listen | |
| 4 | French and Spanish | `…-french.wav`, `…-spanish.wav`, listen | |
| 5 | Elapsed time, real-time factor | `report.md` → Generations | |
| 6 | Peak memory | `report.md` → MLX peak, worker peak RSS, lowest system available | |
| 7 | Restart and reuse the saved voice | rerun with `--reuse-voice <id>` | |
| 8 | If memory is tight: 0.6B and/or 8-bit | `--models qwen3-tts-0.6b-base-bf16,qwen3-tts-1.7b-base-8bit` | |
| 9 | Export | in the app: Generate → Export → WAV and MP3 320 | |

Fill in the listening table at the end of `report.md` and copy the language results into
Settings → Languages (status + notes) so the app records them.

Tip: run the validation with only the usual apps open, then once more with a browser and a
video call running, to see the memory headroom you really have.

## Acceptance criteria (spec section 11)

| Test | Required result | How to check |
|---|---|---|
| Launch | Opens via Applications without terminal commands | `scripts/build-app.sh --install`, open from Launchpad |
| Initial setup | Detects/downloads missing checkpoint | Fresh data folder: Dashboard shows "Install a voice model"; Settings → Models → Download with progress |
| Cloning | Usable profile from authorised reference audio | Clone Voice → consent → upload → transcript → test → Save voice |
| Persistence | Profile works after restart | Quit, reopen, generate with the voice |
| Speech | Audible narration with the selected profile | Generate page |
| Languages | EN, FR, ES evaluated and documented | M1 report + Settings → Languages notes |
| Long-form | Independently stored segments | Project → Generate missing; each segment has its own take file |
| Regeneration | One segment replaced without rerunning the project | Segment ↻ button: one job, other segments untouched (also covered by `test_project_workflow`) |
| Exports | WAV and MP3 | Export menus (Generate, History, Projects: combined / per segment) |
| Offline | Works with network disconnected | Turn off Wi-Fi after setup; clone, generate, export |
| Memory | Planned workloads within 16 GB | Generate a 10-minute project with your usual apps open; watch Dashboard → Engine and the memory pressure badge |
| Failures | Understandable errors, resume/retry | Pull the network during a model download (Resume), quit during a long project (interrupted jobs → Retry; queued ones continue) |
| Shutdown | Stops the backend and releases model memory | Quit with a model loaded; Activity Monitor shows no Voice Studio `python3.12` processes left and the memory is free |

## Automated tests

```bash
cd backend && uv run pytest
```

20 tests cover the API, the job queue with a real worker process, cancel/crash/retry/recovery,
projects, exports and the validation CLI, using a stand-in engine. They pass in the Linux build
environment; `scripts/setup-mac.sh` runs them on the Mac too.
