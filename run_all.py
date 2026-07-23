#!/usr/bin/env python
"""
Batch processor: runs the full Revox pipeline on ALL video files
in the input/ folder. Skips files that already have a censored output.

Usage:
    python run_all.py
    python run_all.py --provider pyttsx3
    python run_all.py --force  (re-process even if output exists)
"""

import argparse
import subprocess
import sys
from pathlib import Path

VIDEO_EXTS = {".mkv", ".mp4", ".m4v", ".mov", ".avi", ".webm", ".wmv", ".flv"}


def log(msg: str = "") -> None:
    print(msg, flush=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Batch process all videos in input/ folder.")
    p.add_argument("--provider", default="pyttsx3", help="TTS provider (default: pyttsx3)")
    p.add_argument("--force", action="store_true", help="Re-process even if output exists")
    p.add_argument("--input-dir", default="input", help="Input folder (default: input)")
    p.add_argument("--output-dir", default="output", help="Output folder (default: output)")
    args = p.parse_args(argv)

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    if not input_dir.is_dir():
        log(f"[error] Input folder not found: {input_dir}")
        return 1

    # Find all video files
    videos = sorted(
        f for f in input_dir.iterdir()
        if f.is_file() and f.suffix.lower() in VIDEO_EXTS
    )

    if not videos:
        log(f"[info] No video files found in {input_dir}")
        return 0

    log(f"{'=' * 78}")
    log(f"  Found {len(videos)} video file(s) to process:")
    for i, v in enumerate(videos, 1):
        log(f"    {i}. {v.name}")
    log(f"{'=' * 78}")
    log()

    success_count = 0
    skip_count = 0
    fail_count = 0

    for i, video in enumerate(videos, 1):
        basename = video.stem
        out_ext = video.suffix.lower()
        expected_output = output_dir / f"{basename}_censored{out_ext}"

        log(f"{'=' * 78}")
        log(f"  [{i}/{len(videos)}] Processing: {video.name}")
        log(f"{'=' * 78}")

        # Skip if output already exists (unless --force)
        if expected_output.exists() and not args.force:
            log(f"  [SKIP] Output already exists: {expected_output.name}")
            log(f"         Use --force to re-process.")
            skip_count += 1
            continue

        # Run the pipeline
        cmd = [
            sys.executable, "run.py",
            str(video),
            "--output-dir", str(output_dir),
            "--provider", args.provider,
        ]

        log(f"  $ {' '.join(cmd)}")
        log()

        result = subprocess.run(cmd)

        if result.returncode == 0:
            log(f"\n  [OK] Successfully processed: {video.name}")
            success_count += 1
        else:
            log(f"\n  [FAILED] Pipeline failed for: {video.name}")
            fail_count += 1

        log()

    # Summary
    log(f"{'=' * 78}")
    log(f"  BATCH COMPLETE")
    log(f"{'=' * 78}")
    log(f"  Total:     {len(videos)}")
    log(f"  Success:   {success_count}")
    log(f"  Skipped:   {skip_count}")
    log(f"  Failed:    {fail_count}")
    log()

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())