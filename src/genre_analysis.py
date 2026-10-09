"""Stage 4 - Resolve genre/subgenre per song and build the final dataset.

Input : data/processed/songs_metadata.csv, data/processed/songs_clean.csv,
        data/cache/lastfm_tag_cache.json, data/dictionaries/genre_overrides.json
Output: data/processed/songs_final.csv
    columns: line_no, song, artist, year, genre, subgenre, duration, bpm, popularity, liked
    (line_no is kept as a stable cross-reference back to songs_raw.csv/songs_clean.csv -
    row position isn't reliable since rows can be excluded or tables re-sorted)

Genre is resolved per song in priority order: (1) genre_overrides.json
(manual, authoritative), (2) genre_hint (PDF-derived, Stage 2), (3) Last.fm
top tags (Stage 3.5) filtered against config.GENRE_CANONICAL, (4) Spotify
artist_genres (fallback, currently empty without Extended Quota Mode).
``liked`` is left blank for manual rating.

Run:  python -m src.genre_analysis
"""
from __future__ import annotations

import json

import pandas as pd

from . import config


def load_overrides(path=config.GENRE_OVERRIDES_JSON) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def _load_lastfm_cache() -> dict:
    if not config.LASTFM_TAG_CACHE_JSON.exists():
        return {}
    with open(config.LASTFM_TAG_CACHE_JSON, encoding="utf-8") as f:
        return json.load(f)


def _first_canonical(values: list[str]) -> str | None:
    """Return the first value (in order) that matches config.GENRE_CANONICAL."""
    for v in values:
        canon = config.GENRE_CANONICAL.get(v.strip().lower())
        if canon:
            return canon
    return None


def resolve_genre(
    artist: str,
    hint: str,
    lastfm_tags: list[str],
    spotify_genres: list[str],
    overrides: dict,
) -> tuple[str | None, str | None, str]:
    """Resolve (genre, subgenre, source) for one song's artist."""
    override = overrides.get(artist)
    if override:
        return override.get("genre"), override.get("subgenre"), "override"

    if hint:
        genre = _first_canonical(hint.split(", "))
        if genre:
            return genre, None, "hint"

    genre = _first_canonical(lastfm_tags)
    if genre:
        return genre, None, "lastfm"

    genre = _first_canonical(spotify_genres)
    if genre:
        return genre, None, "spotify"

    return None, None, "missing"


def run(
    metadata_csv=config.SONGS_METADATA_CSV,
    clean_csv=config.SONGS_CLEAN_CSV,
    lastfm_cache_path=config.LASTFM_TAG_CACHE_JSON,
    out_csv=config.SONGS_FINAL_CSV,
) -> pd.DataFrame:
    config.ensure_dirs()
    if not metadata_csv.exists():
        raise FileNotFoundError(f"{metadata_csv} not found. Run stage 3 (src.spotify_api) first.")
    if not clean_csv.exists():
        raise FileNotFoundError(f"{clean_csv} not found. Run stage 2 (src.cleaning) first.")

    meta = pd.read_csv(metadata_csv, encoding="utf-8", keep_default_na=False)
    hints = pd.read_csv(clean_csv, encoding="utf-8", keep_default_na=False)[
        ["line_no", "genre_hint"]
    ]
    # left-merge can leave NaN genre_hint for metadata rows stale relative to a
    # since-excluded/regenerated songs_clean.csv - treat those as "no hint".
    df = meta.merge(hints, on="line_no", how="left")
    df["genre_hint"] = df["genre_hint"].fillna("")

    overrides = load_overrides()
    lastfm_cache = _load_lastfm_cache()

    sources = {"override": 0, "hint": 0, "lastfm": 0, "spotify": 0, "missing": 0}
    rows = []
    for row in df.itertuples(index=False):
        artist = row.artist_corrected
        hint = row.genre_hint or ""
        lastfm_tags = lastfm_cache.get(artist, [])
        spotify_genres = [g.strip() for g in (row.artist_genres or "").split(",") if g.strip()]

        genre, subgenre, source = resolve_genre(artist, hint, lastfm_tags, spotify_genres, overrides)
        sources[source] += 1

        rows.append(
            {
                "line_no": row.line_no,
                "song": row.song_clean,
                "artist": artist,
                "year": row.year,
                "genre": genre,
                "subgenre": subgenre,
                "duration": row.duration_ms,
                "bpm": row.bpm,
                "popularity": row.popularity,
                "liked": None,
            }
        )

    out_df = pd.DataFrame(
        rows,
        columns=["line_no", "song", "artist", "year", "genre", "subgenre", "duration", "bpm", "popularity", "liked"],
    )
    out_df.to_csv(out_csv, index=False, encoding="utf-8")

    n = len(out_df)
    print(
        f"[stage 4] genre resolved for {n - sources['missing']}/{n} songs "
        f"(override: {sources['override']}, hint: {sources['hint']}, "
        f"lastfm: {sources['lastfm']}, spotify: {sources['spotify']}, "
        f"missing: {sources['missing']}) -> {out_csv}"
    )
    return out_df


if __name__ == "__main__":
    run()
