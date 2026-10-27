"""Keeping one cloned voice the same person from chunk to chunk.

Every synthesis chunk is sampled on its own, and now and then a chunk comes out as a different
person: measured on a Spanish take of an English speaker, one fingerprint take in seven landed
an octave up (178 Hz against his 95 Hz) with a speaker similarity of 0.89 where the others
scored 0.986–0.989. Heard in a paragraph, that is the voice "switching".

The worker scores each chunk against the speaker's real recordings, on two measures:
- speaker similarity: the model's own speaker encoder, against the averaged embedding of the
  recordings (timbre);
- pitch register: the median F0, against the recordings and against the chunks already
  accepted in the same take (a register jump between chunks is what is heard first).
A chunk that fails either is generated again with another seed, and the best attempt is kept.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

# Seeds for a retried chunk step by a large prime, so attempts are unrelated.
RETRY_SEED_STEP = 7919
MAX_RETRIES = 2
# Takes of the same speaker scored 0.98–0.99; the outlier above scored 0.89.
MIN_SIMILARITY = 0.95
# Native takes in another language sat within 1.3 semitones of the speaker's own register;
# a language's own melody can move it further, so this only catches real jumps.
MAX_REGISTER_OFFSET_ST = 4.0
# Between chunks of one take the median F0 moved 0.1–0.7 semitones when the voice held.
MAX_DRIFT_ST = 2.5


def median_f0(samples: np.ndarray, sample_rate: int) -> float | None:
    """Median F0 in Hz of the voiced 40 ms frames (autocorrelation, 60–400 Hz); None when
    nothing is voiced."""
    x = np.asarray(samples, dtype=np.float32).reshape(-1)
    n = int(0.04 * sample_rate)
    hop = n // 2
    if len(x) < n:
        return None
    frames = np.lib.stride_tricks.sliding_window_view(x, n)[::hop] * np.hanning(n)
    energy = np.sqrt(np.mean(frames**2, axis=1))
    frames = frames[energy > 0.01]
    if not len(frames):
        return None
    ac = np.fft.irfft(np.abs(np.fft.rfft(frames, 2 * n, axis=1)) ** 2, axis=1)[:, :n]
    # Divide out the window's own autocorrelation, which otherwise favours short lags
    # (Boersma 1993), then refine the peak between samples.
    window = np.fft.irfft(np.abs(np.fft.rfft(np.hanning(n), 2 * n)) ** 2)[:n]
    ac = ac / (ac[:, :1] + 1e-9) / (window / window[0] + 1e-9)
    lo, hi = sample_rate // 400, sample_rate // 60
    band = ac[:, lo:hi]
    peak = (band[:, 1:-1] >= band[:, :-2]) & (band[:, 1:-1] >= band[:, 2:])
    # The shortest lag that peaks near the strongest: multiples of the period score as high
    # once the window is divided out, and taking them would halve or third the pitch.
    near_top = band[:, 1:-1] >= 0.9 * band.max(axis=1, keepdims=True)
    lags = lo + 1 + np.argmax(peak & near_top, axis=1)
    rows = np.arange(len(ac))
    strength = ac[rows, lags]
    left, right = ac[rows, lags - 1], ac[rows, lags + 1]
    bend = left - 2 * strength + right
    shift = np.where(bend < 0, 0.5 * (left - right) / np.where(bend < 0, bend, -1), 0.0)
    voiced = (lags + np.clip(shift, -0.5, 0.5))[strength > 0.45]
    if not len(voiced):
        return None
    return float(np.median(sample_rate / voiced))


def semitones(hz: float, reference_hz: float) -> float:
    return float(12 * np.log2(hz / reference_hz))


def unit(vector: np.ndarray) -> np.ndarray:
    v = np.asarray(vector, dtype=np.float32).reshape(-1)
    return v / (np.linalg.norm(v) + 1e-9)


@dataclass
class ChunkScore:
    similarity: float | None
    f0_hz: float | None
    register_st: float | None  # against the speaker's recordings
    drift_st: float | None  # against the chunks already accepted in this take
    attempts: int = 1

    @property
    def outlier(self) -> bool:
        return (
            (self.similarity is not None and self.similarity < MIN_SIMILARITY)
            or (self.register_st is not None and abs(self.register_st) > MAX_REGISTER_OFFSET_ST)
            or (self.drift_st is not None and abs(self.drift_st) > MAX_DRIFT_ST)
        )

    @property
    def rank(self) -> float:
        """Higher is closer to the speaker: one semitone off costs 0.02 of similarity."""
        sim = self.similarity if self.similarity is not None else 1.0
        off = abs(self.register_st or 0.0) + abs(self.drift_st or 0.0)
        return sim - 0.02 * off

    def to_dict(self) -> dict:
        out = asdict(self)
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in out.items()}


class Judge:
    """Scores chunks of one take against the speaker. embedding is the unit speaker embedding
    of the real recordings (None when the engine cannot measure one); target_f0 their median F0."""

    def __init__(self, embedding: np.ndarray | None, target_f0: float | None, sample_rate: int):
        self.embedding = None if embedding is None else unit(embedding)
        self.target_f0 = target_f0
        self.sample_rate = sample_rate
        self._accepted_f0: list[float] = []

    def score(self, audio: np.ndarray, embedding: np.ndarray | None) -> ChunkScore:
        hz = median_f0(audio, self.sample_rate)
        similarity = None
        if self.embedding is not None and embedding is not None:
            similarity = float(unit(embedding) @ self.embedding)
        register = semitones(hz, self.target_f0) if hz and self.target_f0 else None
        drift = (
            semitones(hz, float(np.median(self._accepted_f0))) if hz and self._accepted_f0 else None
        )
        return ChunkScore(similarity, hz, register, drift)

    def accept(self, score: ChunkScore) -> None:
        if score.f0_hz:
            self._accepted_f0.append(score.f0_hz)
