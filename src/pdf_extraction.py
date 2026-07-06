"""Stage 1 - Extract the raw song/artist list from the repertory PDF.

Input : data/raw/lista_canciones.pdf
Output: data/processed/songs_raw.csv   (line_no, song_raw, artist_raw)

The PDF is a two-column layout ("N. SONG        ARTIST"). PyMuPDF's plain
"text" mode interleaves the columns, so we work from word coordinates instead:

  1. Group words into visual rows by their y position.
  2. Anchor each entry on the row whose first token is "<number>.".
  3. Determine the song/artist x boundary for the page (the artist column is
     highly stable at x~=363), then split each row at that x. Using a fixed
     boundary - rather than the widest in-row gap - correctly handles long song
     titles whose text runs close up to the artist column.

Originals are preserved verbatim (only whitespace normalized) for auditing.

Run:  python -m src.pdf_extraction
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict

import fitz  # PyMuPDF
import pandas as pd

from . import config

# A token that is purely an entry number, e.g. "12." (or rarely "12").
_NUMBER_RE = re.compile(r"^(\d+)\.?$")
# Minimum in-row gap (px) used when probing for the artist column position.
_PROBE_GAP = 40.0
# Fallback x boundary if a page yields no clear two-column rows. Song text tops
# out around x=317 and the artist column starts at x>=327, so ~322 splits cleanly.
_DEFAULT_BOUNDARY = 322.0
# Sane range for the computed boundary (song right-edge max ~317; artist inner
# indent ~327) - protects against a stray wide gap inside a long song title.
_BOUNDARY_MIN = 318.0
_BOUNDARY_MAX = 360.0
# Words within this many points of vertical position belong to the same row.
_ROW_TOL = 3.0


def _cluster_rows(words: list[tuple]) -> list[list[tuple]]:
    """Group word tuples into rows by y position (handles tiny baseline jitter)."""
    buckets: dict[int, list[tuple]] = defaultdict(list)
    for w in words:
        buckets[round(w[1])].append(w)

    # Merge buckets whose y are within _ROW_TOL of each other.
    rows: list[list[tuple]] = []
    current_key = None
    current: list[tuple] = []
    for key in sorted(buckets):
        if current_key is None or key - current_key <= _ROW_TOL:
            current.extend(buckets[key])
            current_key = key if current_key is None else current_key
        else:
            rows.append(current)
            current = list(buckets[key])
            current_key = key
    if current:
        rows.append(current)
    return rows


def _strip_number(words: list[tuple]) -> tuple[int | None, list[tuple]]:
    """Pull a leading "<number>." token off a left-to-right sorted row."""
    if words:
        m = _NUMBER_RE.match(words[0][4])
        if m:
            return int(m.group(1)), words[1:]
    return None, words


def _page_boundary(rows: list[list[tuple]]) -> float:
    """Estimate the song/artist x boundary for a page.

    The artist column is left-aligned at two indentation levels (~327 and
    ~363), while song text never reaches the artist column. We probe rows that
    have a clear wide gap, collect the left edge of the right-hand (artist)
    column, and place the boundary just to the left of the *smallest* artist
    start so every artist word - even at the inner indentation - lands on the
    artist side. Falls back to a default if no two-column rows are found.
    """
    artist_starts: list[float] = []
    for row in rows:
        ws = sorted(row, key=lambda w: w[0])
        _, ws = _strip_number(ws)
        for i in range(1, len(ws)):
            if ws[i][0] - ws[i - 1][2] > _PROBE_GAP:
                artist_starts.append(ws[i][0])
                break
    if not artist_starts:
        return _DEFAULT_BOUNDARY
    boundary = min(artist_starts) - 5.0  # just left of the inner artist indent
    return min(max(boundary, _BOUNDARY_MIN), _BOUNDARY_MAX)


def _split_row(words: list[tuple], boundary: float) -> tuple[int | None, str, str]:
    """Return (line_no, song, artist) for one visual row, split at ``boundary``.

    ``words`` is a list of PyMuPDF word tuples (x0, y0, x1, y1, text, ...).
    """
    ws = sorted(words, key=lambda w: w[0])  # left to right
    line_no, ws = _strip_number(ws)
    if not ws:
        return line_no, "", ""

    song = _collapse_ws(" ".join(w[4] for w in ws if w[0] < boundary))
    artist = _collapse_ws(" ".join(w[4] for w in ws if w[0] >= boundary))

    # Some entries have no artist and their title is positioned in the right
    # column (e.g. "1074. UN VERANO EN NUEVA YORK"). The song must never be
    # empty, so treat right-column-only content as the song.
    if not song and artist:
        song, artist = artist, ""
    return line_no, song, artist


def _collapse_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def parse_pdf(pdf_path) -> tuple[pd.DataFrame, int]:
    """Parse the PDF into a (line_no, song_raw, artist_raw) DataFrame."""
    records: list[dict] = []
    max_no = 0

    with fitz.open(pdf_path) as doc:
        for page in doc:
            words = page.get_text("words")
            rows = _cluster_rows(words)
            boundary = _page_boundary(rows)
            for row in rows:
                line_no, song, artist = _split_row(row, boundary)
                if line_no is None or not song:
                    # Header rows ("LISTA CANCIONES") and stray fragments.
                    continue
                max_no = max(max_no, line_no)
                records.append(
                    {"line_no": line_no, "song_raw": song, "artist_raw": artist}
                )

    df = pd.DataFrame(records, columns=["line_no", "song_raw", "artist_raw"])
    df = df.sort_values("line_no").reset_index(drop=True)
    return df, max_no


def extract(pdf_path=config.PDF_PATH, out_csv=config.SONGS_RAW_CSV) -> pd.DataFrame:
    """Run the full extraction and write the raw CSV."""
    config.ensure_dirs()
    if not pdf_path.exists():
        raise FileNotFoundError(
            f"PDF not found at {pdf_path}. Place 'lista_canciones.pdf' in data/raw/."
        )

    df, max_no = parse_pdf(pdf_path)
    df.to_csv(out_csv, index=False, encoding="utf-8")

    missing_artist = int((df["artist_raw"] == "").sum())
    print(f"[stage 1] Extracted {len(df)} entries (max entry number: {max_no}).")
    print(f"[stage 1] Rows with no artist: {missing_artist}.")
    if max_no and abs(max_no - len(df)) > 0.05 * max_no:
        print(
            f"[stage 1] WARNING: parsed rows ({len(df)}) differ notably from the "
            f"max entry number ({max_no}). Some lines may have failed to parse.",
            file=sys.stderr,
        )
    print(f"[stage 1] Wrote {out_csv}")
    return df


if __name__ == "__main__":
    extract()
