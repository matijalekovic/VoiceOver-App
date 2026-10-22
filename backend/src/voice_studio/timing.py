"""Fitting speech to a target length (for narrating a video of a given duration).

The model reads at its own pace and has no length control, so the length is fitted after
generation: first the pauses between sentences and paragraphs are stretched or squeezed
(the voice itself is untouched), then the remainder is made up with a pitch-preserving
tempo change, within limits that still sound natural. Before generating, the natural
length is estimated from the voice's own speaking rate.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np

from . import audio

PAUSE_SCALE = (0.3, 2.5)  # how far pauses may shrink or grow
FIT_SPEED = (0.8, 1.25)  # tempo range that still sounds natural (the speed slider's range)
TYPICAL_WORDS_PER_S = 2.6  # about 155 words a minute, pauses included
TYPICAL_CHARS_PER_S = 4.5  # Chinese and Japanese, counted in characters
CHARACTER_LANGUAGES = {"chinese", "japanese"}


def fit(
    parts: list[tuple[np.ndarray, float]], sample_rate: int, target_s: float, *, pitch: float
) -> tuple[np.ndarray, dict[str, Any]]:
    """Join (speech, pause after) parts so the result lasts as close to target_s as the
    limits allow. Returns the audio and what was done."""
    speech_s = sum(len(a) for a, _ in parts) / sample_rate
    pauses_s = sum(p for _, p in parts[:-1])
    natural_s = speech_s + pauses_s
    scale = 1.0
    if pauses_s > 0:
        wanted = (target_s - speech_s) / pauses_s
        scale = min(max(wanted, PAUSE_SCALE[0]), PAUSE_SCALE[1])
    joined = audio.join([(a, p * scale) for a, p in parts], sample_rate)
    joined_s = len(joined) / sample_rate
    speed = min(max(joined_s / target_s, FIT_SPEED[0]), FIT_SPEED[1])
    out = audio.change_tempo_pitch(joined, sample_rate, speed=speed, semitones=pitch)
    achieved = len(out) / sample_rate
    return out, {
        "target_s": round(target_s, 2),
        "natural_s": round(natural_s, 2),
        "achieved_s": round(achieved, 2),
        "pause_scale": round(scale, 3),
        "speed": round(speed, 3),
        "within": abs(achieved - target_s) <= max(0.3, 0.02 * target_s),
    }


def units(text: str, language: str) -> int:
    """Words, or characters for languages written without spaces."""
    if language.lower() in CHARACTER_LANGUAGES:
        return len(re.sub(r"\s", "", text))
    return len(text.split())


def speaking_rate(history: list[dict[str, Any]], language: str) -> tuple[float, str]:
    """Units per second from the voice's past generations in this language (those made at
    normal speed and not fitted), or a typical rate. Returns (rate, "voice" | "typical")."""
    spoken = sum(units(h["text"], language) for h in history)
    seconds = sum(h["duration_s"] for h in history)
    if spoken >= 30 and seconds > 0:
        return spoken / seconds, "voice"
    typical = (
        TYPICAL_CHARS_PER_S if language.lower() in CHARACTER_LANGUAGES else TYPICAL_WORDS_PER_S
    )
    return typical, "typical"


def estimate(text: str, language: str, rate: float) -> dict[str, float]:
    """The natural length, and the range fitting can reach from it."""
    seconds = units(text, language) / rate
    return {
        "seconds": round(seconds, 1),
        "shortest_s": round(seconds / FIT_SPEED[1] * 0.95, 1),  # pauses add a little slack
        "longest_s": round(seconds / FIT_SPEED[0] * 1.05, 1),
    }
