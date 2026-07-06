"""Stage 4 - Build artist->genre/subgenre table and the final dataset. (SCAFFOLD)

Combines Spotify artist genres + the ``genre_hint`` column from cleaning +
manual overrides in data/dictionaries/genre_overrides.json.

Final dataset columns:
    song | artist | year | genre | subgenre | duration | bpm | popularity | liked

Run:  python -m src.genre_analysis
"""
from __future__ import annotations

import json

from . import config


def load_overrides() -> dict:
    if not config.GENRE_OVERRIDES_JSON.exists():
        return {}
    with open(config.GENRE_OVERRIDES_JSON, encoding="utf-8") as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def run() -> None:
    raise NotImplementedError(
        "Stage 4 scaffold: join songs_metadata.csv with genre_hint + overrides, "
        "collapse Spotify's many micro-genres into a primary genre/subgenre, and "
        "emit the final dataset with an empty 'liked' column for rating."
    )


if __name__ == "__main__":
    run()
