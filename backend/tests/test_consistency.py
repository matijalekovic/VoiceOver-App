import numpy as np

from voice_studio.consistency import ChunkScore, Judge, median_f0

SR = 24_000


def tone(hz: float, seconds: float = 2.5) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    return (0.3 * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def test_median_f0():
    for hz in (85, 110, 220):
        assert abs(median_f0(tone(hz), SR) - hz) / hz < 0.02
    assert median_f0(np.zeros(SR, np.float32), SR) is None


def test_judge_flags_register_jumps_and_other_speakers():
    me = np.array([1, 0, 0], np.float32)
    judge = Judge(me, target_f0=95.0, sample_rate=SR)
    good = judge.score(tone(98), me)
    assert not good.outlier and good.similarity == 1.0
    judge.accept(good)
    octave = judge.score(tone(190), me)
    assert octave.outlier and octave.register_st > 11
    stranger = judge.score(tone(98), np.array([0.3, 1, 0], np.float32))
    assert stranger.outlier and stranger.similarity < 0.95
    # Within the speaker's range, but a jump from the chunks before it.
    jump = judge.score(tone(118), me)
    assert abs(jump.register_st) < 4 and jump.drift_st > 2.5 and jump.outlier
    assert good.rank > jump.rank > octave.rank


def test_unmeasured_scores_never_flag():
    assert not ChunkScore(None, None, None, None).outlier
