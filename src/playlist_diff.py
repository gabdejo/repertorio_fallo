"""Show tracks in one Spotify playlist that are missing from another.

Left difference: tracks in playlist A not present in playlist B (by track ID).

Run:  python -m src.playlist_diff <playlist_a> [playlist_b] [--out results.csv]
      (playlist_b defaults to REPERTORIO_PLAYLIST_ID in .env if omitted)
"""
from __future__ import annotations

import argparse
import os

import pandas as pd
from dotenv import load_dotenv

from . import spotify_api


def get_playlist_tracks(sp, playlist_id: str) -> pd.DataFrame:
    """Fetch all tracks in a playlist (paginated, 100 per call).

    Spotify has been inconsistently returning the track object under an
    "item" key instead of the documented "track" key for some playlists -
    check both.
    """
    rows = []
    results = sp.playlist_items(playlist_id)
    while results:
        for entry in results["items"]:
            track = entry.get("track") or entry.get("item")
            if not track or not track.get("id"):
                continue
            rows.append(
                {
                    "track_id": track["id"],
                    "name": track["name"],
                    "artist": ", ".join(a["name"] for a in track.get("artists", [])),
                }
            )
        results = sp.next(results) if results.get("next") else None
    return pd.DataFrame(rows, columns=["track_id", "name", "artist"])


def run(playlist_a: str, playlist_b: str, out_csv=None) -> pd.DataFrame:
    sp = spotify_api.get_client()
    tracks_a = get_playlist_tracks(sp, playlist_a)
    tracks_b = get_playlist_tracks(sp, playlist_b)

    missing = tracks_a[~tracks_a["track_id"].isin(tracks_b["track_id"])]

    if out_csv:
        missing.to_csv(out_csv, index=False, encoding="utf-8")

    print(
        f"[playlist_diff] {len(missing)}/{len(tracks_a)} tracks in playlist A "
        f"are missing from playlist B" + (f" -> {out_csv}" if out_csv else "")
    )
    return missing


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("playlist_a", help="playlist ID/URL to check (the smaller/niche one)")
    parser.add_argument(
        "playlist_b",
        nargs="?",
        default=None,
        help="playlist ID/URL to check against. Defaults to REPERTORIO_PLAYLIST_ID in .env.",
    )
    parser.add_argument("--out", default=None, help="write results to this CSV")
    args = parser.parse_args()

    load_dotenv()
    playlist_b = args.playlist_b or os.getenv("REPERTORIO_PLAYLIST_ID")
    if not playlist_b:
        raise SystemExit("No second playlist given. Pass one, or set REPERTORIO_PLAYLIST_ID in .env.")

    result = run(args.playlist_a, playlist_b, out_csv=args.out)
    pd.set_option("display.max_rows", None, "display.width", None)
    print(result)
