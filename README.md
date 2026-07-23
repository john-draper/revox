# Revox

**Re**write the **Vox** — automatically detect profanity in video files and replace each word with a clean euphemism using AI text-to-speech with **voice cloning**. The video stream is preserved losslessly; only the audio track is edited and re-written.

The final output is a video file with identical picture quality and a censored soundtrack.

Revox uses [WhisperX](https://github.com/m-bain/whisperX) for GPU-accelerated transcription with accurate word-level timestamps, then generates replacement audio via [Fish Speech](https://fish.audio) (or ElevenLabs), and splices the replacements back into the audio, muxing the censored audio with the original video stream.

```
video.mkv ──▶ [1. Transcribe] ──▶ words.json
                                        │
                 ┌──────────────────────┘
                 ▼
          [2. Find Replacements] ──▶ replacements.json
                                        │
          [2b. Extract Reference] ◀─────┤
                 │                      │
                 ▼                      ▼
          reference_voice.wav ──▶ [3. Generate Audio] ──▶ *.wav files
                                                                 │
                 ┌───────────────────────────────────────────────┘
                 ▼
          [4. Splice + Mux] ──▶ video_censored.mkv
            (censored audio + ORIGINAL video stream)
```

## TTS Providers

| Provider | Voice Cloning | Offline | Setup |
|----------|:---:|:---:|-------|
| **pyttsx3** (default) | ❌ | ✅ | None — uses Windows SAPI5 |
| **Fish Speech** | ✅ | ✅ (self-hosted) | Run Fish Speech server |
| **ElevenLabs** | ✅ | ❌ (cloud) | API key required |
| **Pocket-TTS** | ✅ | ✅ (local GPU) | `pip install pocket-tts` |

## Quick Start

### Prerequisites

1. **Python 3.10+** on PATH
2. **ffmpeg** on PATH — `winget install Gyan.FFmpeg` (Windows) or `brew install ffmpeg` (macOS)
3. **NVIDIA GPU** (recommended) — the pipeline falls back to CPU but it's ~50x slower

### Installation

```bash
# 1. Install PyTorch for your CUDA version (GPU only)
#    For CUDA 11.8:
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu118
#    For other versions: https://pytorch.org/get-started/locally/

# 2. Install the remaining dependencies
pip install -r requirements.txt
```

### Configure API Keys (optional)

Copy `.env.example` to `.env` and fill in your TTS provider details. If you skip this, Revox defaults to the offline `pyttsx3` engine.

```bash
copy .env.example .env        (Windows)
cp .env.example .env          (macOS/Linux)
```

### Place Your Videos

Drop video files into the `input/` folder:

```
input/movie.mkv
```

### Run

```bash
# Single file:
python run.py "input/movie.mkv"

# Batch process all videos in input/:
python run.bat            # Windows
python run_all.py         # Cross-platform

# GUI:
python gui.py
```

The censored video is saved to `output/` — same video quality, censored audio.

---

## Pipeline Stages

### Stage 1: Transcription (`transcribe_whisperx.py`)

Transcribes the audio track with WhisperX. ffmpeg extracts the audio stream automatically from any video container.

```bash
python transcribe_whisperx.py "input/video.mkv" -o output/words.json
```

| Option | Default | Notes |
|--------|---------|-------|
| `-o PATH` | `<input>.json` | Output JSON path |
| `--model NAME` | `small` | Whisper model (smaller = faster/less accurate) |
| `--device D` | `cuda` | `cuda` or `cpu` |
| `--compute-type T` | `int8` | `float16` for higher precision |

### Stage 2: Profanity Filtering (`find_replacements.py`)

Matches transcribed words against a 100+ entry replacement dictionary.

```bash
python find_replacements.py output/words.json -o output/replacements.json
```

Edit the `REPLACEMENTS` dictionary in `find_replacements.py` to customize.

### Stage 3: Audio Generation (`generate_replacement_audio.py`)

Generates replacement `.wav` files for each profanity word.

```bash
python generate_replacement_audio.py output/replacements.json \
    --output-dir output/generated_audio --provider pyttsx3
```

### Stage 4: Audio Splice + Video Mux (`splice_audio.py`)

Builds the censored audio track (each replacement trimmed/stretched to exactly match the original word duration), then muxes it with the **original video stream** (copied losslessly).

```bash
python splice_audio.py "input/video.mkv" \
    --replacements-json output/replacements.json \
    --audio-dir output/generated_audio \
    --output output/video_censored.mkv
```

If ffmpeg can't stream-copy the video, set `VIDEO_REENCODE=1` to re-encode.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FISH_SPEECH_URL` | `http://localhost:8080/v1/tts` | Fish Speech TTS endpoint |
| `ELEVENLABS_API_KEY` | — | ElevenLabs API key |
| `VIDEO_REENCODE` | `0` | Set to `1` to re-encode video |
| `WHISPER_DEVICE` | `cuda` | `cuda` or `cpu` |
| `WHISPER_MODEL` | `small` | Whisper model size |

---

## Troubleshooting

- **Audio out of sync** — Revox time-stretches each replacement to exactly match the original word's duration. If sync issues persist, ensure you're using the latest `splice_audio.py`.
- **CUDA crashes / cuDNN errors** — Install cuDNN 8 DLLs (`pip install nvidia-cudnn-cu11==8.9.4.25`) and copy them to your `torch/lib/` folder. Or fall back to CPU with `--device cpu`.
- **`pyttsx3` hangs** — Revox runs pyttsx3 in separate subprocesses to avoid the Windows COM deadlock. Each word takes ~2-3 seconds.
- **FFmpeg not found** — `winget install Gyan.FFmpeg`, then reopen your terminal.

## License

MIT — see [LICENSE](LICENSE).