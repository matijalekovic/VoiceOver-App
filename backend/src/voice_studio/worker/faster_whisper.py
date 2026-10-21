"""Speech-to-text with faster-whisper (CTranslate2), used where MLX does not exist.

Returns the same timed segments as the MLX transcriber, so clips are cut the same way.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from .. import audio
from ..errors import EngineError

WHISPER_SAMPLE_RATE = 16_000


class FasterWhisperTranscriber:
    def transcribe(self, model_dir: Path, audio_path: Path, language: str | None) -> list[dict]:
        """Segments as [{start, end, text, words: [{start, end, word, probability}]}]."""
        try:
            import ctranslate2
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise EngineError(
                "engine_unavailable",
                "The speech recognition runtime is not installed. Reinstall Voice Studio.",
                details=str(exc),
            ) from exc
        if ctranslate2.get_cuda_device_count() > 0:
            device, compute_type = "cuda", "float16"
        else:
            device, compute_type = "cpu", "int8"
        # Decoded here rather than by faster-whisper, whose PyAV-based loader breaks with
        # some PyAV releases; FFmpeg already ships with the app.
        with tempfile.TemporaryDirectory() as folder:
            wav = Path(folder) / "speech.wav"
            audio.decode_to_wav(audio_path, wav, sample_rate=WHISPER_SAMPLE_RATE)
            samples, _ = audio.read_audio(wav)
        model = WhisperModel(str(model_dir), device=device, compute_type=compute_type)
        try:
            segments, _info = model.transcribe(
                samples,
                language=language,
                word_timestamps=True,
                condition_on_previous_text=False,  # fewer runaway repetitions on long audio
                vad_filter=False,
            )
            out = []
            for segment in segments:  # a generator: transcription happens while iterating
                text = segment.text.strip()
                if not text:
                    continue
                out.append(
                    {
                        "start": round(float(segment.start), 3),
                        "end": round(float(segment.end), 3),
                        "text": text,
                        "words": [
                            {
                                "start": round(float(w.start), 3),
                                "end": round(float(w.end), 3),
                                "word": w.word,
                                "probability": round(float(w.probability), 3),
                            }
                            for w in segment.words or []
                        ],
                    }
                )
            return out
        finally:
            del model
