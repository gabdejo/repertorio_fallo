# Plan: Band Repertory → Music Database → Spotify Playlist Pipeline

> **Implementation status (Stages 1–2 done).** Two approach details changed during
> the build vs. the original plan below:
> - **Extraction** uses PyMuPDF **word coordinates** (split at the column boundary
>   ~x=322), not a `2+ whitespace` split — the plain-text mode interleaved the two
>   columns. See [src/pdf_extraction.py](src/pdf_extraction.py).
> - **`needs_review`** flags only no-artist / possible-duplicate rows (169/1164), and
>   a `fuzzy_suggestion` column was added. The "low fuzzy confidence" rule was dropped
>   because it flagged every unique artist.
> See [README.md](README.md) for the as-built behavior.

## Context

The user has a PDF (`lista_canciones.pdf`, in project root) listing **~1,164 songs** from a band's
repertoire (mostly Latin: cumbia, salsa, merengue, reggaetón, Latin pop, plus 90s/English hits).
The goal (per `context.md`) is to turn this messy, unstructured list into a clean, enriched music
database and eventually a curated Spotify playlist tuned to personal taste.

This plan builds the architecture from `context.md`, but the **first concrete deliverable is
extraction + cleaning** (validate the messy data before touching Spotify). Later stages (Spotify
matching, genre analysis, playlist creation, preference learning) are scaffolded and documented so
they can be implemented incrementally.

### Data realities discovered by inspecting the PDF
- The PDF is a two-column layout (`N. SONG        ARTIST`). PyMuPDF's plain text mode interleaves
  the columns, so extraction works from **word coordinates** instead. Accents (`ALIMAÑA`, `TAÑÓN`)
  and the apostrophe (`90'S`) decode correctly as Unicode.
- Column geometry: song text never passes x≈317, the artist column starts at x≥327 (two indent
  levels, ~327 and ~363) — so a boundary at ~322 splits cleanly, robust to per-page shifts.
- Artist field is dirty:
  - Genre annotations mixed in: `(JUAN LUIS GUERRA-MERENGUE)`, `(LATIN POP)`, `(THE VILLAGE PEOPLE-ROCK)`,
    or bare genre words `MERENGUE` / `REGETON` / `CUMBIA`.
  - Multi-artist separators: `/`, `&`, `,`, `–`/`—` (en/em dash), ` - `, ` Y `, `feat`.
  - Typos / OCR-ish errors: `SELANA`→Selena, `MICHEL TELLO`→Teló, `WSISIN`→Wisin, `PROBRE`→pobre.
  - **Missing artists** (e.g. `AGACHADITA MIX`, `ALL TIME ROCK AND ROLL`, `AMOR DE ETIQUETA`).
  - **Duplicates** (`ADIOS AMOR` ×2, `ANTONIA` ×2 — legitimately different artists, keep both).
  - All UPPERCASE.

### Decisions confirmed with user
- **Audio features**: attempt Spotify `audio-features` anyway (deprecated for new apps Nov 2024);
  fall back gracefully if it returns 403 — basic metadata + genres still work.
- **First deliverable**: extraction + cleaning, producing a reviewable CSV.
- **Spotify credentials**: user does not have them yet → plan includes setup instructions.

### Environment
- `.venv` (Python 3.10) exists in root but is **empty** (only pip/setuptools). All deps must be installed.

---

## Project structure to create

```
repertorio_fallo/
  lista_canciones.pdf          # exists (move to data/raw/ during setup)
  context.md                   # exists
  requirements.txt             # NEW
  .env.example                 # NEW (Spotify creds template)
  .gitignore                   # NEW (.venv, .env, data/processed if desired)
  README.md                    # NEW (how to run each stage)

  data/
    raw/lista_canciones.pdf
    processed/
      songs_raw.csv            # stage 1 output (song_raw, artist_raw, line_no)
      songs_clean.csv          # stage 2 output (+ clean/corrected/genre_hint/needs_review)
      songs_metadata.csv       # stage 3 output (Spotify metadata)
    dictionaries/
      artist_aliases.json      # editable alias/correction map
      genre_overrides.json     # editable artist→genre overrides

  src/
    __init__.py
    config.py                  # paths, constants
    pdf_extraction.py          # STAGE 1  (build now)
    cleaning.py                # STAGE 2  (build now)
    spotify_api.py             # STAGE 3  (scaffold now, implement next)
    genre_analysis.py          # STAGE 4  (scaffold)
    playlist_creation.py       # STAGE 5  (scaffold)
    preferences.py             # STAGE 6  (scaffold)

  notebooks/
    exploration.ipynb          # analysis playground (later)
```

---

## Stage 1 — PDF extraction (`src/pdf_extraction.py`) — BUILD NOW

**Goal:** `data/raw/lista_canciones.pdf` → `data/processed/songs_raw.csv` with columns
`line_no, song_raw, artist_raw`. Preserve originals exactly for auditing.

Approach (as built):
1. Open with PyMuPDF (`fitz.open`), iterate pages, get words with coordinates (`page.get_text("words")`).
2. Group words into visual rows by y position; anchor each entry on the row whose first token is `N.`.
3. Determine the song/artist x boundary per page (just left of the smallest artist start; clamped to
   a sane range) and split each row at that x. A fixed boundary handles long titles that run close to
   the artist column, and artist-less titles positioned in the right column are treated as the song.
4. Strip/collapse whitespace; drop header/fragment rows.
5. Sanity check: warn if extracted count differs significantly from max line number (~1164).
6. Write CSV (UTF-8). Print a short summary (total rows, # missing artist).

## Stage 2 — Cleaning & normalization (`src/cleaning.py`) — BUILD NOW

**Goal:** `songs_raw.csv` → `songs_clean.csv` with:
`line_no, song_raw, artist_raw, song_clean, artist_clean, artist_corrected, genre_hint,
fuzzy_suggestion, needs_review`.

Steps:
1. **Extract genre hints** from the artist field: pull genre keywords out of parentheticals and bare
   text into `genre_hint`, keeping any remaining text as the artist
   (`(JUAN LUIS GUERRA-MERENGUE)` → artist `Juan Luis Guerra`, genre `Merengue`).
2. **Basic normalization** (`song_clean`, `artist_clean`): smart title-case, normalize quotes/
   apostrophes, trim, normalize multi-artist separators to a canonical ` & `.
3. **Alias correction** → `artist_corrected`: apply `data/dictionaries/artist_aliases.json`
   (keys normalized through the same pipeline as the data). rapidfuzz snaps near-certain misspellings
   (score ≥ 95) and surfaces borderline ones (86–95) in `fuzzy_suggestion`.
4. **needs_review flag**: true when the artist is missing or a possible duplicate spelling was found.
   (New unique artists are NOT flagged.)
5. Keep duplicates (different artists are valid).
6. Write CSV + print summary (corrections applied, missing artists, suggestions, rows needing review).

`artist_aliases.json` and `genre_overrides.json` start small and are meant to be hand-edited, then
re-running stage 2 re-applies them (idempotent — verified).

## Stage 3 — Spotify matching (`src/spotify_api.py`) — SCAFFOLD NOW, IMPLEMENT NEXT

- Auth via **spotipy** `SpotifyOAuth` (playlist scopes) reading creds from `.env`.
- For each row: query `q=track:<song> artist:<artist>`, take best candidate (rank by rapidfuzz on
  title+artist and Spotify popularity). Store `track_id, official_artist, album, year, duration_ms,
  popularity, match_score`. Flag low-confidence matches for manual review.
- Fetch **artist genres** via the artist endpoint (still available) → feeds Stage 4.
- **Audio features**: attempt `sp.audio_features(track_ids)`; wrap in try/except — on 403/None,
  log once and leave BPM/energy/etc. columns null (per user decision).
- Cache responses to avoid re-querying; respect rate limits.
- Output `songs_metadata.csv`.

## Stage 4 — Genre analysis (`src/genre_analysis.py`) — SCAFFOLD
Build artist→genre/subgenre table from Spotify genres + `genre_hint` + `genre_overrides.json`;
produce final dataset `song | artist | year | genre | subgenre | duration | bpm | popularity | liked`.

## Stage 5 — Playlist creation (`src/playlist_creation.py`) — SCAFFOLD
Create a Spotify playlist from matched `track_id`s (batched ≤100 per add call).

## Stage 6 — Preference learning (`src/preferences.py`) — SCAFFOLD
After user fills `liked` (1/0), aggregate ratings by genre/artist/decade/BPM/energy; generate a
balanced playlist around top 3 genres while keeping diversity. Visuals in `notebooks/exploration.ipynb`.

---

## Dependencies (`requirements.txt`)
`pymupdf`, `pandas`, `rapidfuzz`, `spotipy`, `python-dotenv`, `matplotlib`, `seaborn`, `plotly`,
`jupyter`. (`camelot`/`tabula` not needed — the PDF is text, not ruled tables.)

Install into the existing empty `.venv`:
`.venv/Scripts/python.exe -m pip install -r requirements.txt`

## Spotify credentials setup (instructions in README)
1. Go to developer.spotify.com/dashboard → Create app.
2. Add Redirect URI `http://127.0.0.1:8888/callback`.
3. Copy Client ID/Secret into `.env` (from `.env.example`):
   `SPOTIPY_CLIENT_ID=`, `SPOTIPY_CLIENT_SECRET=`, `SPOTIPY_REDIRECT_URI=http://127.0.0.1:8888/callback`.

---

## Verification (results)

**Stage 1 (extraction):** all 1164 line numbers present (no gaps/dupes); first/last entries match the
PDF (`24 K MAGIC / BRUNO MARS`, `YA TE OLVIDE / BERNIS SALSA`); artist-less rows captured
(`AGACHADITA MIX`); cross-checked against an independent `pdftotext` run (where they disagreed, the
coordinate-based extraction was correct).

**Stage 2 (cleaning):** accents preserved (`Alimaña` = UTF-8 `c3 b1`); genre hints split out
(153 rows); separators normalized (`Luis Fonsi & Daddy Yankee`); aliases applied (18); fuzzy
suggestions surfaced (21, e.g. `Madona`→`Madonna`); `needs_review` = 169; idempotent (identical
output hash on re-run).

**Later stages:** after creds are set, run a small N-song slice through `spotify_api.py`, confirm
matches and that audio-features either populate or degrade gracefully to null on 403.
