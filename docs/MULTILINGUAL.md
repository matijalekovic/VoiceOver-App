# One voice, many languages

How Voice Studio makes a speaker recorded in one language sound like the same person in others,
what was measured to get there, and what the model can and cannot do.

## How Qwen3-TTS Base clones a voice

Two things condition every generation:

1. **A speaker embedding** (an x-vector from the checkpoint's own speaker encoder): one vector
   that carries timbre. It is inserted as a single token in the prompt.
2. **Optionally, a recording to continue** ("in-context learning", ICL): the reference audio's
   codec tokens and its transcript go in front of the new text, and the model continues them.
   This carries far more than timbre: register, pace, microphone, energy and accent.

Fingerprint-only cloning (the embedding alone) is what lets an English speaker speak Spanish with
native pronunciation, but the model then invents everything the vector does not hold, afresh for
every chunk of text it is given.

## What was wrong: measured on a 69 s Spanish take of an English speaker

| | Speaker's English recordings | Spanish take (fingerprint, new seed per chunk) |
|---|---|---|
| Median pitch | 89–95 Hz | 97–125 Hz, by chunk |
| Pitch movement within a chunk | 4.2 semitones | 1.5–3.3 semitones |
| Brightness between chunks | steady | 1,800–3,300 Hz spectral centroid |
| Loudness | steady | last 15 s about 5 dB quieter |
| Speaker similarity (model's encoder) | — | 0.97 throughout |

The timbre held; the delivery did not. In seven fingerprint takes of the same Spanish text, six
sat within 1.3 semitones of the speaker (similarity 0.986–0.989) and one came out at 178 Hz,
an octave up, at 0.89: a different person. With a new seed per chunk, any chunk of a paragraph
can be that one.

## Four ways compared (the same Spanish script, five chunks each)

| Method | Pitch between chunks (sd) | Loudness between chunks (sd) | Similarity | Median pitch | Word error (Whisper) |
|---|---|---|---|---|---|
| A. Fingerprint, new seed per chunk (before) | 0.74 st | 2.1 dB | 0.986 | 93 Hz | 1.9 % |
| C. Continue the English recording ("carried" accent) | **0.09 st** | 0.5 dB | 0.987 | 95 Hz | 3.3 % |
| E. Continue a scored Spanish take ("native" accent) | 0.44 st | 0.7 dB | 0.986 | 96 Hz | 2.8 % |
| B. As E, but with an unlucky take | 0.24 st | 0.3 dB | **0.898** | **182 Hz** | 0.9 % |

B is the lesson: continuing one take makes every chunk alike, so the take must be chosen, not
rolled. Whisper understood all of them; it does not measure accent, so that is for a listener.

## What the app does now

- **Language profiles.** Adding a language to a cloned voice voices four takes of a short script
  natively from the fingerprint, scores each against the real recordings (speaker similarity and
  pitch register), and chooses the closest. Every generation in that language then continues the
  chosen take, with the speaker embedding pinned to the average of the real recordings, so the
  take lends accent and delivery while the identity stays the speaker's. You can listen and pick
  another take, or voice a new round.
- **Accent per language.** "Native pronunciation" (above) or "the speaker's own accent", which
  continues the original recording itself: the steadiest option, and how the person would sound
  speaking the language as a second language.
- **Delivery per language.** Expressiveness, speed and pitch can differ by language (Spanish
  scripts often run longer than English ones, for example); a generation's own settings still
  win.
- **An off-voice guard for every take.** Each chunk is scored as it is generated. A chunk more
  than 4 semitones from the speaker's register, more than 2.5 semitones from the chunks before
  it, or below 0.95 similarity is generated again with another seed (up to twice) and the best
  attempt kept. The scores are stored with each generation.
- **One seed per take** instead of a new seed for every chunk.

## Languages

Qwen3-TTS supports Chinese, English, Japanese, Korean, German, French, Russian, Portuguese,
Spanish and Italian; all ten are enabled by default.

**Serbian is experimental.** The checkpoint has no Serbian language token, so Serbian is spoken
with the token left out ("auto") and the script read in Latin letters (Cyrillic is
transliterated before synthesis). Measured on the same speaker, two takes each, Whisper word
error against the script:

| Serbian setup | Word error | Similarity |
|---|---|---|
| Latin script, no language token (what the app does) | 18–26 % | 0.99 |
| Latin script, continuing the English recording (own accent) | 18 % | 0.99 |
| Cyrillic, no language token | 50–58 % | 0.99 |
| Cyrillic with the Russian token | 53–61 % | 0.99 |

Part of the Latin error is word splitting ("daleko vodi") and assimilation that is how the words
are spoken ("obštine"); the Cyrillic and Russian takes reduce vowels the Russian way
("vremina", "duga"). It is understandable, not native. A Serbian recording of the speaker would
help most: cloning that recording in Serbian continues his own Serbian pronunciation.

Chinese, by contrast, came out at 0 % character error with similarity 0.99, natively and with
the speaker's own accent alike.

Language character (Mandarin's tones, French liaison, Spanish's syllable timing) is learned by
the model from native speakers. It is not something to configure; what a profile controls is
how much of the speaker carries into it.

## Beyond this: fine-tuning

Qwen3-TTS publishes single-speaker fine-tuning for the Base checkpoints
([QwenLM/Qwen3-TTS `finetuning/`](https://github.com/QwenLM/Qwen3-TTS/tree/main/finetuning)):
JSONL of (audio, transcript, one fixed reference clip), turned into a "custom voice" speaker.
Fine-tuned on the speaker's English (the guide gives no minimum; an hour of clean narration
is a reasonable first target), the identity is learned into the weights
rather than read from one vector, which is the strongest consistency fix there is. It needs an
NVIDIA GPU (the scripts use CUDA and FlashAttention) and is not available on MLX, so it would be
done once on a rented GPU and the checkpoint converted for the Mac. Whether it helps other
languages as much as English has to be measured; it cannot add a language the model was not
trained on, such as Serbian, without speech data in that language.

## Script hygiene

What the model reads, it speaks: headings like "01" and notes like "Here it is" in a script are
voiced. Numbers and symbols ("25,8 %") are read by the model's own rules for the language and are
worth checking on a first listen.
