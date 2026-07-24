"""Stage 3 - Match cleaned songs to Spotify and pull metadata.

Input : data/processed/songs_clean.csv
Output: data/processed/songs_metadata.csv

Requires Spotify credentials in a .env file (see .env.example). Track lookups
are cached under data/cache/ so re-runs are fast and idempotent. Audio
features are attempted but degrade gracefully to null if the endpoint is
unavailable (deprecated for new apps since Nov 2024). If Spotify's rate limit
is hit, the run stops cleanly and saves progress - re-run later to resume.

Run:  python -m src.spotify_api
"""
from __future__ import annotations

import json
import os
import time

import pandas as pd
from dotenv import load_dotenv
from rapidfuzz import fuzz

from . import config

# Delay between Spotify calls to avoid tripping the API's rate limit (which,
# once tripped, can impose a multi-hour cooldown - see get_client()'s retries=0).
REQUEST_DELAY_S = 0.1

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
    # retries=0: on a 429 we want to catch it ourselves and stop cleanly (see
    # run()) rather than have spotipy/urllib3 block for the full Retry-After
    # window, which can be tens of thousands of seconds.
    return spotipy.Spotify(auth_manager=auth, retries=0)


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


# NOTE: sp.artist() genre/popularity lookups were removed here - verified in
# testing that apps without Extended Quota Mode get an empty `genres` list for
# every artist, so the call only doubled our request volume for zero benefit
# (a real contributor to tripping Spotify's rate limit). artist_genres stays
# in the output schema (always empty) for Stage 4 fallback compatibility, and
# can be restored if Extended Quota Mode is ever granted.


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

    import spotipy

    sp = get_client()
    track_cache = _load_cache(config.SPOTIFY_TRACK_CACHE_JSON)

    rows = []
    cache_hits = 0
    n = len(df)
    stopped_early = False
    for i, row in enumerate(df.itertuples(index=False), start=1):
        song = row.song_clean
        artist = row.artist_corrected
        key = _track_cache_key(song, artist)

        if key in track_cache:
            cache_hits += 1
            summary = track_cache[key]
        else:
            try:
                match = match_row(sp, song, artist)
            except spotipy.SpotifyException as exc:
                if exc.http_status == 429:
                    retry_after = (exc.headers or {}).get("Retry-After", "unknown")
                    _save_cache(config.SPOTIFY_TRACK_CACHE_JSON, track_cache)
                    print(
                        f"[stage 3] rate limited after {i - 1}/{n} rows "
                        f"(retry after {retry_after}s). Progress saved to cache; "
                        f"re-run later to resume from here."
                    )
                    stopped_early = True
                    break
                raise
            summary = _summarize_match(match)
            track_cache[key] = summary
            time.sleep(REQUEST_DELAY_S)

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
            "artist_genres": None,
            "match_score": summary.get("match_score") if summary else None,
            "low_confidence_match": (
                summary is None
                or summary["match_score"] < config.MATCH_LOW_CONFIDENCE_THRESHOLD
            ),
        }
        rows.append(out)

        if i % 25 == 0:
            _save_cache(config.SPOTIFY_TRACK_CACHE_JSON, track_cache)
        if i % 50 == 0 or i == n:
            print(f"[stage 3] matched {i}/{n} (cache hits: {cache_hits})")

    _save_cache(config.SPOTIFY_TRACK_CACHE_JSON, track_cache)

    out_df = pd.DataFrame(rows, columns=METADATA_COLUMNS[:-6])

    # Batch audio-features lookups (Spotify allows up to 100 ids per call).
    # Skip entirely if we just got rate limited, to avoid tripping it again.
    track_ids = [] if stopped_early else [t for t in out_df["track_id"].tolist() if t]
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
    status = "PARTIAL (rate limited, re-run to continue)" if stopped_early else "done"
    print(
        f"[stage 3] {status}: {matched}/{n} matched, {low_conf} low-confidence -> {out_csv}"
    )
    return out_df


if __name__ == "__main__":
    run()
