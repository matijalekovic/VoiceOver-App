"""Milestone M1 proof of concept, run on the target Mac before relying on the desktop app.

It drives the same pipeline the app uses (voice library, reference processing, job queue,
inference worker, post-processing) without the UI, and writes a report with timings,
memory figures and the generated audio for listening tests.

    uv run voice-studio-validate --reference ~/voice.wav --transcript "Exact words spoken." \
        --speaker "Jane Doe" --scope "Internal narration tests"

    # after quitting and starting again, prove the saved voice still works:
    uv run voice-studio-validate --reuse-voice <voice-id>
"""

from __future__ import annotations

import argparse
import contextlib
import json
import platform
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import psutil

from . import __version__
from .catalog import CATALOG, DEFAULT_MODEL_ID
from .config import Paths, Settings, default_data_dir
from .studio import Studio, configure_logging
from .voices import VoiceService

# About 30 seconds of narration each, written for this test.
DEFAULT_TEXTS = {
    "english": (
        "Welcome to the studio. Today we are walking through a new residential project on the edge of the old "
        "harbour. The building steps down towards the water, so every apartment opens onto a terrace with "
        "morning light. Timber, stone and lime plaster keep the palette quiet. Inside, the plans are simple and "
        "flexible, and the shared courtyard becomes a garden that neighbours can actually use."
    ),
    "french": (
        "Bienvenue au studio. Aujourd'hui, nous découvrons un nouveau projet résidentiel en bordure de l'ancien "
        "port. Le bâtiment descend en gradins vers l'eau, si bien que chaque appartement s'ouvre sur une terrasse "
        "baignée de lumière le matin. Le bois, la pierre et l'enduit à la chaux gardent une palette sobre. "
        "À l'intérieur, les plans restent simples et flexibles."
    ),
    "spanish": (
        "Bienvenidos al estudio. Hoy recorremos un nuevo proyecto residencial junto al antiguo puerto. El "
        "edificio desciende en terrazas hacia el agua, de modo que cada vivienda se abre a una terraza con luz de "
        "mañana. La madera, la piedra y el revoco de cal mantienen una paleta serena. En el interior, las plantas "
        "son sencillas y flexibles, y el patio compartido se convierte en un jardín para los vecinos."
    ),
}


class MemorySampler:
    """Samples the worker's resident memory and the system's available memory while jobs run."""

    def __init__(self, studio: Studio):
        self.studio = studio
        self.peak_worker_rss = 0
        self.min_available = psutil.virtual_memory().available
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(0.25):
            self.min_available = min(self.min_available, psutil.virtual_memory().available)
            pid = self.studio.inference.worker_pid()
            if pid:
                with contextlib.suppress(psutil.Error):
                    self.peak_worker_rss = max(
                        self.peak_worker_rss, psutil.Process(pid).memory_info().rss
                    )

    def __enter__(self) -> MemorySampler:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join()


def _gb(value: float | None) -> str:
    return "n/a" if value is None else f"{value / 1e9:.2f} GB"


def _sysctl(name: str) -> str | None:
    try:
        return subprocess.run(
            ["/usr/sbin/sysctl", "-n", name], capture_output=True, text=True, timeout=2
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def environment() -> dict[str, Any]:
    info: dict[str, Any] = {
        "voice_studio": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "macos": platform.mac_ver()[0] or None,
        "chip": _sysctl("machdep.cpu.brand_string")
        if sys.platform == "darwin"
        else platform.processor(),
        "memory_total": psutil.virtual_memory().total,
    }
    try:
        import mlx.core as mx

        info["mlx"] = mx.__version__
        info["mlx_audio"] = metadata.version("mlx-audio")
    except ImportError:
        info["mlx"] = None
    return info


def wait(studio: Studio, job_id: str) -> dict[str, Any]:
    last = None
    while True:
        job = studio.jobs.get(job_id)
        stage = (job["status"], job["progress"].get("chunk"))
        if stage != last:
            progress = job["progress"]
            extra = (
                f" chunk {progress['chunk'] + 1}/{progress['chunks']}"
                if "chunk" in progress and "chunks" in progress
                else ""
            )
            print(f"    {job['status']}{extra}", flush=True)
            last = stage
        if job["status"] in ("completed", "failed", "cancelled"):
            return job
        time.sleep(0.25)


def ensure_model(studio: Studio, model_id: str, download: bool) -> None:
    status = studio.models.status(model_id)
    if status["state"] == "installed":
        return
    spec = studio.models.spec(model_id)
    if not download:
        sys.exit(
            f"{spec.label} is not installed at {status['path']}.\n"
            f"Run again with --download, or fetch it yourself:\n"
            f'  uvx --from huggingface_hub hf download {spec.repo_id} --local-dir "{status["path"]}"'
        )
    print(f"Downloading {spec.repo_id} …", flush=True)
    studio.models.start_download(model_id)
    while True:
        status = studio.models.status(model_id)
        if status["state"] != "downloading":
            break
        total = status.get("total_bytes") or 0
        done = status.get("downloaded_bytes") or 0
        print(f"\r  {done / 1e9:.2f} / {total / 1e9:.2f} GB", end="", flush=True)
        time.sleep(2)
    print()
    if status["state"] != "installed":
        sys.exit(f"Download failed: {status.get('error') or status.get('problems')}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Validate Qwen3-TTS voice cloning on this Mac (milestone M1)."
    )
    parser.add_argument(
        "--reference", type=Path, help="Consented reference recording (10–30 s of clean speech)."
    )
    parser.add_argument(
        "--transcript", help="Exact words in the reference recording, or @path/to/file.txt"
    )
    parser.add_argument("--speaker", help="Name of the person whose voice it is (consent record).")
    parser.add_argument(
        "--scope", default="Voice Studio validation tests", help="Uses the speaker agreed to."
    )
    parser.add_argument("--name", default=None, help="Name for the saved voice profile.")
    parser.add_argument(
        "--reuse-voice", help="Skip cloning and reuse a voice saved by an earlier run."
    )
    parser.add_argument(
        "--models",
        default=DEFAULT_MODEL_ID,
        help=f"Comma-separated model ids: {', '.join(s.id for s in CATALOG if s.kind == 'tts')}",
    )
    parser.add_argument("--languages", default="english,french,spanish")
    parser.add_argument(
        "--texts",
        type=Path,
        help="JSON file mapping language -> text to use instead of the defaults.",
    )
    parser.add_argument("--download", action="store_true", help="Download missing models.")
    parser.add_argument(
        "--data-dir", type=Path, default=default_data_dir(), help="Voice Studio data folder."
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="Where to write the report and audio."
    )
    args = parser.parse_args(argv)

    if not args.reuse_voice and not (args.reference and args.transcript and args.speaker):
        parser.error("give --reference, --transcript and --speaker, or --reuse-voice")

    out = args.out or Path.cwd() / f"validation-{datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    texts = dict(DEFAULT_TEXTS)
    if args.texts:
        texts.update(json.loads(args.texts.read_text()))
    languages = [lang.strip().lower() for lang in args.languages.split(",") if lang.strip()]
    model_ids = [m.strip() for m in args.models.split(",") if m.strip()]

    settings = Settings(paths=Paths(args.data_dir))
    settings.paths.ensure()
    configure_logging(settings.paths.logs)
    studio = Studio(settings)
    studio.start()
    env = environment()
    print(
        f"Voice Studio {__version__} · {env['chip']} · {_gb(env['memory_total'])} RAM · mlx {env.get('mlx')}"
    )
    if not env.get("mlx"):
        print("WARNING: MLX is not installed; this machine cannot run the model.")

    report: dict[str, Any] = {
        "started_at": datetime.now().isoformat(),
        "environment": env,
        "runs": [],
    }
    try:
        voices = VoiceService(studio)
        if args.reuse_voice:
            voice = voices.get(args.reuse_voice)
            print(f"Reusing saved voice “{voice['name']}” ({voice['id']})")
        else:
            transcript = args.transcript
            if transcript.startswith("@"):
                transcript = Path(transcript[1:]).expanduser().read_text().strip()
            voice = voices.create(
                name=args.name or f"Validation – {args.speaker}",
                description="Created by voice-studio-validate",
                language=languages[0],
                consent={
                    "speaker": args.speaker,
                    "scope": args.scope,
                    "notes": "Recorded by the validation tool.",
                },
            )
            tmp = settings.paths.cache / f"validate-{voice['id']}{args.reference.suffix.lower()}"
            shutil.copy(args.reference.expanduser(), tmp)
            ref = voices.add_reference(
                voice["id"], tmp, args.reference.name, transcript, languages[0]
            )
            quality = ref["quality"]
            print(
                f"Reference: {ref['duration_s']:.1f}s after trimming (from {ref['source_duration_s']:.1f}s), "
                f"SNR ≈ {quality['snr_db']:.0f} dB"
            )
            for flag in quality["flags"]:
                print(f"  {flag['severity'].upper()}: {flag['message']}")
            if any(f["severity"] == "error" for f in quality["flags"]):
                sys.exit(
                    "The reference recording is not usable; fix the issues above and run again."
                )
            voice = voices.update(voice["id"], {"status": "ready"})
            print(f"Saved voice “{voice['name']}” with id {voice['id']}")
        report["voice"] = {
            "id": voice["id"],
            "name": voice["name"],
            "reference": voice["primary_reference_id"],
        }

        for model_id in model_ids:
            spec = studio.models.spec(model_id)
            ensure_model(studio, model_id, args.download)
            studio.inference.unload()  # measure a cold load for every model
            print(f"\n== {spec.label} ({spec.repo_id})")
            with MemorySampler(studio) as sampler:
                load_started = time.monotonic()
                job = studio.jobs.submit("load_model", {"model_id": model_id})
                job = wait(studio, job["id"])
                if job["status"] != "completed":
                    raise SystemExit(f"Loading failed: {job['error_code']}: {job['error_message']}")
                load_seconds = time.monotonic() - load_started
                print(f"  loaded in {load_seconds:.1f}s")
                for language in languages:
                    if language not in texts:
                        print(f"  no text for {language}; skipping")
                        continue
                    print(f"  [{language}]")
                    job = studio.jobs.submit(
                        "tts",
                        {
                            "text": texts[language],
                            "voice_id": voice["id"],
                            "reference_id": voice["primary_reference_id"],
                            "language": language,
                            "model_id": model_id,
                            "seed": 1234,
                        },
                        voice_id=voice["id"],
                    )
                    job = wait(studio, job["id"])
                    run: dict[str, Any] = {
                        "model_id": model_id,
                        "language": language,
                        "status": job["status"],
                    }
                    if job["status"] == "completed":
                        stats = job["result"]["stats"]
                        generation_id = job["result"]["generation_id"]
                        row = studio.db.one(
                            "SELECT audio_path FROM generations WHERE id = ?", (generation_id,)
                        )
                        wav = out / f"{model_id}-{language}.wav"
                        shutil.copy(studio.paths.resolve(row["audio_path"]), wav)
                        run.update(
                            generation_id=generation_id,
                            file=wav.name,
                            audio_seconds=stats["audio_seconds"],
                            elapsed_s=stats["elapsed_s"],
                            real_time_factor=stats["real_time_factor"],
                            gpu_peak_bytes=stats["memory"].get("gpu_peak_bytes"),
                            worker_peak_rss_bytes=stats["memory"].get("rss_peak_bytes"),
                        )
                        print(
                            f"    {stats['audio_seconds']:.1f}s of audio in {stats['elapsed_s']:.1f}s "
                            f"(RTF {stats['real_time_factor']}), MLX peak {_gb(stats['memory'].get('gpu_peak_bytes'))}"
                        )
                    else:
                        run.update(error_code=job["error_code"], error_message=job["error_message"])
                        print(f"    FAILED {job['error_code']}: {job['error_message']}")
                    report["runs"].append(run)
            report.setdefault("models", []).append(
                {
                    "model_id": model_id,
                    "load_seconds": round(load_seconds, 2),
                    "worker_peak_rss_sampled_bytes": sampler.peak_worker_rss,
                    "system_min_available_bytes": sampler.min_available,
                }
            )
            print(
                f"  worker peak RSS {_gb(sampler.peak_worker_rss)}, "
                f"lowest system available memory {_gb(sampler.min_available)}"
            )
    finally:
        studio.stop()

    report["finished_at"] = datetime.now().isoformat()
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    (out / "report.md").write_text(render_markdown(report))
    print(f"\nReport and audio written to {out}")
    print(
        f"Next: quit, then run again with --reuse-voice {report['voice']['id']} to check persistence."
    )


def render_markdown(report: dict[str, Any]) -> str:
    env = report["environment"]
    lines = [
        "# Voice Studio M1 validation",
        "",
        f"- Date: {report['started_at']}",
        f"- Machine: {env.get('chip')} · {_gb(env.get('memory_total'))} · macOS {env.get('macos')}",
        f"- Runtime: Python {env.get('python')} · mlx {env.get('mlx')} · mlx-audio {env.get('mlx_audio')}",
        f"- Voice: {report['voice']['name']} (`{report['voice']['id']}`)",
        "",
        "## Models",
        "",
        "| Model | Cold load | Worker peak RSS (sampled) | Lowest system available memory |",
        "|---|---|---|---|",
    ]
    for model in report.get("models", []):
        lines.append(
            f"| {model['model_id']} | {model['load_seconds']} s | {_gb(model['worker_peak_rss_sampled_bytes'])} "
            f"| {_gb(model['system_min_available_bytes'])} |"
        )
    lines += [
        "",
        "## Generations",
        "",
        "| Model | Language | Audio | Time | RTF | MLX peak | File |",
        "|---|---|---|---|---|---|---|",
    ]
    for run in report["runs"]:
        if run["status"] == "completed":
            lines.append(
                f"| {run['model_id']} | {run['language']} | {run['audio_seconds']:.1f} s | {run['elapsed_s']:.1f} s "
                f"| {run['real_time_factor']} | {_gb(run.get('gpu_peak_bytes'))} | {run['file']} |"
            )
        else:
            lines.append(
                f"| {run['model_id']} | {run['language']} | failed: {run.get('error_code')} | | | | |"
            )
    lines += [
        "",
        "RTF = generation time ÷ audio duration (below 1 is faster than real time).",
        "",
        "## Listening evaluation (fill in)",
        "",
        "Score 1–5. Identity = sounds like the speaker; Pronunciation = correct for the language.",
        "",
        "| Model | Language | Identity | Pronunciation | Artifacts / glitches | Notes |",
        "|---|---|---|---|---|---|",
    ]
    for run in report["runs"]:
        if run["status"] == "completed":
            lines.append(f"| {run['model_id']} | {run['language']} | | | | |")
    lines += [
        "",
        "## Persistence",
        "",
        "- [ ] Re-run with `--reuse-voice` after a restart produced audio with the same voice.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
