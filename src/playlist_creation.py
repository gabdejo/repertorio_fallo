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
import re

import pandas as pd
from dotenv import load_dotenv

from . import config, spotify_api


def _pid(s: str | None) -> str:
    """Bare 22-char playlist id from an id or a full open.spotify.com URL."""
    return (re.search(r"[A-Za-z0-9]{22}", s or "") or [""])[0]


def guard(playlist_id: str) -> None:
    """Refuse any write to the hand-curated screen playlist (SCREEN_PLAYLIST_ID),
    which is read-only for this project. Every playlist write in src/ routes
    through add_in_batches / remove_in_batches / clear, so this is the one gate.
    Deliberate override only: ALLOW_PROTECTED_PLAYLIST_WRITES=1 in the environment."""
    load_dotenv()
    if os.getenv("ALLOW_PROTECTED_PLAYLIST_WRITES") == "1":
        return
    protected = _pid(os.getenv("SCREEN_PLAYLIST_ID"))
    if protected and _pid(playlist_id) == protected:
        raise PermissionError(
            f"Playlist {playlist_id} is the protected screen playlist (read-only). "
            "Pass a different playlist, or set ALLOW_PROTECTED_PLAYLIST_WRITES=1 on purpose."
        )


def add_in_batches(sp, playlist_id: str, track_ids: list[str], size: int = 100) -> None:
    guard(playlist_id)
    for i in range(0, len(track_ids), size):
        sp.playlist_add_items(playlist_id, track_ids[i : i + size])


def remove_in_batches(sp, playlist_id: str, track_ids: list[str], size: int = 100) -> None:
    guard(playlist_id)
    for i in range(0, len(track_ids), size):
        sp.playlist_remove_all_occurrences_of_items(playlist_id, track_ids[i : i + size])


def clear(sp, playlist_id: str) -> None:
    """Empty a playlist (replace its contents with nothing) - one call, no batching needed."""
    guard(playlist_id)
    sp.playlist_replace_items(playlist_id, [])


def run(
    playlist_id: str,
    metadata_csv=config.SONGS_METADATA_CSV,
    limit: int | None = None,
    remove: bool = False,
    clear_first: bool = False,
) -> str:
    """Add (or, with remove=True, remove) matched tracks on an existing playlist
    (create it manually first - see module docstring). clear_first=True empties
    the playlist before adding - use for a clean re-ingestion instead of
    duplicating unchanged tracks."""
    if not metadata_csv.exists():
        raise FileNotFoundError(f"{metadata_csv} not found. Run stage 3 (src.spotify_api) first.")

    df = pd.read_csv(metadata_csv, encoding="utf-8", keep_default_na=False)
    track_ids = [t for t in df["track_id"].tolist() if t]
    if limit is not None:
        track_ids = track_ids[:limit]
    if not track_ids:
        raise ValueError("No matched track_ids found.")

    sp = spotify_api.get_client()

    if clear_first:
        if remove:
            raise ValueError("clear_first and remove are mutually exclusive.")
        clear(sp, playlist_id)
        print("[stage 5] cleared playlist before re-ingesting")

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
    parser.add_argument(
        "--clear", action="store_true", help="empty the playlist first, for a clean re-ingestion (no duplicates)"
    )
    parser.add_argument("--limit", type=int, default=None, help="only process the first N matched tracks")
    args = parser.parse_args()

    load_dotenv()
    playlist_id = args.playlist_id or os.getenv("REPERTORIO_PLAYLIST_ID")
    if not playlist_id:
        raise SystemExit(
            "No playlist given. Pass one, or set REPERTORIO_PLAYLIST_ID in .env."
        )

    run(playlist_id, limit=args.limit, remove=args.remove, clear_first=args.clear)
