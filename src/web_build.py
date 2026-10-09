"""Build web/songs.json - the closed song universe for the picker page (web/index.html)
from the screen-playlist report. The page never reads the screen playlist from
Spotify, so this file is also an offline snapshot of its track ids.

Run:  python -m src.preferences report --out data/processed/screen_playlist.csv
      python -m src.web_build
"""
from __future__ import annotations

import json

import pandas as pd

from . import config

SCREEN_CSV = config.PROCESSED / "screen_playlist.csv"
OUT = config.ROOT / "web" / "songs.json"


def run() -> None:
    df = pd.read_csv(SCREEN_CSV, encoding="utf-8", keep_default_na=False)
    rows = [
        {
            "id": r.track_id,
            "name": r.name,
            "artist": r.artist,
            "genre": r.genre or "Sin género",
            "year": int(float(r.year)) if r.year else None,
        }
        for r in df.itertuples()
    ]
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[web] wrote {len(rows)} songs -> {OUT}")


if __name__ == "__main__":
    run()
