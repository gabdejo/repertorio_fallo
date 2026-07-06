"""Stage 5 - Create a Spotify playlist from matched track IDs. (SCAFFOLD)

Reads track IDs from songs_metadata.csv, creates a playlist, and adds tracks
in batches of <=100 (Spotify API limit per add call).

Run:  python -m src.playlist_creation
"""
from __future__ import annotations

from . import spotify_api


def add_in_batches(sp, playlist_id: str, track_ids: list[str], size: int = 100) -> None:
    for i in range(0, len(track_ids), size):
        sp.playlist_add_items(playlist_id, track_ids[i : i + size])


def run(playlist_name: str = "Repertorio - Para Calificar") -> None:
    raise NotImplementedError(
        "Stage 5 scaffold: load track_ids from songs_metadata.csv, create the "
        "playlist via sp.user_playlist_create(...), then call add_in_batches()."
    )
    _ = spotify_api  # referenced to make the dependency explicit


if __name__ == "__main__":
    run()
