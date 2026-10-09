# Repertorio → Music Database → Spotify Playlist

Turns a band's PDF song list (`lista_canciones.pdf`, ~1,164 songs) into a clean,
enriched music database and, eventually, a curated Spotify playlist tuned to your
taste. See [context.md](context.md) for the full vision.

## Status

| Stage | Module | State |
|------|--------|-------|
| 1. PDF extraction | `src/pdf_extraction.py` | ✅ done |
| 2. Cleaning / normalization | `src/cleaning.py` | ✅ done |
| 3. Spotify matching | `src/spotify_api.py` | ✅ done |
| 3.5. Last.fm genre tags | `src/lastfm_api.py` | ✅ done |
| 4. Genre analysis | `src/genre_analysis.py` | ✅ done |
| 5. Playlist creation | `src/playlist_creation.py` | ✅ done (create the playlist manually first — see PLAN.md) |
| 6. Screen playlist workflow | `src/preferences.py` | ✅ done (`check`/`add`/`report`/`label` — see PLAN.md) |

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

# Stage 3 — match to Spotify -> data/processed/songs_metadata.csv
# (requires .env credentials, see "Spotify credentials" below)
.venv/Scripts/python.exe -m src.spotify_api
```

### `songs_clean.csv` columns
`line_no, song_raw, artist_raw` (originals, for auditing) plus:
- `song_clean`, `artist_clean` — normalized casing / separators / quotes
- `artist_corrected` — after alias correction + high-confidence fuzzy snap
- `genre_hint` — genre pulled out of the artist field (e.g. `(LATIN POP)`, `CUMBIA …`)
- `fuzzy_suggestion` — a possible canonical spelling when a near-duplicate was found
- `needs_review` — `True` for rows with no artist or a possible duplicate spelling

### `songs_metadata.csv` columns
`line_no, song_clean, artist_corrected` (join keys back to `songs_clean.csv`) plus:
- `track_id`, `official_artist`, `album`, `year`, `duration_ms`, `popularity` — from the
  best-matching Spotify track (null if no match found)
- `artist_genres` — comma-separated genres from Spotify's artist endpoint (see note below —
  usually empty for apps without Extended Quota Mode)
- `match_score` — 0-100 fuzzy match confidence (song 60% + artist 40% weight)
- `low_confidence_match` — `True` when unmatched or `match_score` is below 70; triage these
  manually the same way as `needs_review` rows from Stage 2
- `bpm, energy, danceability, acousticness, valence, loudness` — audio features, null if the
  endpoint is unavailable (see note below)

Stage 3 caches Spotify lookups in `data/cache/` (`spotify_track_cache.json`,
`spotify_artist_genre_cache.json`), so re-running only queries new/changed rows.

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
- `data/dictionaries/excluded_lines.json` — `line_no`s to drop entirely (medley/wildcard
  PDF entries like "Huaynos Varios" that aren't a single song); look up the `line_no` in
  `songs_raw.csv`

Workflow: run Stage 2, open `songs_clean.csv`, triage `needs_review` rows, add
fixes to `artist_aliases.json`, and re-run. Cleaning is idempotent.

## Spotify credentials (needed for Stages 3–5)

1. Create an app at https://developer.spotify.com/dashboard
2. Add Redirect URI `http://127.0.0.1:8888/callback`
3. Copy `.env.example` → `.env` and fill in `SPOTIPY_CLIENT_ID` / `SPOTIPY_CLIENT_SECRET`.

> Note: Spotify deprecated the audio-features endpoints (BPM, energy, …) for new
> apps in Nov 2024, and — as observed running Stage 3 — new apps without
> **Extended Quota Mode** also get no `genres`/`popularity`/`followers` on Artist
> and Track objects. Stage 3 attempts both and degrades to null gracefully;
> basic metadata (track, album, year, duration) still works reliably. Because
> Spotify genres are effectively unavailable, Stage 4 relies on `genre_hint`
> (from the PDF), `genre_overrides.json`, and Last.fm tags (Stage 3.5) as genre
> sources, not Spotify's artist genres. BPM has no planned automated source —
> Spotify no longer exposes `preview_url` either, so local audio analysis
> isn't an option, and no free API has verified coverage of this catalog.

## Last.fm credentials (needed for Stage 3.5)

1. Get a free API key at https://www.last.fm/api/account/create
2. Copy `.env.example` → `.env` (if not done already) and fill in `LASTFM_API_KEY`.

Run `python -m src.lastfm_api` to fetch top tags per unique artist into
`data/cache/lastfm_tag_cache.json`, supplementing `genre_hint`/`genre_overrides.json` for genre
coverage (see PLAN.md's Stage 3.5 section for the design).

## Picker page (`web/`) — choose the final playlist from your phone

A static page that plays each undecided song on your phone's Spotify app (Spotify Connect,
Premium required) and records In / Out per song, with a quota meter per genre. Decisions are
stored as membership in two playlists you create by hand: **Final** and **Descartes**.

1. Create two empty playlists in Spotify and paste their ids/URLs into `web/config.js`
   (`finalPlaylistId`, `descartesPlaylistId`). Default per-genre maximums live there too (`quotas`); edit them live in the page with the "Cupos" button (saved in the Final playlist description).
2. In the Spotify dashboard add the page URL as a Redirect URI, e.g.
   `https://<your-app>.vercel.app/` and, for local testing, `http://127.0.0.1:8888/`.
3. Regenerate the song list whenever the screen playlist changes:
   `python -m src.preferences report --out data/processed/screen_playlist.csv && python -m src.web_build`
4. Deploy the `web/` folder on Vercel (root directory = `web`, no build step), or test locally:
   `python -m http.server 8888 -d web -b 127.0.0.1`.

Safety: the screen playlist id is listed in `protectedPlaylistIds` and the page never sends a
write naming it. On the Python side `playlist_creation.guard()` blocks every write to
`SCREEN_PLAYLIST_ID` (override deliberately with `ALLOW_PROTECTED_PLAYLIST_WRITES=1`).
`web/songs.json` doubles as a committed snapshot of the screen playlist's track ids.
