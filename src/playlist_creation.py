"""Stage 5 - Add matched tracks to a Spotify playlist.

Reads track IDs from songs_metadata.csv and adds them in batches of <=100
(Spotify API limit per add call).

NOTE: Development-mode Spotify apps get a 403 on POST /users/{id}/playlists
(playlist creation) even for the app owner with correct scopes - a Spotify
restriction, not a bug here (see PLAN.md). Create the playlist manually in
the Spotify app/web UI, then pass its ID/URL in.

Run:  python -m src.playlist_creation [playlist_id_or_url]
      (falls back to REPERTORIO_PLAYLIST_ID in .env if omitted)
"""
from __future__ import annotations

import os

import pandas as pd
from dotenv import load_dotenv

from . import config, spotify_api


def add_in_batches(sp, playlist_id: str, track_ids: list[str], size: int = 100) -> None:
    for i in range(0, len(track_ids), size):
        sp.playlist_add_items(playlist_id, track_ids[i : i + size])


def remove_in_batches(sp, playlist_id: str, track_ids: list[str], size: int = 100) -> None:
    for i in range(0, len(track_ids), size):
        sp.playlist_remove_all_occurrences_of_items(playlist_id, track_ids[i : i + size])


def run(
    playlist_id: str,
    metadata_csv=config.SONGS_METADATA_CSV,
    limit: int | None = None,
    remove: bool = False,
) -> str:
    """Add (or, with remove=True, remove) matched tracks on an existing playlist
    (create it manually first - see module docstring)."""
    if not metadata_csv.exists():
        raise FileNotFoundError(f"{metadata_csv} not found. Run stage 3 (src.spotify_api) first.")

    df = pd.read_csv(metadata_csv, encoding="utf-8", keep_default_na=False)
    track_ids = [t for t in df["track_id"].tolist() if t]
    if limit is not None:
        track_ids = track_ids[:limit]
    if not track_ids:
        raise ValueError("No matched track_ids found.")

    sp = spotify_api.get_client()
    if remove:
        remove_in_batches(sp, playlist_id, track_ids)
        verb = "removed"
    else:
        add_in_batches(sp, playlist_id, track_ids)
        verb = "added"

    playlist = sp.playlist(playlist_id, fields="external_urls,name")
    url = playlist["external_urls"]["spotify"]
    print(f"[stage 5] {verb} {len(track_ids)} tracks {'from' if remove else 'to'} '{playlist['name']}' -> {url}")
    return url


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "playlist_id",
        nargs="?",
        default=None,
        help="Spotify playlist ID or URL (create it manually first). "
        "Defaults to REPERTORIO_PLAYLIST_ID in .env if omitted.",
    )
    parser.add_argument("--remove", action="store_true", help="remove matched tracks instead of adding them")
    parser.add_argument("--limit", type=int, default=None, help="only process the first N matched tracks")
    args = parser.parse_args()

    load_dotenv()
    playlist_id = args.playlist_id or os.getenv("REPERTORIO_PLAYLIST_ID")
    if not playlist_id:
        raise SystemExit(
            "No playlist given. Pass one, or set REPERTORIO_PLAYLIST_ID in .env."
        )

    run(playlist_id, limit=args.limit, remove=args.remove)
