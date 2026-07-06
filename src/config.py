"""Shared paths and constants for the repertory pipeline."""
from __future__ import annotations

from pathlib import Path

# --- Directories -----------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent

DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
DICTIONARIES = DATA / "dictionaries"

# --- Files -----------------------------------------------------------------
PDF_PATH = RAW / "lista_canciones.pdf"

SONGS_RAW_CSV = PROCESSED / "songs_raw.csv"
SONGS_CLEAN_CSV = PROCESSED / "songs_clean.csv"
SONGS_METADATA_CSV = PROCESSED / "songs_metadata.csv"

ARTIST_ALIASES_JSON = DICTIONARIES / "artist_aliases.json"
GENRE_OVERRIDES_JSON = DICTIONARIES / "genre_overrides.json"

# --- Parsing constants -----------------------------------------------------
# Each repertory line looks like:  "123. SONG NAME        ARTIST"
# Capture the entry number and the rest of the line.
ENTRY_RE = r"^\s*(\d+)\.\s+(.*)$"
# Song and artist columns are separated by a run of 2+ spaces. Alignment
# shifts between pages, so we never rely on fixed character columns.
COLUMN_SPLIT_RE = r"\s{2,}"

# Bare genre keywords that sometimes appear in the "artist" column instead of
# (or alongside) the real performer. Matched case-insensitively as whole words.
GENRE_KEYWORDS = [
    "merengue",
    "cumbia",
    "salsa",
    "bachata",
    "reggaeton",
    "reggaetón",
    "regeton",
    "regueton",
    "reggae",
    "regaee",
    "latin pop",
    "pop latino",
    "balada",
    "rock",
    "rock and roll",
    "pop",
    "house",
    "electronic",
    "electronica",
    "huayno",
    "festejo",
    "vals",
    "ranchera",
    "bolero",
    "tropical",
]

# Multi-artist separators normalized to a canonical " & ". En-dash/em-dash and
# " - " (hyphen padded with spaces) are used as separators in this PDF; a bare
# hyphen is left alone so hyphenated names (e.g. "Jay-Z") survive.
ARTIST_SEPARATORS = [
    "/", "&", ",", "–", "—", " - ",
    " y ", " feat ", " feat. ", " ft ", " ft. ", " con ", " vs ",
]
CANONICAL_SEPARATOR = " & "
# Characters trimmed from the ends of an artist string after genre/paren removal.
ARTIST_STRIP_CHARS = " -/&–—,"

# rapidfuzz score bands (token_sort_ratio, 0-100) for matching a new artist
# against the set of artists already seen:
#   >= FUZZY_SNAP_THRESHOLD            -> near-certain same artist; snap spelling
#   [FUZZY_REVIEW_LOW, snap)           -> possible duplicate; suggest + flag review
#   <  FUZZY_REVIEW_LOW               -> treat as a genuinely new artist
FUZZY_SNAP_THRESHOLD = 95
FUZZY_REVIEW_LOW = 86


def ensure_dirs() -> None:
    """Create the data directories if they do not exist."""
    for d in (RAW, PROCESSED, DICTIONARIES):
        d.mkdir(parents=True, exist_ok=True)
