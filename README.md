# Repertorio → Music Database → Spotify Playlist

Turns a band's PDF song list (`lista_canciones.pdf`, ~1,164 songs) into a clean,
enriched music database and, eventually, a curated Spotify playlist tuned to your
taste. See [context.md](context.md) for the full vision.

## Status

| Stage | Module | State |
|------|--------|-------|
| 1. PDF extraction | `src/pdf_extraction.py` | ✅ done |
| 2. Cleaning / normalization | `src/cleaning.py` | ✅ done |
| 3. Spotify matching | `src/spotify_api.py` | 🟡 scaffold |
| 4. Genre analysis | `src/genre_analysis.py` | 🟡 scaffold |
| 5. Playlist creation | `src/playlist_creation.py` | 🟡 scaffold |
| 6. Preference learning | `src/preferences.py` | 🟡 scaffold |

## Setup

```bash
# Install dependencies into the project venv (Python 3.10)
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

The repertory PDF lives in `data/raw/lista_canciones.pdf`.

## Running the pipeline

```bash
# Stage 1 — PDF -> data/processed/songs_raw.csv  (line_no, song_raw, artist_raw)
.venv/Scripts/python.exe -m src.pdf_extraction

# Stage 2 — clean -> data/processed/songs_clean.csv
.venv/Scripts/python.exe -m src.cleaning
```

### `songs_clean.csv` columns
`line_no, song_raw, artist_raw` (originals, for auditing) plus:
- `song_clean`, `artist_clean` — normalized casing / separators / quotes
- `artist_corrected` — after alias correction + high-confidence fuzzy snap
- `genre_hint` — genre pulled out of the artist field (e.g. `(LATIN POP)`, `CUMBIA …`)
- `fuzzy_suggestion` — a possible canonical spelling when a near-duplicate was found
- `needs_review` — `True` for rows with no artist or a possible duplicate spelling

## How the messy data is handled

The PDF is a two-column layout (`N. SONG        ARTIST`). Extraction uses word
**coordinates** (PyMuPDF), splitting song vs. artist at the column boundary
(~x=322; songs never pass 317, artists start at 327), which is robust to the
per-page alignment shifts and to long titles that run close to the artist column.

Cleaning then:
- pulls genre annotations out of the artist column, keeping the real artist
  (`(JUAN LUIS GUERRA-MERENGUE)` → artist `Juan Luis Guerra`, genre `Merengue`);
- normalizes multi-artist separators (`/ & , – —  -  y  feat …`) to ` & `;
- applies an editable alias dictionary and uses rapidfuzz to snap obvious
  misspellings and suggest borderline ones.

### Editable dictionaries (re-run Stage 2 to apply)
- `data/dictionaries/artist_aliases.json` — `"singer/typo" → "official artist"`
- `data/dictionaries/genre_overrides.json` — `artist → {genre, subgenre}` (Stage 4)

Workflow: run Stage 2, open `songs_clean.csv`, triage `needs_review` rows, add
fixes to `artist_aliases.json`, and re-run. Cleaning is idempotent.

## Spotify credentials (needed for Stages 3–5)

1. Create an app at https://developer.spotify.com/dashboard
2. Add Redirect URI `http://127.0.0.1:8888/callback`
3. Copy `.env.example` → `.env` and fill in `SPOTIPY_CLIENT_ID` / `SPOTIPY_CLIENT_SECRET`.

> Note: Spotify deprecated the audio-features endpoints (BPM, energy, …) for new
> apps in Nov 2024. Stage 3 attempts them and falls back to null if unavailable;
> basic metadata and artist genres still work.
