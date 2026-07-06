"""Stage 3 - Match cleaned songs to Spotify and pull metadata.

Input : data/processed/songs_clean.csv
Output: data/processed/songs_metadata.csv

Requires Spotify credentials in a .env file (see .env.example). Track and
artist-genre lookups are cached under data/cache/ so re-runs are fast and
idempotent. Audio features are attempted but degrade gracefully to null if
the endpoint is unavailable (deprecated for new apps since Nov 2024).

Run:  python -m src.spotify_api
"""
from __future__ import annotations

import json
import os

import pandas as pd
from dotenv import load_dotenv
from rapidfuzz import fuzz

from . import config

# Columns the rest of the pipeline expects this stage to produce.
METADATA_COLUMNS = [
    "line_no", "song_clean", "artist_corrected",
    "track_id", "official_artist", "album", "year", "duration_ms",
    "popularity", "artist_genres", "match_score", "low_confidence_match",
    # audio features (may be null if endpoint unavailable):
    "bpm", "energy", "danceability", "acousticness", "valence", "loudness",
]


def get_client():
    """Return an authenticated spotipy client (import is local so the rest of
    the pipeline works without spotipy/credentials installed)."""
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth

    load_dotenv()
    if not os.getenv("SPOTIPY_CLIENT_ID"):
        raise RuntimeError(
            "Spotify credentials missing. Copy .env.example to .env and fill it in."
        )
    auth = SpotifyOAuth(scope="playlist-modify-private playlist-modify-public")
    return spotipy.Spotify(auth_manager=auth)


def _score(query_song: str, query_artist: str, track: dict) -> float:
    name = track.get("name", "")
    artists = ", ".join(a["name"] for a in track.get("artists", []))
    return 0.6 * fuzz.token_sort_ratio(query_song, name) + 0.4 * fuzz.token_sort_ratio(
        query_artist, artists
    )


def match_row(sp, song: str, artist: str) -> dict | None:
    """Search Spotify for one (song, artist) and return the best candidate."""
    q = f"track:{song} artist:{artist}" if artist else f"track:{song}"
    items = sp.search(q=q, type="track", limit=10).get("tracks", {}).get("items", [])
    if not items:
        items = sp.search(q=f"{song} {artist}".strip(), type="track", limit=10) \
            .get("tracks", {}).get("items", [])
    if not items:
        return None
    best = max(items, key=lambda t: _score(song, artist, t))
    return {"track": best, "match_score": round(_score(song, artist, best), 1)}


def fetch_audio_features(sp, track_ids: list[str]) -> dict[str, dict]:
    """Attempt audio features; return {} if the endpoint is unavailable."""
    try:
        feats = sp.audio_features(track_ids)
        return {f["id"]: f for f in feats if f}
    except Exception as exc:  # noqa: BLE001 - deprecated endpoint -> degrade
        print(f"[stage 3] audio-features unavailable ({exc}); leaving features null.")
        return {}


def _load_cache(path) -> dict:
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_cache(path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _track_cache_key(song: str, artist: str) -> str:
    return f"{song}|||{artist}"


def _summarize_match(match: dict | None) -> dict | None:
    """Reduce a match_row() result to the plain-data fields we persist/cache."""
    if match is None:
        return None
    track = match["track"]
    artists = track.get("artists", [])
    release_date = track.get("album", {}).get("release_date", "")
    return {
        "track_id": track.get("id"),
        "official_artist": ", ".join(a["name"] for a in artists),
        "artist_id": artists[0]["id"] if artists else None,
        "album": track.get("album", {}).get("name"),
        "year": release_date[:4] if release_date else None,
        "duration_ms": track.get("duration_ms"),
        "popularity": track.get("popularity"),
        "match_score": match["match_score"],
    }


def _fetch_artist_genres(sp, artist_id: str | None, genre_cache: dict) -> list[str]:
    if not artist_id:
        return []
    if artist_id in genre_cache:
        return genre_cache[artist_id]
    genres = sp.artist(artist_id).get("genres", [])
    genre_cache[artist_id] = genres
    return genres


def run(
    in_csv=config.SONGS_CLEAN_CSV,
    out_csv=config.SONGS_METADATA_CSV,
    limit: int | None = None,
) -> pd.DataFrame:
    config.ensure_dirs()
    if not in_csv.exists():
        raise FileNotFoundError(
            f"{in_csv} not found. Run stage 2 (src.cleaning) first."
        )

    df = pd.read_csv(in_csv, encoding="utf-8", keep_default_na=False)
    if limit is not None:
        df = df.head(limit).copy()

    sp = get_client()
    track_cache = _load_cache(config.SPOTIFY_TRACK_CACHE_JSON)
    genre_cache = _load_cache(config.SPOTIFY_ARTIST_GENRE_CACHE_JSON)

    rows = []
    cache_hits = 0
    n = len(df)
    for i, row in enumerate(df.itertuples(index=False), start=1):
        song = row.song_clean
        artist = row.artist_corrected
        key = _track_cache_key(song, artist)

        if key in track_cache:
            cache_hits += 1
            summary = track_cache[key]
        else:
            match = match_row(sp, song, artist)
            summary = _summarize_match(match)
            track_cache[key] = summary

        genres = _fetch_artist_genres(sp, (summary or {}).get("artist_id"), genre_cache)

        out = {
            "line_no": row.line_no,
            "song_clean": song,
            "artist_corrected": artist,
            "track_id": summary.get("track_id") if summary else None,
            "official_artist": summary.get("official_artist") if summary else None,
            "album": summary.get("album") if summary else None,
            "year": summary.get("year") if summary else None,
            "duration_ms": summary.get("duration_ms") if summary else None,
            "popularity": summary.get("popularity") if summary else None,
            "artist_genres": ", ".join(genres) if genres else None,
            "match_score": summary.get("match_score") if summary else None,
            "low_confidence_match": (
                summary is None
                or summary["match_score"] < config.MATCH_LOW_CONFIDENCE_THRESHOLD
            ),
        }
        rows.append(out)

        if i % 25 == 0:
            _save_cache(config.SPOTIFY_TRACK_CACHE_JSON, track_cache)
            _save_cache(config.SPOTIFY_ARTIST_GENRE_CACHE_JSON, genre_cache)
        if i % 50 == 0 or i == n:
            print(f"[stage 3] matched {i}/{n} (cache hits: {cache_hits})")

    _save_cache(config.SPOTIFY_TRACK_CACHE_JSON, track_cache)
    _save_cache(config.SPOTIFY_ARTIST_GENRE_CACHE_JSON, genre_cache)

    out_df = pd.DataFrame(rows, columns=METADATA_COLUMNS[:-6])

    # Batch audio-features lookups (Spotify allows up to 100 ids per call).
    track_ids = [t for t in out_df["track_id"].tolist() if t]
    features: dict[str, dict] = {}
    for start in range(0, len(track_ids), 100):
        chunk = track_ids[start : start + 100]
        features.update(fetch_audio_features(sp, chunk))

    feature_cols = ["bpm", "energy", "danceability", "acousticness", "valence", "loudness"]
    feature_key_map = {
        "bpm": "tempo",
        "energy": "energy",
        "danceability": "danceability",
        "acousticness": "acousticness",
        "valence": "valence",
        "loudness": "loudness",
    }
    for col in feature_cols:
        src_key = feature_key_map[col]
        out_df[col] = out_df["track_id"].map(
            lambda tid: features.get(tid, {}).get(src_key) if tid else None
        )

    out_df = out_df[METADATA_COLUMNS]
    out_df.to_csv(out_csv, index=False, encoding="utf-8")

    matched = out_df["track_id"].notna().sum()
    low_conf = out_df["low_confidence_match"].sum()
    with_genres = out_df["artist_genres"].notna().sum()
    print(
        f"[stage 3] done: {matched}/{n} matched, {low_conf} low-confidence, "
        f"{with_genres} with artist genres -> {out_csv}"
    )
    return out_df


if __name__ == "__main__":
    run()
