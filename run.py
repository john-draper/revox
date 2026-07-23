#!/usr/bin/env python
"""
Cross-platform orchestrator for Revox.

Runs all stages in sequence:
  1. Transcription       (transcribe_whisperx.py)
  2. Profanity filtering (find_replacements.py)
  2b. Reference extraction (extract_reference.py)
  3. Audio generation    (generate_replacement_audio.py)
  4. Audio/video mux     (splice_audio.py)  -- audio censored, video copied

The final output is a video file with the SAME video stream as the input and a
CENSORED audio track. For audio-only inputs it behaves like the audiobook
pipeline and produces a censored audio file.

Usage:
    python run.py "path/to/video.mkv"
    python run.py "input/movie.mkv" --output-dir output --provider fish-speech
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BANNER = "=" * 78


def log(msg: str = "") -> None:
    print(msg, flush=True)


def banner(title: str) -> None:
    log()
    log(BANNER)
    log(f"  {title}")
    log(BANNER)


def run(cmd: list[str], **kwargs) -> int:
    """Run a command, streaming output to the terminal. Returns exit code."""
    log(f"  $ {' '.join(cmd)}")
    log("-" * 78)
    result = subprocess.run(cmd, **kwargs)
    log("-" * 78)
    return result.returncode


def check_tool(name: str) -> bool:
    """Return True if a CLI tool is on PATH."""
    return shutil.which(name) is not None


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------


def stage1_transcribe(audio: str, words_json: str) -> bool:
    banner("[STAGE 1/4] TRANSCRIPTION")
    log("  WhisperX word-level transcription (audio track of the video)")
    log()
    log(f"  Input:   {audio}")
    log(f"  Output:  {words_json}")
    import os
    whisper_device = os.environ.get("WHISPER_DEVICE", "cuda")
    whisper_model = os.environ.get("WHISPER_MODEL", "small")
    rc = run([
        sys.executable, "transcribe_whisperx.py", audio, "-o", words_json,
        "--model", whisper_model, "--device", whisper_device,
        "--batch-size", "8", "--compute-type", "int8",
    ])
    if rc != 0:
        log(f"\n  [FAILED] Stage 1 exited with code {rc}")
        return False
    if not Path(words_json).is_file():
        log(f"\n  [FAILED] Output JSON not found: {words_json}")
        return False
    log(f"\n  [OK] Stage 1 complete -> {words_json}")
    return True


def stage2_filter(words_json: str, replacements_json: str) -> tuple[bool, int]:
    banner("[STAGE 2/4] PROFANITY FILTERING")
    log(f"  Input:   {words_json}")
    log(f"  Output:  {replacements_json}")
    rc = run([sys.executable, "find_replacements.py", words_json, "-o", replacements_json])
    if rc != 0:
        log(f"\n  [FAILED] Stage 2 exited with code {rc}")
        return False, 0
    if not Path(replacements_json).is_file():
        log(f"\n  [FAILED] Output JSON not found: {replacements_json}")
        return False, 0

    count = 0
    try:
        with open(replacements_json, encoding="utf-8") as f:
            count = len(json.load(f))
    except Exception:
        pass
    log(f"\n  [OK] Stage 2 complete -> {replacements_json} ({count} replacements)")
    return True, count


def stage2b_reference(audio: str, words_json: str, ref_audio: str, ref_text: str) -> bool:
    banner("[STAGE 2b] REFERENCE EXTRACTION")
    log(f"  Audio:   {audio}")
    log(f"  Words:   {words_json}")
    log(f"  Output:  {ref_audio} + {ref_text}")
    rc = run([
        sys.executable, "extract_reference.py",
        "--audio", audio,
        "--words-json", words_json,
        "--output-audio", ref_audio,
        "--output-text", ref_text,
    ])
    if rc != 0:
        log(f"\n  [WARNING] Stage 2b failed (code {rc}). Continuing without voice cloning.")
        return False
    log(f"\n  [OK] Stage 2b complete -> reference clip saved")
    return True


def stage3_generate(
    replacements_json: str,
    audio_dir: str,
    provider: str,
    ref_audio: str | None,
    ref_text: str | None,
) -> bool:
    banner("[STAGE 3/4] AUDIO GENERATION")
    log(f"  Input:     {replacements_json}")
    log(f"  Output:    {audio_dir}")
    log(f"  Provider:  {provider}")
    if ref_audio and ref_text and Path(ref_audio).is_file() and Path(ref_text).is_file():
        log("  Voice cloning: ENABLED")
    else:
        log("  Voice cloning: DISABLED (no reference clip)")
    cmd = [
        sys.executable, "generate_replacement_audio.py",
        replacements_json,
        "--output-dir", audio_dir,
        "--provider", provider,
        "--skip-existing",
    ]
    if ref_audio and ref_text and Path(ref_audio).is_file() and Path(ref_text).is_file():
        cmd.extend(["--ref-audio", ref_audio, "--ref-text", ref_text])
    rc = run(cmd)
    if rc != 0:
        log(f"\n  [FAILED] Stage 3 exited with code {rc}")
        return False
    log(f"\n  [OK] Stage 3 complete -> {audio_dir}")
    return True


def stage4_splice(
    audio: str,
    replacements_json: str,
    audio_dir: str,
    final_output: str,
) -> bool:
    banner("[STAGE 4/4] AUDIO SPLICING / VIDEO MUX")
    log(f"  Original:     {audio}")
    log(f"  Replacements: {replacements_json}")
    log(f"  WAV dir:      {audio_dir}")
    log(f"  Output:       {final_output}")
    log(f"  (Video stream is copied losslessly; only audio is censored.)")
    rc = run([
        sys.executable, "splice_audio.py",
        audio,
        "--replacements-json", replacements_json,
        "--audio-dir", audio_dir,
        "--output", final_output,
    ])
    if rc != 0:
        log(f"\n  [FAILED] Stage 4 exited with code {rc}")
        return False
    if not Path(final_output).is_file():
        log(f"\n  [FAILED] Output file not found: {final_output}")
        return False
    log(f"\n  [OK] Stage 4 complete -> {final_output}")
    return True


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------


def preflight(audio: str) -> bool:
    banner("PRE-FLIGHT CHECKS")

    # Python
    log("  [check] Python...")
    if not check_tool("python"):
        log("          [FAILED] Python not found on PATH.")
        return False
    log("          [OK]")

    # ffmpeg
    log("  [check] ffmpeg...")
    if not check_tool("ffmpeg"):
        log("          [FAILED] ffmpeg not found on PATH.")
        log("                 Install: winget install Gyan.FFmpeg (Windows)")
        log("                          brew install ffmpeg (macOS)")
        log("                          sudo apt install ffmpeg (Linux)")
        return False
    log("          [OK]")

    # Input file
    log("  [check] Input file...")
    if not Path(audio).is_file():
        log(f"          [FAILED] Input file not found: {audio}")
        return False
    log(f"          [OK] {audio}")

    # Scripts
    log("  [check] Pipeline scripts...")
    scripts = [
        "transcribe_whisperx.py",
        "find_replacements.py",
        "extract_reference.py",
        "generate_replacement_audio.py",
        "splice_audio.py",
    ]
    missing = [s for s in scripts if not Path(s).is_file()]
    if missing:
        log(f"          [FAILED] Missing scripts: {', '.join(missing)}")
        return False
    log("          [OK] All 5 scripts found")

    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(
        description="Run the full Revox pipeline.",
    )
    p.add_argument("audio", help="Path to the input video file (e.g. input/movie.mkv)")
    p.add_argument(
        "--output-dir",
        default="output",
        help="Directory for all outputs (default: output)",
    )
    p.add_argument(
        "--provider",
        choices=["fish-speech", "elevenlabs", "pocket-tts", "pyttsx3"],
        default=None,
        help="TTS provider. Auto-detected from env vars if omitted.",
    )
    args = p.parse_args(argv)

    audio = args.audio
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    basename = Path(audio).stem

    # Determine the output extension. For video inputs, keep the same container
    # so players recognize it as video; otherwise fall back to .mkv.
    input_ext = Path(audio).suffix.lower()
    video_exts = {".mkv", ".mp4", ".m4v", ".mov", ".avi", ".webm", ".wmv", ".flv"}
    out_ext = input_ext if input_ext in video_exts else ".mkv"

    words_json = str(output_dir / f"{basename}.json")
    replacements_json = str(output_dir / f"{basename}_replacements.json")
    ref_audio = str(output_dir / "reference_voice.wav")
    ref_text = str(output_dir / "reference_text.txt")
    audio_dir = str(output_dir / "generated_audio")
    final_output = str(output_dir / f"{basename}_censored{out_ext}")

    # Auto-detect provider
    import os
    provider = args.provider
    if provider is None:
        if os.environ.get("FISH_SPEECH_URL"):
            provider = "fish-speech"
        elif os.environ.get("ELEVENLABS_API_KEY"):
            provider = "elevenlabs"
        else:
            provider = "pyttsx3"  # offline default, no API key needed

    # --- Pre-flight ---
    if not preflight(audio):
        banner("[FAILED] PRE-FLIGHT CHECKS FAILED")
        return 1

    # --- Config summary ---
    banner("PIPELINE CONFIGURATION")
    log(f"  Input file:       {audio}")
    log(f"  Base name:        {basename}")
    log(f"  Output folder:    {output_dir}")
    log(f"  TTS provider:     {provider}")
    log(f"  Output container: {out_ext}")
    log()
    log(f"  Stage 1  -> {words_json}")
    log(f"  Stage 2  -> {replacements_json}")
    log(f"  Stage 2b -> {ref_audio} + {ref_text}")
    log(f"  Stage 3  -> {audio_dir}/*.wav")
    log(f"  Stage 4  -> {final_output}")

    # --- Stage 1: Transcription ---
    if not stage1_transcribe(audio, words_json):
        return 1

    # --- Stage 2: Profanity filtering ---
    ok, count = stage2_filter(words_json, replacements_json)
    if not ok:
        return 1

    if count == 0:
        banner("[INFO] NO PROFANITY DETECTED")
        log("  No replacements needed. Copying original to output.")
        shutil.copy2(audio, final_output)
        banner("[SUCCESS] PIPELINE COMPLETE")
        log(f"  Final output: {final_output}")
        return 0

    # --- Stage 2b: Reference extraction ---
    ref_ok = stage2b_reference(audio, words_json, ref_audio, ref_text)
    ref_a = ref_audio if ref_ok else None
    ref_t = ref_text if ref_ok else None

    # --- Stage 3: Audio generation ---
    if not stage3_generate(replacements_json, audio_dir, provider, ref_a, ref_t):
        return 1

    # --- Stage 4: Splicing ---
    if not stage4_splice(audio, replacements_json, audio_dir, final_output):
        return 1

    # --- Success ---
    banner("[SUCCESS] PIPELINE COMPLETE")
    log(f"  Final censored video: {final_output}")
    log()
    log("  Intermediate files:")
    log(f"    Transcription JSON:  {words_json}")
    log(f"    Replacements JSON:   {replacements_json}")
    log(f"    Reference voice:     {ref_audio}")
    log(f"    Generated .wav dir:  {audio_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())