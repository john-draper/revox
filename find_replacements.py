#!/usr/bin/env python
"""
Read the word-level JSON produced by transcribe_whisperx.py, clean each word
(strip punctuation, lowercase), match it against a hardcoded dictionary, and
write a new JSON containing only the matched words with their original
start/end timestamps and the replacement text.

Output JSON is a list of objects:
    {"word": str, "start": float, "end": float, "replacement": str}

`word` is the ORIGINAL word exactly as transcribed (e.g. "Dang,") so the match
is traceable; the cleaned/lowercased form is what was looked up in the dict.

Example:
    python find_replacements.py words.json
    python find_replacements.py words.json -o cleaned.json
"""

import argparse
import json
import string
import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
# Hardcoded replacement dictionary.
#   key   = cleaned word (lowercase, no surrounding punctuation) to match
#   value = replacement text to substitute
# Edit this freely — add or remove mappings as needed.
# --------------------------------------------------------------------------- #
#
# This list was seeded from an "Advanced Profanity Filter" export and extended
# with additional mappings. Multi-word phrases and entries that contain internal
# whitespace are intentionally omitted because this tool operates on cleaned,
# single-word tokens. The matching is case-insensitive and ignores surrounding
# punctuation (see clean_word()).
#
# NOTE: Only actual profanity belongs here. Clean euphemisms (dang, darn, gosh,
# heck, shucks) are the REPLACEMENT targets, not words to filter.
# --------------------------------------------------------------------------- #
REPLACEMENTS: dict[str, str] = {
    # NOTE: Only actual profanity belongs here. Clean euphemisms (dang, darn,
    # gosh, heck, shucks) are the REPLACEMENT targets, not words to filter.

    # --- Ass family ---
    "ass": "butt",
    "asses": "butts",
    "asshole": "jerk",
    "assholimov": "buttholimov",
    "assholishness": "buttholishness",
    "assing": "butting",
    "badass": "cool",
    "dumbass": "idiot",
    "jackass": "jerk",
    "kickass": "kickbutt",

    # --- Shit family ---
    "apeshit": "apecrap",
    "batshit": "batcrap",
    "birdshit": "birdcrap",
    "bullshit": "bull",
    "chickenshit": "chickencrap",
    "dogshit": "dogcrap",
    "dumbshit": "dumbcrap",
    "horseshit": "horsecrap",
    "shit": "crap",
    "shitass": "crapbutt",
    "shitbag": "crapbag",
    "shitbeard": "crapbeard",
    "shitbird": "crapbird",
    "shitbox": "crapbox",
    "shitbrain": "crapbrain",
    "shitbrains": "crapbrains",
    "shitface": "crapface",
    "shitfaced": "crapfaced",
    "shithead": "craphead",
    "shitheads": "crapheads",
    "shitheel": "crapheel",
    "shithole": "craphole",
    "shitlick": "craplick",
    "shitload": "crapload",
    "shitloads": "craploads",
    "shits": "craps",
    "shitsnackin": "crapsnackin",
    "shitsnacks": "crapsnacks",
    "shitspace": "crapspace",
    "shitstorm": "crapstorm",
    "shitstorms": "crapstorms",
    "shitter": "crapper",
    "shittier": "crappier",
    "shittiest": "crappiest",
    "shittin": "crappin",
    "shitting": "crapping",
    "shitty": "crappy",
    "shitzombies": "crapzombies",
    "shart": "poo-fart",

    # --- Fuck family ---
    "fuck": "freak",
    "fucking": "stinking",  # from "(beep)ing" / "f***ing" -> "stinking" in the source list
    "effing": "flipping",

    # --- Damn / hell / goddamn family ---
    "damn": "dang",
    "damns": "dangs",
    "damned": "danged",
    "damning": "danging",
    "dammit": "dangit",
    "god": "gosh",
    "goddamn": "doggone",
    "goddamned": "doggone",
    "goddamns": "doggones",
    "goddamning": "doggoning",
    "goddammit": "dangit",
    "hell": "heck",

    # --- Religious exclamations (used as profanity) ---
    "christ": "cripes",
    "christs": "cripes",
    "jesus": "geez",

    # --- Bitch / cunt / twat family ---
    "bitch": "bench",
    "cunt": "expletive",
    "twat": "dumbo",
    "twats": "dumbos",

    # --- Cocksucker ---
    "cocksucker": "suckup",

    # --- Pussy / pussies ---
    "pussy": "softie",
    "pussies": "softies",

    # --- Misc from the filter ---
    "bleep": "beep",
    "fags": "gays",
    "fuchs": "craps",
    "dipshit": "dipstick",
}


def log(msg: str) -> None:
    print(msg, flush=True)


def clean_word(raw: str) -> str:
    """Strip surrounding punctuation and lowercase a word for matching.

    Examples:
        "Dang,"  -> "dang"
        "'Em"    -> "em"
        "WELL?"  -> "well"
    Internal punctuation (e.g. "don't" -> "don't") is preserved.
    """
    return raw.strip(string.punctuation).lower()


def load_words(path: str) -> list[dict]:
    in_path = Path(path)
    if not in_path.is_file():
        raise FileNotFoundError(f"Input JSON not found: {in_path}")
    with in_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(
            f"Expected a JSON list of word objects, got {type(data).__name__}."
        )
    return data


def find_matches(
    words: list[dict],
    replacements: dict[str, str],
) -> list[dict]:
    matches: list[dict] = []
    for entry in words:
        if not isinstance(entry, dict):
            continue
        raw = entry.get("word")
        if not isinstance(raw, str):
            continue
        key = clean_word(raw)
        if key in replacements:
            matches.append(
                {
                    "word": raw,                       # original (uncleaned) word
                    "start": float(entry.get("start")),
                    "end": float(entry.get("end")),
                    "replacement": replacements[key],
                }
            )
    return matches


def default_output_path(input_path: str) -> str:
    p = Path(input_path)
    return str(p.with_name(f"{p.stem}_replacements{p.suffix}"))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Match transcribed words against a hardcoded replacement "
                    "dictionary and export matched words with timestamps.",
    )
    p.add_argument(
        "input",
        help="Path to the word-level JSON from transcribe_whisperx.py",
    )
    p.add_argument(
        "-o", "--output",
        default=None,
        help="Output JSON path (default: <input>_replacements.json next to input).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        words = load_words(args.input)
        log(f"[input] Loaded {len(words)} word entries from {args.input}")

        matches = find_matches(words, REPLACEMENTS)
        log(f"[match] {len(matches)} word(s) matched the replacement dictionary.")

        out_path = Path(args.output or default_output_path(args.input))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(matches, f, ensure_ascii=False, indent=2)

        log(f"[done] Wrote {len(matches)} match(es) to {out_path}")
        # Show a small preview for quick confirmation.
        for m in matches[:5]:
            log(
                f"  {m['start']:7.2f}-{m['end']:7.2f}  "
                f"{m['word']!r} -> {m['replacement']!r}"
            )
        if len(matches) > 5:
            log(f"  ... and {len(matches) - 5} more.")
    except FileNotFoundError as exc:
        log(f"[error] {exc}")
        return 2
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        log(f"[error] {type(exc).__name__}: {exc}")
        return 1
    except KeyboardInterrupt:
        log("[abort] Interrupted by user.")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())