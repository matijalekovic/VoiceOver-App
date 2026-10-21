from __future__ import annotations

import numpy as np

from voice_studio import audio, text


def test_sentences_respect_abbreviations_and_languages():
    para = "Dr. Smith arrived at 5 p.m. today. ¿Dónde está la Sra. García? « Bonjour M. Dupont ! » Fin."
    assert text.split_sentences(para) == [
        "Dr. Smith arrived at 5 p.m. today.",
        "¿Dónde está la Sra. García?",
        "« Bonjour M. Dupont ! »",
        "Fin.",
    ]


def test_chunks_never_cross_paragraphs_and_respect_limit():
    script = "One. Two. Three.\n\n" + "A long clause, " * 40 + "end."
    pieces = text.chunk_text(script, 120)
    assert pieces[0] == text.Piece("One. Two. Three.", ends_paragraph=True)
    assert all(len(p.text) <= 120 for p in pieces)
    assert pieces[-1].ends_paragraph and not pieces[1].ends_paragraph


def test_sentence_segmentation_marks_paragraph_ends():
    pieces = text.segment_script(
        "First line. Second line.\nThird.\n\nNew paragraph.", "sentence", 300
    )
    assert [p.text for p in pieces] == ["First line.", "Second line.", "Third.", "New paragraph."]
    assert [p.ends_paragraph for p in pieces] == [False, False, True, True]


def test_analysis_flags_short_and_clipped_audio():
    sr = 24_000
    clipped = np.ones(sr * 2, dtype=np.float32)
    report = audio.analyse(clipped, sr)
    codes = {f["code"] for f in report.flags}
    assert {"too_short", "clipping"} <= codes


def test_speech_bounds_trim_silence():
    sr = 24_000
    tone = 0.5 * np.sin(np.linspace(0, 2000, sr * 2)).astype(np.float32)
    signal = np.concatenate([np.zeros(sr), tone, np.zeros(sr)])
    start, end = audio.speech_bounds(signal, sr, pad_s=0.1)
    assert 0.85 <= start <= 1.0 and 3.0 <= end <= 3.15


def test_join_inserts_pauses():
    sr = 1000
    joined = audio.join([(np.ones(100, np.float32), 0.5), (np.ones(100, np.float32), 9.0)], sr)
    assert len(joined) == 100 + 500 + 100  # the trailing pause is dropped
