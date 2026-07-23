#!/usr/bin/env python
"""
Extract a reference audio clip from a video (or audio) file for voice cloning.

This script:
  1. Finds a good ~20-30 second segment of continuous speech (no profanity)
  2. Extracts it using ffmpeg (ffmpeg reads the audio track directly from any
     video container)
  3. Saves the corresponding transcript text for the Fish Speech reference

Usage:
    python extract_reference.py --audio input/movie.mkv --words-json words.json
    python extract_reference.py --audio input/movie.mkv --words-json words.json --start 1200
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Words to avoid in the reference clip (profanity that would be replaced)
SKIP_WORDS = {
    "damn", "dammit", "goddammit", "hell", "god", "ass", "asshole", "jackass",
    "dumbass", "badass", "shit", "bullshit", "fuck", "fucking", "bitch",
    "cunt", "twat", "cocksucker", "pussy", "dang", "heck", "gosh", "bench",
    "darn", "shucks", "butt", "dangit", "crap",
}


def log(msg: str) -> None:
    print(msg, flush=True)


def clean_word(w: str) -> str:
    """Lowercase and strip punctuation."""
    import string
    return w.strip(string.punctuation).lower()


def find_good_reference_segment(
    words: list[dict],
    target_start: float = 1200.0,
    min_duration: float = 20.0,
    max_duration: float = 30.0,
) -> tuple[int, int] | None:
    """Find a segment of continuous narration without profanity.

    Args:
        words: Word-level transcription list.
        target_start: Preferred start time in seconds.
        min_duration: Minimum segment duration in seconds.
        max_duration: Maximum segment duration in seconds.

    Returns:
        Tuple of (start_index, end_index) into the words list, or None.
    """
    # Find starting point near target_start
    start_search = max(0, next(
        (i for i, w in enumerate(words) if w["start"] >= target_start), 0
    ))

    # Try multiple starting points
    for offset in range(0, len(words) - 100, 50):
        base_idx = start_search + offset
        if base_idx >= len(words):
            break

        seg_start_time = words[base_idx]["start"]

        # Find the end of a good segment
        end_idx = base_idx
        has_profanity = False

        while end_idx < len(words):
            w = words[end_idx]
            seg_duration = w["end"] - seg_start_time

            # Check if this word is profanity
            if clean_word(w["word"]) in SKIP_WORDS:
                has_profanity = True
                break

            # Check if we have a long enough segment
            if seg_duration >= min_duration:
                # Extend a bit more for better voice reference (up to max_duration)
                while end_idx + 1 < len(words):
                    next_dur = words[end_idx + 1]["end"] - seg_start_time
                    if next_dur > max_duration:
                        break
                    if clean_word(words[end_idx + 1]["word"]) in SKIP_WORDS:
                        break
                    end_idx += 1
                return (base_idx, end_idx + 1)

            end_idx += 1

    return None


def extract_audio_segment(
    audio_path: str,
    start_s: float,
    duration_s: float,
    output_path: str,
) -> bool:
    """Extract a segment from the video/audio file using ffmpeg.

    ffmpeg automatically selects the audio stream from a video container.

    Args:
        audio_path: Source video/audio file.
        start_s: Start time in seconds.
        duration_s: Duration in seconds.
        output_path: Output WAV path.

    Returns:
        True if successful.
    """
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start_s:.3f}",
        "-t", f"{duration_s:.3f}",
        "-i", audio_path,
        "-vn",                 # ignore any video stream
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", "1",  # Mono for reference (works better with Fish Speech)
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log(f"[error] ffmpeg failed: {result.stderr[-300:]}")
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract a reference audio clip for voice cloning."
    )
    parser.add_argument(
        "--audio",
        required=True,
        help="Source video/audio file",
    )
    parser.add_argument(
        "--words-json",
        required=True,
        help="Word-level transcription JSON from transcribe_whisperx.py",
    )
    parser.add_argument(
        "--start",
        type=float,
        default=1200.0,
        help="Preferred start time in seconds (default: 1200)",
    )
    parser.add_argument(
        "--min-duration",
        type=float,
        default=20.0,
        help="Minimum reference duration in seconds (default: 20)",
    )
    parser.add_argument(
        "--max-duration",
        type=float,
        default=30.0,
        help="Maximum reference duration in seconds (default: 30)",
    )
    parser.add_argument(
        "--output-audio",
        default="output/reference_voice.wav",
        help="Output reference audio path",
    )
    parser.add_argument(
        "--output-text",
        default="output/reference_text.txt",
        help="Output reference transcript text path",
    )
    args = parser.parse_args(argv)

    # Load words
    log(f"[1/3] Loading transcription from {args.words_json}...")
    with open(args.words_json, "r", encoding="utf-8") as f:
        words = json.load(f)
    log(f"  Loaded {len(words)} words")

    # Find a good segment
    log(f"[2/3] Finding clean speech segment near {args.start}s...")
    result = find_good_reference_segment(
        words, target_start=args.start,
        min_duration=args.min_duration, max_duration=args.max_duration,
    )

    if result is None:
        log("[error] Could not find a clean reference segment!")
        return 1

    start_idx, end_idx = result
    seg_start = words[start_idx]["start"]
    seg_end = words[end_idx - 1]["end"]
    seg_duration = seg_end - seg_start
    seg_text = " ".join(w["word"] for w in words[start_idx:end_idx])

    log(f"  Found segment: {seg_start:.2f}s - {seg_end:.2f}s ({seg_duration:.1f}s)")
    log(f"  Words: {end_idx - start_idx}")
    log(f"  Transcript: \"{seg_text[:100]}...\"")

    # Extract audio
    log(f"[3/3] Extracting reference audio to {args.output_audio}...")
    Path(args.output_audio).parent.mkdir(parents=True, exist_ok=True)
    success = extract_audio_segment(
        args.audio, seg_start, seg_duration, args.output_audio
    )

    if not success:
        log("[error] Failed to extract audio!")
        return 1

    # Save transcript text
    Path(args.output_text).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output_text, "w", encoding="utf-8") as f:
        f.write(seg_text)

    log(f"\n[done] Reference extraction complete!")
    log(f"  Audio: {args.output_audio}")
    log(f"  Text:  {args.output_text}")
    log(f"  Duration: {seg_duration:.1f}s")
    log(f"  Transcript: \"{seg_text}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())