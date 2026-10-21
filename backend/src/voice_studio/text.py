"""Splitting scripts into paragraphs, sentences, project segments and synthesis chunks."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Abbreviations that end with a period but do not end a sentence (EN, FR, ES).
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "e.g", "i.e", "approx",
    "no", "fig", "vol", "inc", "ltd", "co", "mt", "jan", "feb", "mar", "apr", "jun", "jul",
    "aug", "sep", "sept", "oct", "nov", "dec",
    "m", "mme", "mlle", "mm", "env", "cf", "p.ex",
    "sra", "srta", "dra", "ud", "uds", "p.ej", "pág", "núm",
}  # fmt: skip

# Terminal punctuation, then closing quotes/brackets (French puts a space before »).
_SENTENCE_END = re.compile(r"([.!?…]+(?:\s?[\"'»”’)\]])*)(\s+)")
_CLAUSE_BREAK = re.compile(r"(?<=[,;:—–])\s+")


def normalise(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    return re.sub(r"[ \t]+", " ", text).strip()


def split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", normalise(text)) if p.strip()]


def split_sentences(paragraph: str) -> list[str]:
    """Split one paragraph into sentences. Single line breaks are kept as boundaries,
    because voiceover scripts are usually written one thought per line."""
    sentences: list[str] = []
    for line in paragraph.split("\n"):
        line = line.strip()
        if not line:
            continue
        start = 0
        for match in _SENTENCE_END.finditer(line):
            end = match.end(1)
            candidate = line[start:end]
            last_word = candidate.rstrip(".!?…\"'»”’)] ").rsplit(" ", 1)[-1].lower()
            following = line[match.end() :]
            if match.group(1).startswith(".") and (
                last_word in _ABBREVIATIONS
                or (len(last_word) == 1 and last_word.isalpha())
                or (following[:1].islower())
            ):
                continue
            sentences.append(candidate.strip())
            start = match.end()
        tail = line[start:].strip()
        if tail:
            sentences.append(tail)
    return sentences


def _split_long(sentence: str, max_chars: int) -> list[str]:
    if len(sentence) <= max_chars:
        return [sentence]
    parts: list[str] = []
    current = ""
    for clause in _CLAUSE_BREAK.split(sentence):
        if current and len(current) + 1 + len(clause) > max_chars:
            parts.append(current)
            current = clause
        else:
            current = f"{current} {clause}".strip()
    if current:
        parts.append(current)
    # A single clause can still be too long; fall back to word boundaries.
    result: list[str] = []
    for part in parts:
        while len(part) > max_chars:
            cut = part.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            result.append(part[:cut].strip())
            part = part[cut:].strip()
        if part:
            result.append(part)
    return result


@dataclass(frozen=True)
class Piece:
    text: str
    ends_paragraph: bool


def chunk_text(text: str, max_chars: int) -> list[Piece]:
    """Group sentences into chunks of at most max_chars, never across paragraphs."""
    pieces: list[Piece] = []
    for paragraph in split_paragraphs(text):
        chunks: list[str] = []
        current = ""
        for sentence in split_sentences(paragraph):
            for part in _split_long(sentence, max_chars):
                if current and len(current) + 1 + len(part) > max_chars:
                    chunks.append(current)
                    current = part
                else:
                    current = f"{current} {part}".strip()
        if current:
            chunks.append(current)
        for index, chunk in enumerate(chunks):
            pieces.append(Piece(chunk, ends_paragraph=index == len(chunks) - 1))
    return pieces


def segment_script(text: str, mode: str, max_chars: int) -> list[Piece]:
    """Project segments: one per sentence or one per paragraph (paragraphs that are too long
    for a single synthesis pass are split at sentence boundaries)."""
    if mode == "sentence":
        pieces: list[Piece] = []
        for paragraph in split_paragraphs(text):
            sentences = [p for s in split_sentences(paragraph) for p in _split_long(s, max_chars)]
            for index, sentence in enumerate(sentences):
                pieces.append(Piece(sentence, ends_paragraph=index == len(sentences) - 1))
        return pieces
    return chunk_text(text, max_chars)
