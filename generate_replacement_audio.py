#!/usr/bin/env python
"""
Read the filtered replacements JSON (output of find_replacements.py), use a TTS
provider to generate the audio for each replacement word, and save each
generated word as an individual .wav file.

Providers:
    - fish-speech  : Fish Speech API (self-hosted, voice cloning via msgpack)
    - elevenlabs   : ElevenLabs API (cloud-based)
    - pocket-tts   : Kyutai Pocket-TTS (offline, local voice cloning, free)

Supports VOICE CLONING: provide a reference audio clip and its transcript, and
all generated words will use the cloned voice for consistency.

Naming scheme:  <start_ms padded to 8>_<end_ms padded to 8>_<replacement>.wav

Requirements:
    - requests, ormsgpack  (pip install requests ormsgpack)  [for fish-speech]
    - pocket-tts           (pip install pocket-tts)           [for pocket-tts]
    - Fish Speech server running (default: http://localhost:8080/v1/tts)

Example:
    python generate_replacement_audio.py replacements.json --provider fish-speech \\
        --ref-audio output/reference_voice.wav \\
        --ref-text output/reference_text.txt
"""

import argparse
import io
import json
import os
import sys
import time
import wave
from pathlib import Path

import ormsgpack
import requests

# --------------------------------------------------------------------------- #
# API configuration (env var fallbacks)
# --------------------------------------------------------------------------- #
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
ELEVENLABS_MODEL_ID = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")

FISH_SPEECH_URL = os.environ.get("FISH_SPEECH_URL", "http://localhost:8080/v1/tts")
FISH_SPEECH_API_KEY = os.environ.get("FISH_SPEECH_API_KEY", "")
FISH_SPEECH_FORMAT = "wav"


def log(msg: str) -> None:
    print(msg, flush=True)


def load_replacements(path: str) -> list[dict]:
    in_path = Path(path)
    if not in_path.is_file():
        raise FileNotFoundError(f"Input JSON not found: {in_path}")
    with in_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(
            f"Expected a JSON list of replacement objects, got {type(data).__name__}."
        )
    return data


def format_filename(start: float, end: float, replacement: str) -> str:
    """Format the output .wav filename based on start/end times and replacement text."""
    start_ms = int(start * 1000)
    end_ms = int(end * 1000)
    safe_replacement = "".join(
        c if c.isalnum() or c in ("-", "_") else "_" for c in replacement
    ).strip("_")
    return f"{start_ms:08d}_{end_ms:08d}_{safe_replacement}.wav"


def generate_elevenlabs(
    text: str,
    api_key: str,
    voice_id: str,
    model_id: str,
) -> bytes:
    """Generate audio using the ElevenLabs API."""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
        },
    }
    params = {"output_format": "pcm_44100"}
    response = requests.post(url, json=payload, headers=headers, params=params, timeout=60)
    response.raise_for_status()
    return response.content


def generate_fish_speech(
    text: str,
    base_url: str,
    api_key: str,
    format: str,
    ref_audio_bytes: bytes | None = None,
    ref_text: str | None = None,
) -> bytes:
    """Generate audio using the Fish Speech API with voice cloning support.

    Args:
        text: The text to synthesize.
        base_url: Fish Speech TTS endpoint (e.g., http://localhost:8080/v1/tts).
        api_key: Fish Speech API key (optional).
        format: Output format (e.g., "wav").
        ref_audio_bytes: Reference audio bytes for voice cloning (optional).
        ref_text: Reference transcript text for voice cloning (optional).

    Returns:
        The generated audio as raw bytes.
    """
    # Build request payload
    payload: dict = {
        "text": text,
        "format": format,
        "references": [],
        "chunk_length": 200,
        "normalize": True,
    }

    # Add reference audio for voice cloning if provided
    if ref_audio_bytes and ref_text:
        payload["references"] = [
            {
                "audio": ref_audio_bytes,
                "text": ref_text,
            }
        ]
        log(f"    [voice-clone] Using reference audio ({len(ref_audio_bytes) / 1024:.1f} KB)")

    headers = {"content-type": "application/msgpack"}
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"

    # Use msgpack for binary reference audio support
    packed = ormsgpack.packb(payload)

    response = requests.post(
        f"{base_url}?format=msgpack",
        data=packed,
        headers=headers,
        timeout=60,
    )
    response.raise_for_status()
    return response.content


def save_wav(audio_bytes: bytes, output_path: Path) -> None:
    """Save raw audio bytes to a file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as f:
        f.write(audio_bytes)


# --------------------------------------------------------------------------- #
# Pocket-TTS (offline, local voice cloning)
# --------------------------------------------------------------------------- #

_POCKET_TTS_MODEL = None
_POCKET_TTS_VOICE_STATE = None


def init_pocket_tts(ref_audio_path: str | None = None) -> None:
    """Load the Pocket-TTS model and (optionally) compute the voice clone state."""
    global _POCKET_TTS_MODEL, _POCKET_TTS_VOICE_STATE
    import torch

    log("[pocket-tts] Loading model (first run downloads ~1.5 GB)...")
    from pocket_tts import TTSModel

    device = "cuda" if torch.cuda.is_available() else "cpu"
    log(f"[pocket-tts] Using device: {device}")
    _POCKET_TTS_MODEL = TTSModel.load_model()
    _POCKET_TTS_MODEL.to(device)
    _POCKET_TTS_MODEL.eval()
    log(f"[pocket-tts] Model loaded. Sample rate: {_POCKET_TTS_MODEL.sample_rate} Hz")

    if ref_audio_path:
        log(f"[pocket-tts] Computing voice clone state from {ref_audio_path}...")
        _POCKET_TTS_VOICE_STATE = _POCKET_TTS_MODEL.get_state_for_audio_prompt(
            ref_audio_path, truncate=False
        )
        log("[pocket-tts] Voice clone state ready.")
    else:
        log("[pocket-tts] No reference audio — using default voice.")


def generate_pocket_tts(text: str) -> bytes:
    """Generate audio using Pocket-TTS with voice cloning. Returns WAV bytes."""
    global _POCKET_TTS_MODEL, _POCKET_TTS_VOICE_STATE
    import torch

    if _POCKET_TTS_MODEL is None:
        raise RuntimeError("Pocket-TTS not initialized. Call init_pocket_tts() first.")

    device = next(_POCKET_TTS_MODEL.parameters()).device

    with torch.no_grad():
        audio_tensor = _POCKET_TTS_MODEL.generate_audio(
            model_state=_POCKET_TTS_VOICE_STATE,
            text_to_generate=text,
        )

    if audio_tensor.dim() == 1:
        audio_tensor = audio_tensor.unsqueeze(0)
    audio_tensor = audio_tensor.cpu().float().clamp(-1, 1)

    sr = _POCKET_TTS_MODEL.sample_rate
    pcm = (audio_tensor * 32767).to(torch.int16)
    channels = pcm.shape[0]

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.numpy().tobytes())
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# pyttsx3 (Windows SAPI5 offline TTS, no voice cloning but reliable/free)
# --------------------------------------------------------------------------- #

_PYTTSX3_HELPER_SCRIPT = """
import sys, os
import pyttsx3
text = sys.argv[1]
out = sys.argv[2]
e = pyttsx3.init()
e.setProperty("rate", 160)
e.save_to_file(text, out)
e.runAndWait()
e.stop()
"""


def generate_pyttsx3(text: str) -> bytes:
    """Generate audio using pyttsx3 in a SEPARATE subprocess.

    pyttsx3's runAndWait() deadlocks after the first call when used in-process
    (Windows COM/SAPI5 issue). Running each word in its own subprocess avoids this.
    """
    import os
    import subprocess
    import tempfile

    if not hasattr(generate_pyttsx3, "_helper_path"):
        helper_path = Path(tempfile.gettempdir()) / "_tts_helper.py"
        helper_path.write_text(_PYTTSX3_HELPER_SCRIPT.strip(), encoding="utf-8")
        generate_pyttsx3._helper_path = str(helper_path)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [sys.executable, generate_pyttsx3._helper_path, text, tmp_path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0 or not os.path.exists(tmp_path):
            raise RuntimeError(f"pyttsx3 subprocess failed: {result.stderr[:200]}")
        with open(tmp_path, "rb") as f:
            wav_bytes = f.read()
        os.unlink(tmp_path)
        return wav_bytes
    except subprocess.TimeoutExpired:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise RuntimeError("pyttsx3 subprocess timed out")


def process_replacement(
    entry: dict,
    output_dir: Path,
    provider: str,
    elevenlabs_key: str,
    elevenlabs_voice: str,
    elevenlabs_model: str,
    fish_url: str,
    fish_key: str,
    fish_format: str,
    ref_audio_bytes: bytes | None = None,
    ref_text: str | None = None,
) -> str | None:
    """Generate audio for a single replacement entry."""
    replacement = entry.get("replacement", "")
    start = entry.get("start", 0.0)
    end = entry.get("end", 0.0)

    if not replacement:
        log(f"  [skip] Empty replacement text for entry: {entry}")
        return None

    filename = format_filename(start, end, replacement)
    output_path = output_dir / filename

    try:
        log(f"  [generate] '{replacement}' -> {filename}")
        if provider == "elevenlabs":
            audio_bytes = generate_elevenlabs(
                text=replacement,
                api_key=elevenlabs_key,
                voice_id=elevenlabs_voice,
                model_id=elevenlabs_model,
            )
        elif provider == "fish-speech":
            audio_bytes = generate_fish_speech(
                text=replacement,
                base_url=fish_url,
                api_key=fish_key,
                format=fish_format,
                ref_audio_bytes=ref_audio_bytes,
                ref_text=ref_text,
            )
        elif provider == "pocket-tts":
            audio_bytes = generate_pocket_tts(text=replacement)
        elif provider == "pyttsx3":
            audio_bytes = generate_pyttsx3(text=replacement)
        else:
            raise ValueError(f"Unknown provider: {provider}")

        save_wav(audio_bytes, output_path)
        log(f"    [saved] {output_path} ({len(audio_bytes) / 1024:.1f} KB)")
        return str(output_path)

    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        body = exc.response.text[:200] if exc.response is not None else ""
        log(f"    [error] HTTP {status}: {exc} | body: {body}")
        return None
    except requests.RequestException as exc:
        log(f"    [error] Request failed: {exc}")
        return None
    except Exception as exc:
        log(f"    [error] {type(exc).__name__}: {exc}")
        return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate replacement audio via Fish Speech (with voice cloning) or ElevenLabs.",
    )
    p.add_argument(
        "input",
        help="Path to the filtered replacements JSON from find_replacements.py",
    )
    p.add_argument(
        "-o", "--output-dir",
        default="output/generated_audio",
        help="Directory to save generated .wav files (default: output/generated_audio).",
    )
    p.add_argument(
        "--provider",
        choices=["elevenlabs", "fish-speech", "pocket-tts", "pyttsx3"],
        default="fish-speech",
        help="TTS provider (default: fish-speech). pocket-tts is offline/free. pyttsx3 uses Windows SAPI5.",
    )
    p.add_argument(
        "--voice",
        default=None,
        help="Voice ID (overrides env vars). Not needed with --ref-audio.",
    )
    p.add_argument(
        "--ref-audio",
        default=None,
        help="Path to reference audio file for voice cloning. "
             "When provided with --ref-text, all generated audio will clone this voice.",
    )
    p.add_argument(
        "--ref-text",
        default=None,
        help="Path to reference transcript text file for voice cloning.",
    )
    p.add_argument(
        "--rate-limit",
        type=float,
        default=0.0,
        help="Delay in seconds between API calls (default: 0.0).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Process the JSON without calling the API.",
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip generating audio for files that already exist.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    provider = args.provider

    # Load reference audio for voice cloning
    ref_audio_bytes: bytes | None = None
    ref_text: str | None = None

    if args.ref_audio and args.ref_text:
        ref_audio_path = Path(args.ref_audio)
        ref_text_path = Path(args.ref_text)

        if not ref_audio_path.is_file():
            log(f"[error] Reference audio not found: {ref_audio_path}")
            return 2
        if not ref_text_path.is_file():
            log(f"[error] Reference text not found: {ref_text_path}")
            return 2

        ref_audio_bytes = ref_audio_path.read_bytes()
        ref_text = ref_text_path.read_text(encoding="utf-8").strip()
        log(f"[voice-clone] Reference audio: {ref_audio_path} ({len(ref_audio_bytes) / 1024:.1f} KB)")
        log(f"[voice-clone] Reference text: \"{ref_text[:80]}...\"")
        log(f"[voice-clone] ALL generated audio will use this cloned voice!")
    elif provider == "fish-speech":
        log("[warning] No --ref-audio/--ref-text provided. Voice will be RANDOMIZED per call!")

    # Resolve voice ID overrides.
    voice = args.voice or (ELEVENLABS_VOICE_ID if provider == "elevenlabs" else None)

    try:
        replacements = load_replacements(args.input)
    except FileNotFoundError as exc:
        log(f"[error] {exc}")
        return 2
    except (ValueError, json.JSONDecodeError) as exc:
        log(f"[error] {type(exc).__name__}: {exc}")
        return 1

    log(f"[input] Loaded {len(replacements)} replacement(s) from {args.input}")
    log(f"[provider] Using {provider}")
    log(f"[output] Saving .wav files to {Path(args.output_dir)}")
    if args.skip_existing:
        log(f"[option] --skip-existing enabled")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        log("[dry-run] Skipping API calls. Showing planned filenames only.")
        for entry in replacements:
            replacement = entry.get("replacement", "")
            start = entry.get("start", 0.0)
            end = entry.get("end", 0.0)
            filename = format_filename(start, end, replacement)
            log(f"  [dry-run] '{replacement}' -> {output_dir / filename}")
        return 0

    # Initialize pocket-tts model if needed (loads once, reused for all words)
    if provider == "pocket-tts":
        pocket_ref = args.ref_audio if args.ref_audio else None
        try:
            init_pocket_tts(ref_audio_path=pocket_ref)
        except Exception as exc:
            log(f"[error] Failed to initialize Pocket-TTS: {type(exc).__name__}: {exc}")
            return 1

    success_count = 0
    failed_count = 0
    skipped_count = 0

    for i, entry in enumerate(replacements):
        replacement_text = entry.get("replacement", "")
        start_t = entry.get("start", 0.0)
        end_t = entry.get("end", 0.0)

        # Check if file already exists (for --skip-existing)
        if args.skip_existing and replacement_text:
            expected_filename = format_filename(start_t, end_t, replacement_text)
            expected_path = output_dir / expected_filename
            if expected_path.is_file():
                log(f"[{i + 1}/{len(replacements)}] [skip-existing] {expected_filename}")
                skipped_count += 1
                success_count += 1
                continue

        log(f"[{i + 1}/{len(replacements)}] Processing replacement...")
        result = process_replacement(
            entry=entry,
            output_dir=output_dir,
            provider=provider,
            elevenlabs_key=ELEVENLABS_API_KEY,
            elevenlabs_voice=voice if provider == "elevenlabs" else "",
            elevenlabs_model=ELEVENLABS_MODEL_ID,
            fish_url=FISH_SPEECH_URL,
            fish_key=FISH_SPEECH_API_KEY,
            fish_format=FISH_SPEECH_FORMAT,
            ref_audio_bytes=ref_audio_bytes,
            ref_text=ref_text,
        )
        if result is not None:
            success_count += 1
        else:
            failed_count += 1

        # Rate limit between API calls.
        if args.rate_limit > 0 and i < len(replacements) - 1:
            time.sleep(args.rate_limit)

    log(f"[done] Generated {success_count} audio file(s) in {output_dir}.")
    if skipped_count:
        log(f"[done] {skipped_count} file(s) skipped (already existed).")
    if failed_count:
        log(f"[done] {failed_count} replacement(s) failed. See errors above.")
    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())