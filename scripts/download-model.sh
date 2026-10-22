#!/usr/bin/env bash
# Downloads a checkpoint straight into the app's model folder (the in-app Settings → Models
# button does the same). Usage: scripts/download-model.sh [model-id]
#   qwen3-tts-1.7b-base-bf16   (default, quality)
#   qwen3-tts-1.7b-base-8bit   (quantised; compare with bf16 before relying on it)
#   qwen3-tts-0.6b-base-bf16   (lightweight)
#   qwen3-tts-1.7b-voice-design-bf16 (designs a new voice from a description)
#   whisper-large-v3-turbo     (speech recognition, used when cloning a voice)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL="${1:-qwen3-tts-1.7b-base-bf16}"
case "$MODEL" in
  qwen3-tts-1.7b-base-bf16) REPO="mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16" ;;
  qwen3-tts-1.7b-base-8bit) REPO="mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit" ;;
  qwen3-tts-0.6b-base-bf16) REPO="mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16" ;;
  qwen3-tts-1.7b-voice-design-bf16) REPO="mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16" ;;
  whisper-large-v3-turbo) REPO="mlx-community/whisper-large-v3-turbo-asr-fp16" ;;
  *) echo "Unknown model id: $MODEL" >&2; exit 1 ;;
esac
DEST="${VOICE_STUDIO_DATA_DIR:-$HOME/Library/Application Support/1PAX Voice Studio}/models/$MODEL"
mkdir -p "$DEST"
echo "Downloading $REPO to $DEST"
cd "$ROOT/backend"
# No Xet chunk cache: it would keep a second copy of the weights in ~/.cache.
HF_XET_CHUNK_CACHE_SIZE_BYTES=0 uv run hf download "$REPO" --local-dir "$DEST"
echo "Done. Voice Studio picks it up in Settings → Models."
