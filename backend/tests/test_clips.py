from __future__ import annotations

import numpy as np

from voice_studio.clips import MAX_CLIP_S, demo_script, pick_candidates

SR = 24_000


def _speech(seconds: float) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    return (0.3 * np.sin(2 * np.pi * 180 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t))).astype(
        np.float32
    )


def _segments(starts: list[float], length: float = 3.0) -> list[dict]:
    return [
        {
            "start": s,
            "end": s + length,
            "text": f"Line {i}.",
            "words": [{"start": s, "end": s + length, "word": "x", "probability": 0.9}],
        }
        for i, s in enumerate(starts)
    ]


def test_clips_stay_within_limits_and_do_not_overlap():
    samples = _speech(90)
    recordings = [("a", _segments([1 + 3.5 * k for k in range(24)]), samples, SR)]
    picked = pick_candidates(recordings)
    assert len(picked) == 3
    for clip in picked:
        assert 10 <= clip.end_s - clip.start_s <= MAX_CLIP_S
    spans = sorted((c.start_s, c.end_s) for c in picked)
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:], strict=False))


def test_long_pauses_split_clips_and_each_recording_is_tried_first():
    samples = _speech(60)
    # A 6-second pause after the third sentence: no clip may span it.
    starts = [1, 4.5, 8, 17, 20.5, 24, 27.5, 31]
    picked = pick_candidates(
        [("a", _segments(starts), samples, SR), ("b", _segments(starts), samples, SR)]
    )
    assert {c.reference_id for c in picked[:2]} == {"a", "b"}
    for clip in picked:
        assert not (clip.start_s < 11.5 < clip.end_s)


def test_short_recordings_fall_back_to_shorter_clips():
    samples = _speech(8)
    picked = pick_candidates([("a", _segments([0.5, 4.0]), samples, SR)])
    assert picked and picked[0].end_s - picked[0].start_s < 10


def test_demo_script_falls_back_to_english():
    assert demo_script("croatian") == demo_script("english")
    assert demo_script("french") != demo_script("english")
