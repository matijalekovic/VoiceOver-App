"""How a voice delivers its lines: expressiveness, speed and pitch.

Qwen3-TTS Base clones the delivery of its reference clip and takes no style instruction,
so the controls are the ones that really exist:
- expressiveness steers the model's sampling: low is steady and even, high varies more;
- speed and pitch are applied to the finished audio (pitch-preserving tempo change and a
  small pitch shift), because the model has no control for either.
A voice stores its own defaults; a generation can override any of them.
"""

from __future__ import annotations

from typing import Any

DEFAULT_STYLE: dict[str, float] = {"expressiveness": 0.6, "speed": 1.0, "pitch": 0.0}
LIMITS: dict[str, tuple[float, float]] = {
    "expressiveness": (0.0, 1.0),
    "speed": (0.8, 1.25),
    "pitch": (-2.0, 2.0),  # semitones; larger shifts sound processed
}


def resolve(*layers: dict[str, Any] | None) -> dict[str, float]:
    """Defaults, then each layer in turn (voice defaults, then the generation's overrides)."""
    style = dict(DEFAULT_STYLE)
    for layer in layers:
        for key, value in (layer or {}).items():
            if key in LIMITS and value is not None:
                low, high = LIMITS[key]
                style[key] = round(min(max(float(value), low), high), 3)
    return style


def sampling(expressiveness: float) -> dict[str, float]:
    """Model sampling for an expressiveness level. 0.6 is the model's own default
    (temperature 0.9, top-p 1.0); lower narrows the choices, higher widens them."""
    e = min(max(expressiveness, 0.0), 1.0)
    if e <= 0.6:
        temperature = 0.5 + e / 0.6 * 0.4
        top_p = 0.8 + e / 0.6 * 0.2
    else:
        temperature = 0.9 + (e - 0.6) / 0.4 * 0.3
        top_p = 1.0
    return {"temperature": round(temperature, 3), "top_p": round(top_p, 3)}


def needs_processing(style: dict[str, float]) -> bool:
    return abs(style["speed"] - 1.0) > 1e-3 or abs(style["pitch"]) > 1e-3
