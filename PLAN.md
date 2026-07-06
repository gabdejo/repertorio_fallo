# Plan: Band Repertory → Music Database → Spotify Playlist Pipeline

> **Implementation status (Stages 1–3 done).** Approach details that changed during
> the build vs. the original plan below:
> - **Extraction** uses PyMuPDF **word coordinates** (split at the column boundary
>   ~x=322), not a `2+ whitespace` split — the plain-text mode interleaved the two
>   columns. See [src/pdf_extraction.py](src/pdf_extraction.py).
> - **`needs_review`** flags only no-artist / possible-duplicate rows (169/1164), and
>   a `fuzzy_suggestion` column was added. The "low fuzzy confidence" rule was dropped
>   because it flagged every unique artist.
> - **Spotify genres and popularity are unavailable**: apps without Extended Quota
>   Mode get no `genres`/`popularity`/`followers` on Artist/Track objects (in addition
>   to the already-expected audio-features 403). Stage 3 degrades gracefully; Stage 4
>   must rely on `genre_hint` + `genre_overrides.json`, not Spotify genres.
> - Stage 3 adds a `low_confidence_match` column (match_score < 70) and caches
>   lookups under `data/cache/` (gitignored), keyed by song+artist and by artist id.
> - **BPM/audio-features are out of scope for automation**: no free API has verified
>   coverage of this catalog, and Spotify no longer exposes `preview_url` either (so
>   local audio analysis isn't an option). A **Last.fm genre source (Stage 3.5) is
>   planned** to mitigate the missing Spotify genres — see that section below.
>   Design is settled; implementation is deferred to a future session.
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
    cache/                     # gitignored; external API lookup caches
      spotify_track_cache.json        # stage 3
      spotify_artist_genre_cache.json # stage 3
      lastfm_tag_cache.json           # stage 3.5 (planned)

  src/
    __init__.py
    config.py                  # paths, constants
    pdf_extraction.py          # STAGE 1  (build now)
    cleaning.py                # STAGE 2  (build now)
    spotify_api.py             # STAGE 3  (scaffold now, implement next)
    lastfm_api.py              # STAGE 3.5 (planned; design settled, not yet built)
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

## Stage 3 — Spotify matching (`src/spotify_api.py`) — DONE

- Auth via **spotipy** `SpotifyOAuth` (playlist scopes) reading creds from `.env`.
- For each row: query `q=track:<song> artist:<artist>` (falls back to a plain query), take the
  best candidate by rapidfuzz `token_sort_ratio` on title (60%) + artist (40%). Store
  `track_id, official_artist, album, year, duration_ms, popularity, match_score,
  low_confidence_match` (flag when unmatched or `match_score < 70`).
- Fetch **artist genres** via `sp.artist()`, cached per artist id — **in practice this app tier
  returns no `genres`/`popularity` at all** (Spotify restricts these to apps with Extended Quota
  Mode), so `artist_genres`/`popularity` are null for every row. Stage 4 must source genre from
  `genre_hint` + `genre_overrides.json` instead.
- **Audio features**: attempts `sp.audio_features(track_ids)` in batches of 100; wraps in
  try/except — confirmed 403 in testing, degrades to null BPM/energy/etc. (per user decision).
- Caches track and artist-genre lookups under `data/cache/*.json` (gitignored), saved every 25
  rows so an interrupted run doesn't lose progress; re-running is fast and idempotent.
- Output `songs_metadata.csv`.

## Stage 3.5 — Last.fm genre tags (`src/lastfm_api.py`) — PLANNED (design settled, not built)

**Why:** Spotify apps without Extended Quota Mode return no `genres`/`popularity` at all (see
Stage 3 verification below), leaving Stage 4 with only `genre_hint` (153/1164 PDF-annotated rows)
and hand-maintained `genre_overrides.json`. Last.fm's free, crowd-sourced tag API fills that gap
— its userbase gives it decent coverage of Latin genres (cumbia, salsa, merengue, reggaetón).

**Design:**
- Plain `requests` calls (no SDK — Last.fm's API is simple REST + API key), reading
  `LASTFM_API_KEY` from `.env`.
- `fetch_artist_tags(artists: list[str]) -> dict[str, list[str]]`: calls `artist.getTopTags`
  once per **unique** `artist_corrected` (not per song), returns top tags ordered by weight.
- Cache in `data/cache/lastfm_tag_cache.json` (same load/save-JSON pattern as
  `spotify_track_cache.json`), so re-runs are fast and idempotent.
- No new CSV output — a supplemental cache feeding Stage 4, like Stage 3's own caches.
- Rate limiting: Last.fm's soft cap (~5 req/sec) is a non-issue since calls are per unique
  artist, not per song — no special handling needed beyond a small delay if throttling appears.
- BPM has **no** planned automated source (see implementation-status note above) — out of scope.

**Not yet implemented** — `src/lastfm_api.py` doesn't exist yet; this section documents the
settled design for a future session.

## Stage 4 — Genre analysis (`src/genre_analysis.py`) — SCAFFOLD
Resolve each row's genre in priority order: (1) `genre_overrides.json` (manual, authoritative),
(2) `genre_hint` (PDF-derived, Stage 2), (3) Last.fm top tags filtered against the existing
`config.GENRE_KEYWORDS` vocabulary (Stage 3.5, once built), (4) Spotify `artist_genres` (kept as
a fallback in case Extended Quota Mode is ever granted). Produce final dataset
`song | artist | year | genre | subgenre | duration | bpm | popularity | liked` (`bpm` will stay
null — see BPM-out-of-scope note above).

## Stage 5 — Playlist creation (`src/playlist_creation.py`) — SCAFFOLD
Create a Spotify playlist from matched `track_id`s (batched ≤100 per add call).

## Stage 6 — Preference learning (`src/preferences.py`) — SCAFFOLD
After user fills `liked` (1/0), aggregate ratings by genre/artist/decade/BPM/energy; generate a
balanced playlist around top 3 genres while keeping diversity. Visuals in `notebooks/exploration.ipynb`.

---

## Dependencies (`requirements.txt`)
`pymupdf`, `pandas`, `rapidfuzz`, `spotipy`, `python-dotenv`, `matplotlib`, `seaborn`, `plotly`,
`jupyter`, `requests` (declared for the planned Stage 3.5 `lastfm_api.py`, no SDK needed).
(`camelot`/`tabula` not needed — the PDF is text, not ruled tables.)

Install into the existing empty `.venv`:
`.venv/Scripts/python.exe -m pip install -r requirements.txt`

## Spotify credentials setup (instructions in README)
1. Go to developer.spotify.com/dashboard → Create app.
2. Add Redirect URI `http://127.0.0.1:8888/callback`.
3. Copy Client ID/Secret into `.env` (from `.env.example`):
   `SPOTIPY_CLIENT_ID=`, `SPOTIPY_CLIENT_SECRET=`, `SPOTIPY_REDIRECT_URI=http://127.0.0.1:8888/callback`.

## Last.fm credentials setup (planned, for Stage 3.5)
1. Get a free API key at last.fm/api/account/create.
2. Copy it into `.env` (from `.env.example`): `LASTFM_API_KEY=`.

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

**Stage 3 (Spotify matching):** ran a 20-song slice (`spotify_api.run(limit=20)`) after Spotify
app creation + `.env` setup: 20/20 matched, correct track/artist/album/year (e.g. `24 K Magic` →
Bruno Mars, score 96.8); 3/20 flagged `low_confidence_match` (e.g. `Agachadita Mix`, no listed
artist, score 50); audio-features confirmed 403 and degraded to null as expected; `artist_genres`
and `popularity` came back empty for every row, including major artists — confirmed via a direct
`sp.artist()`/`sp.track()` call that the API returns no `genres`/`popularity` keys at all for this
app (Extended Quota Mode restriction, not a bug). Re-running the same slice hit the cache
(20/20 cache hits, <1s) and reproduced an identical CSV — idempotent, like Stages 1–2.

**Stage 3.5 (Last.fm genre tags):** planned, not yet implemented — design documented above,
verification deferred to the session that builds `src/lastfm_api.py` (fetch tags for a sample of
artists, confirm Latin-genre coverage, confirm cache idempotency).

**Later stages:** run the full 1164-row pipeline through `spotify_api.py` when ready; Stage 4
should plan around Spotify genres being unavailable and use the Stage 3.5 priority order above
once Last.fm is implemented.
