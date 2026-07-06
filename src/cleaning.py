"""Stage 2 - Clean and normalize the raw repertory.

Input : data/processed/songs_raw.csv
Output: data/processed/songs_clean.csv
    columns: line_no, song_raw, artist_raw, song_clean, artist_clean,
             artist_corrected, genre_hint, needs_review

Behaviour:
- Pulls genre annotations out of the artist column into ``genre_hint``.
- Normalizes casing / separators / quotes into ``song_clean`` & ``artist_clean``.
- Applies the editable alias dictionary, and uses rapidfuzz to snap near
  matches onto already-seen canonical artists (suggestions only) -> ``artist_corrected``.
- Flags messy rows (missing/genre-only artist, low fuzzy confidence) in
  ``needs_review`` so they can be triaged directly in the CSV.

Idempotent: edit data/dictionaries/artist_aliases.json and re-run.

Run:  python -m src.cleaning
"""
from __future__ import annotations

import json
import re

import pandas as pd
from rapidfuzz import fuzz, process

from . import config


# --- helpers ---------------------------------------------------------------
def _load_aliases() -> dict[str, str]:
    if not config.ARTIST_ALIASES_JSON.exists():
        return {}
    with open(config.ARTIST_ALIASES_JSON, encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}


# Pre-compile the bare-genre keyword pattern (whole-word, case-insensitive).
_GENRE_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(g) for g in config.GENRE_KEYWORDS) + r")\b",
    flags=re.IGNORECASE,
)
_PAREN_PATTERN = re.compile(r"\(([^)]*)\)")


def extract_genre_hint(artist_raw: str) -> tuple[str, str]:
    """Return (artist_without_genre, genre_hint).

    Genre hints come from two places:
      * parenthetical notes, e.g. "(JUAN LUIS GUERRA-MERENGUE)" or "(LATIN POP)"
      * bare genre keywords sitting in the artist column, e.g. "CUMBIA GRUPO 5"

    Only the *genre keywords* are removed - any remaining text (often the real
    artist, as in "(JUAN LUIS GUERRA-MERENGUE)" -> "Juan Luis Guerra") is kept.
    Internal artist separators ("/", "&", "-") are preserved for the separator
    normalization step; only stray leading/trailing ones are trimmed.
    """
    hints: list[str] = []

    def take_genres(text: str) -> str:
        hints.extend(_GENRE_PATTERN.findall(text))
        return _GENRE_PATTERN.sub(" ", text)

    # 1. Parentheticals: pull genres out, keep the remainder unwrapped.
    def _paren_repl(m: re.Match) -> str:
        return " " + take_genres(m.group(1)) + " "

    working = _PAREN_PATTERN.sub(_paren_repl, artist_raw)

    # 2. Bare genre keywords in the remaining (non-parenthetical) text.
    working = take_genres(working)

    working = re.sub(r"\s+", " ", working).strip(config.ARTIST_STRIP_CHARS)

    # De-duplicate hints preserving order, title-cased.
    seen: list[str] = []
    for h in hints:
        t = h.strip().title()
        if t and t not in seen:
            seen.append(t)
    return working, ", ".join(seen)


def normalize_separators(artist: str) -> str:
    """Collapse the various multi-artist separators into ' & '."""
    out = artist
    for sep in config.ARTIST_SEPARATORS:
        out = re.sub(re.escape(sep), config.CANONICAL_SEPARATOR, out, flags=re.IGNORECASE)
    out = re.sub(r"\s*&\s*", config.CANONICAL_SEPARATOR, out)
    # Collapse any runs of " & " produced by adjacent separators.
    out = re.sub(r"(?:\s*&\s*)+", config.CANONICAL_SEPARATOR, out)
    return re.sub(r"\s+", " ", out).strip(config.ARTIST_STRIP_CHARS)


def smart_title(text: str) -> str:
    """Title-case while keeping common short connectors lowercase (mid-string)."""
    small = {"de", "la", "el", "y", "los", "las", "del", "the", "a", "o", "en"}
    words = text.lower().split()
    out = []
    for i, w in enumerate(words):
        if i != 0 and w in small:
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


def normalize_text(value: str) -> str:
    """Normalize quotes/apostrophes/whitespace and apply smart title casing."""
    if not value:
        return ""
    v = value.replace("’", "'").replace("`", "'").replace("´", "'")
    v = v.replace("“", '"').replace("”", '"')
    v = re.sub(r"\s+", " ", v).strip()
    return smart_title(v)


# --- main pipeline ---------------------------------------------------------
def clean(in_csv=config.SONGS_RAW_CSV, out_csv=config.SONGS_CLEAN_CSV) -> pd.DataFrame:
    config.ensure_dirs()
    if not in_csv.exists():
        raise FileNotFoundError(
            f"{in_csv} not found. Run `python -m src.pdf_extraction` first."
        )

    df = pd.read_csv(in_csv, encoding="utf-8").fillna({"artist_raw": ""})
    aliases = _load_aliases()
    # Normalize alias keys through the *same* pipeline as artist_clean so keys
    # written with "Y"/"/" separators still match data normalized to " & ".
    norm_aliases = {
        normalize_text(normalize_separators(k)): v for k, v in aliases.items()
    }

    canonical_pool: list[str] = []  # accumulates seen canonical artists
    rows = []
    n_corrected = 0

    for _, r in df.iterrows():
        song_clean = normalize_text(str(r["song_raw"]))

        artist_no_genre, genre_hint = extract_genre_hint(str(r["artist_raw"]))
        artist_clean = normalize_text(normalize_separators(artist_no_genre))

        corrected = artist_clean
        applied_alias = False
        fuzzy_review = False
        fuzzy_suggestion = ""

        if artist_clean:
            if artist_clean in norm_aliases:
                corrected = norm_aliases[artist_clean]
                applied_alias = True
            elif canonical_pool:
                match = process.extractOne(
                    artist_clean, canonical_pool, scorer=fuzz.token_sort_ratio
                )
                if match:
                    cand, score = match[0], match[1]
                    if score >= config.FUZZY_SNAP_THRESHOLD:
                        corrected = cand  # snap to existing canonical spelling
                    elif score >= config.FUZZY_REVIEW_LOW:
                        # Close but not certain: keep as-is, surface a suggestion.
                        fuzzy_suggestion = cand
                        fuzzy_review = True
            if corrected and corrected not in canonical_pool:
                canonical_pool.append(corrected)

        if applied_alias and corrected != artist_clean:
            n_corrected += 1

        artist_missing = artist_clean == ""
        # Flag only genuinely actionable rows: no artist at all, or a possible
        # duplicate spelling. New unique artists are NOT flagged.
        needs_review = artist_missing or fuzzy_review

        rows.append(
            {
                "line_no": r["line_no"],
                "song_raw": r["song_raw"],
                "artist_raw": r["artist_raw"],
                "song_clean": song_clean,
                "artist_clean": artist_clean,
                "artist_corrected": corrected,
                "genre_hint": genre_hint,
                "fuzzy_suggestion": fuzzy_suggestion,
                "needs_review": needs_review,
            }
        )

    out = pd.DataFrame(rows)
    out.to_csv(out_csv, index=False, encoding="utf-8")

    n_review = int(out["needs_review"].sum())
    n_missing = int((out["artist_clean"] == "").sum())
    n_suggest = int((out["fuzzy_suggestion"] != "").sum())
    print(f"[stage 2] Cleaned {len(out)} rows.")
    print(f"[stage 2] Alias corrections applied: {n_corrected}.")
    print(f"[stage 2] Rows missing an artist: {n_missing}.")
    print(f"[stage 2] Possible-duplicate suggestions: {n_suggest}.")
    print(f"[stage 2] Rows flagged needs_review: {n_review}.")
    print(f"[stage 2] Wrote {out_csv}")
    return out


if __name__ == "__main__":
    clean()
