"""Stage 3 - Match cleaned songs to Spotify and pull metadata. (SCAFFOLD)

Input : data/processed/songs_clean.csv
Output: data/processed/songs_metadata.csv

Status: scaffold. The search/match flow is sketched and runnable once Spotify
credentials exist in a .env file (see .env.example). Audio features are
attempted but degrade gracefully to null if the endpoint is unavailable
(deprecated for new apps since Nov 2024).

Run:  python -m src.spotify_api
"""
from __future__ import annotations

import os

import pandas as pd
from dotenv import load_dotenv
from rapidfuzz import fuzz

from . import config

# Columns the rest of the pipeline expects this stage to produce.
METADATA_COLUMNS = [
    "line_no", "song_clean", "artist_corrected",
    "track_id", "official_artist", "album", "year", "duration_ms",
    "popularity", "artist_genres", "match_score",
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


def run(in_csv=config.SONGS_CLEAN_CSV, out_csv=config.SONGS_METADATA_CSV) -> pd.DataFrame:
    raise NotImplementedError(
        "Stage 3 is a scaffold. Wire match_row()/fetch_audio_features() into a "
        "loop over songs_clean.csv (with caching + rate limiting) once Spotify "
        "credentials are configured in .env."
    )


if __name__ == "__main__":
    run()
