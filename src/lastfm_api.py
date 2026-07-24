"""Stage 3.5 - Fetch Last.fm genre tags per unique artist.

Input : data/processed/songs_clean.csv (artist_corrected column)
Output: data/cache/lastfm_tag_cache.json (supplemental cache for Stage 4;
        no new CSV - Spotify apps without Extended Quota Mode return no
        genres, so this fills that gap with Last.fm's crowd-sourced tags)

Requires LASTFM_API_KEY in a .env file (see .env.example).

Run:  python -m src.lastfm_api
"""
from __future__ import annotations

import json
import os

import pandas as pd
import requests
from dotenv import load_dotenv

from . import config

LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"


def _load_cache(path) -> dict:
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_cache(path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fetch_artist_tags(artists: list[str], api_key: str | None = None) -> dict[str, list[str]]:
    """Fetch Last.fm top tags (weight-sorted) for each unique artist.

    Network/lookup failures degrade to an empty tag list for that artist.
    """
    load_dotenv()
    api_key = api_key or os.getenv("LASTFM_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Last.fm credentials missing. Copy .env.example to .env and fill in LASTFM_API_KEY."
        )

    tags: dict[str, list[str]] = {}
    for artist in dict.fromkeys(artists):  # dedupe, preserve order
        params = {
            "method": "artist.gettoptags",
            "artist": artist,
            "autocorrect": 1,
            "api_key": api_key,
            "format": "json",
        }
        try:
            resp = requests.get(LASTFM_API_URL, params=params, timeout=10)
            data = resp.json()
            if "error" in data:
                print(f"[stage 3.5] no tags for {artist!r}: {data.get('message')}")
                tags[artist] = []
            else:
                tags[artist] = [t["name"] for t in data.get("toptags", {}).get("tag", [])]
        except Exception as exc:  # noqa: BLE001 - degrade gracefully like Stage 3
            print(f"[stage 3.5] Last.fm lookup failed for {artist!r}: {exc}")
            tags[artist] = []
    return tags


def run(
    in_csv=config.SONGS_CLEAN_CSV,
    out_cache=config.LASTFM_TAG_CACHE_JSON,
    limit: int | None = None,
) -> dict[str, list[str]]:
    config.ensure_dirs()
    if not in_csv.exists():
        raise FileNotFoundError(f"{in_csv} not found. Run stage 2 (src.cleaning) first.")

    load_dotenv()
    api_key = os.getenv("LASTFM_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Last.fm credentials missing. Copy .env.example to .env and fill in LASTFM_API_KEY."
        )

    df = pd.read_csv(in_csv, encoding="utf-8", keep_default_na=False)
    artists = list(dict.fromkeys(df["artist_corrected"].tolist()))
    if limit is not None:
        artists = artists[:limit]

    cache = _load_cache(out_cache)
    n = len(artists)
    tagged = 0
    for i, artist in enumerate(artists, start=1):
        if artist in cache:
            if cache[artist]:
                tagged += 1
            continue
        result = fetch_artist_tags([artist], api_key=api_key)
        cache[artist] = result[artist]
        if result[artist]:
            tagged += 1

        if i % 25 == 0:
            _save_cache(out_cache, cache)
        if i % 50 == 0 or i == n:
            print(f"[stage 3.5] tagged {i}/{n} artists")

    _save_cache(out_cache, cache)
    print(f"[stage 3.5] done: {tagged}/{n} artists with tags -> {out_cache}")
    return cache


if __name__ == "__main__":
    run()
