"""Choosing reference clips from longer recordings.

Qwen3-TTS clones from one short reference each time it generates, and its cost grows with
the reference's length (a 70 s reference is about seven times slower than a 12 s one and
needs twice the GPU memory). So up to three minutes of recordings are a pool to choose
from: candidate clips of 10–25 seconds are cut on Whisper's sentence boundaries, scored
on recording quality, and the best few are offered to the user to compare by ear.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import audio

MIN_CLIP_S = 10.0
TARGET_CLIP_S = 18.0
MAX_CLIP_S = 25.0
FALLBACK_MIN_CLIP_S = 3.0  # when no recording has 10 s of continuous speech
MAX_GAP_S = 1.5  # a longer pause inside a clip is copied into every generation
EDGE_PAD_S = 0.15
CANDIDATES = 3


@dataclass
class Candidate:
    reference_id: str
    start_s: float
    end_s: float
    transcript: str
    score: float
    quality: audio.QualityReport


def _word_start(segment: dict) -> float:
    return segment["words"][0]["start"] if segment.get("words") else segment["start"]


def _word_end(segment: dict) -> float:
    return segment["words"][-1]["end"] if segment.get("words") else segment["end"]


def _quietest(samples: np.ndarray, sample_rate: int, lo: float, hi: float) -> float:
    """The quietest 20 ms point in [lo, hi] seconds: where a cut is least audible."""
    duration = len(samples) / sample_rate
    lo, hi = max(0.0, lo), min(duration, hi)
    if hi - lo < 0.02:
        return (lo + hi) / 2
    win, hop = int(0.02 * sample_rate), int(0.005 * sample_rate)
    start = int(lo * sample_rate)
    region = samples[start : int(hi * sample_rate)]
    best, best_energy = 0, float("inf")
    for offset in range(0, max(1, len(region) - win), hop):
        energy = float(np.mean(region[offset : offset + win] ** 2))
        if energy < best_energy:
            best, best_energy = offset, energy
    return (start + best + win / 2) / sample_rate


def _bounds(
    segments: list[dict], i: int, j: int, samples: np.ndarray, sample_rate: int
) -> tuple[float, float]:
    """Cut points for segments i..j, in the quietest moment before the first word and after
    the last, never reaching into the neighbouring words. Whisper's word times are only
    approximate, so the search reaches a little past them."""
    first, last = _word_start(segments[i]), _word_end(segments[j])
    lo = _word_end(segments[i - 1]) if i > 0 else first - 2 * EDGE_PAD_S
    hi = _word_start(segments[j + 1]) if j + 1 < len(segments) else last + 2 * EDGE_PAD_S
    start = _quietest(samples, sample_rate, max(lo, first - 2 * EDGE_PAD_S), first + 0.05)
    end = _quietest(samples, sample_rate, last - 0.05, min(hi, last + 2 * EDGE_PAD_S))
    return start, end


def _confidence(segments: list[dict]) -> float:
    probs = [w["probability"] for s in segments for w in s.get("words") or []]
    return float(np.mean(probs)) if probs else 0.8


def _score(quality: audio.QualityReport, length: float, confidence: float) -> float:
    """Higher is better. Clean, confidently transcribed speech near the target length wins."""
    snr = min(quality.snr_db, 45.0) / 45.0
    clipping = min(quality.clipping_ratio * 200, 1.0)
    length_fit = 1.0 - min(abs(length - TARGET_CLIP_S) / TARGET_CLIP_S, 1.0)
    errors = sum(1 for f in quality.flags if f["severity"] == "error")
    return round(0.45 * snr + 0.25 * confidence + 0.2 * length_fit - 0.4 * clipping - errors, 4)


def _windows(
    reference_id: str,
    segments: list[dict],
    samples: np.ndarray,
    sample_rate: int,
    min_s: float,
) -> list[Candidate]:
    found: list[Candidate] = []
    for i in range(len(segments)):
        for j in range(i, len(segments)):
            if j > i and segments[j]["start"] - segments[j - 1]["end"] > MAX_GAP_S:
                break
            start, end = _bounds(segments, i, j, samples, sample_rate)
            length = end - start
            if length > MAX_CLIP_S:
                break
            if length < min_s:
                continue
            clip = samples[int(start * sample_rate) : int(end * sample_rate)]
            quality = audio.analyse(clip, sample_rate)
            picked = segments[i : j + 1]
            found.append(
                Candidate(
                    reference_id=reference_id,
                    start_s=round(start, 3),
                    end_s=round(end, 3),
                    transcript=" ".join(s["text"].strip() for s in picked),
                    score=_score(quality, length, _confidence(picked)),
                    quality=quality,
                )
            )
    return found


SENTENCE_ENDS = (".", "!", "?", "…", "。", "！", "？")
MAX_SENTENCE_S = 8.0


def sentences(segments: list[dict]) -> list[dict]:
    """Regroup Whisper's segments into sentences using the word timings, so clips start
    and end where a sentence does. (Segment boundaries can fall mid-sentence, notably with
    faster-whisper.) Segments without word timings are kept as they are."""
    if not segments or not all(s.get("words") for s in segments):
        return segments
    out: list[dict] = []
    current: list[dict] = []
    for segment in segments:
        for word in segment["words"]:
            if current and word["start"] - current[-1]["end"] > MAX_GAP_S:
                out.append(current)  # a long pause ends a sentence, punctuated or not
                current = []
            current.append(word)
            if word["word"].strip().endswith(SENTENCE_ENDS):
                out.append(current)
                current = []
        # Unpunctuated speech would otherwise run on; close long runs at a segment end.
        if current and current[-1]["end"] - current[0]["start"] > MAX_SENTENCE_S:
            out.append(current)
            current = []
    if current:
        out.append(current)
    return [
        {
            "start": words[0]["start"],
            "end": words[-1]["end"],
            "text": "".join(w["word"] for w in words).strip(),
            "words": words,
        }
        for words in out
    ]


def pick_candidates(
    recordings: list[tuple[str, list[dict], np.ndarray, int]],
    count: int = CANDIDATES,
) -> list[Candidate]:
    """Best non-overlapping clips across recordings, spread over different recordings first.

    recordings: (reference_id, whisper segments, mono samples, sample rate) per recording.
    """
    pool: list[Candidate] = []
    for min_s in (MIN_CLIP_S, FALLBACK_MIN_CLIP_S):
        for reference_id, segments, samples, sr in recordings:
            pool.extend(_windows(reference_id, sentences(segments), samples, sr, min_s))
        if pool:
            break
    pool.sort(key=lambda c: c.score, reverse=True)
    chosen: list[Candidate] = []
    # First pass takes the best clip of each recording; later passes fill the remaining slots.
    for one_per_recording in (True, False):
        for candidate in pool:
            if len(chosen) >= count:
                return chosen
            if one_per_recording and any(c.reference_id == candidate.reference_id for c in chosen):
                continue
            if any(
                c.reference_id == candidate.reference_id
                and candidate.start_s < c.end_s
                and c.start_s < candidate.end_s
                for c in chosen
            ):
                continue
            chosen.append(candidate)
    return chosen


DEMO_SCRIPTS: dict[str, str] = {
    "english": "Hi, and welcome. This is a short preview of my new voice. I can read your scripts, "
    "narrate your videos and guide your listeners, clearly and naturally. Let me know how it sounds.",
    "french": "Bonjour et bienvenue. Voici un court aperçu de ma nouvelle voix. Je peux lire vos "
    "scripts, raconter vos vidéos et guider vos auditeurs, avec clarté et naturel. Dites-moi ce que vous en pensez.",
    "spanish": "Hola y bienvenidos. Este es un breve adelanto de mi nueva voz. Puedo leer sus guiones, "
    "narrar sus vídeos y guiar a sus oyentes, con claridad y naturalidad. Díganme qué les parece.",
    "german": "Hallo und willkommen. Das ist eine kurze Hörprobe meiner neuen Stimme. Ich kann Ihre "
    "Skripte lesen, Ihre Videos vertonen und Ihre Hörer klar und natürlich begleiten. Sagen Sie mir, wie es klingt.",
    "italian": "Ciao e benvenuti. Questa è una breve anteprima della mia nuova voce. Posso leggere i "
    "vostri testi, narrare i vostri video e guidare chi ascolta, con chiarezza e naturalezza. Fatemi sapere come suona.",
    "portuguese": "Olá e bem-vindos. Esta é uma breve amostra da minha nova voz. Posso ler os seus "
    "roteiros, narrar os seus vídeos e guiar quem ouve, com clareza e naturalidade. Digam-me o que acham.",
    "serbian": "Zdravo i dobro došli. Ovo je kratak primer mog novog glasa. Mogu da čitam vaše "
    "tekstove, da pripovedam vaše video snimke i vodim vaše slušaoce, jasno i prirodno. Recite mi kako zvuči.",
    "russian": "Здравствуйте и добро пожаловать. Это короткий пример моего нового голоса. Я могу читать "
    "ваши сценарии, озвучивать видео и вести слушателей ясно и естественно. Скажите, как это звучит.",
    "chinese": "你好，欢迎收听。这是我新声音的简短试听。我可以朗读你的稿件、为视频配音，清晰自然地引导听众。告诉我听起来怎么样。",
    "japanese": "こんにちは、ようこそ。これは私の新しい声の短いサンプルです。台本の読み上げや動画のナレーションを、"
    "はっきりと自然にお届けします。聞いた感想を教えてください。",
    "korean": "안녕하세요, 환영합니다. 제 새로운 목소리를 짧게 들려드릴게요. 대본을 읽고 영상을 내레이션하며 "
    "청취자를 또렷하고 자연스럽게 안내할 수 있습니다. 어떻게 들리는지 알려 주세요.",
}


def demo_script(language: str) -> str:
    return DEMO_SCRIPTS.get(language.lower(), DEMO_SCRIPTS["english"])
