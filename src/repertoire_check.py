"""Check an arbitrary song list against the band's repertoire (this project's PDF).

Fuzzy-matches each input song (optionally with artist) against
songs_clean.csv - no Spotify/Last.fm calls, so it's instant and free to
re-run. Input file: one song per line, formatted as "Song - Artist",
"Song, Artist", or just "Song" (artist optional).

Run:  python -m src.repertoire_check <list.txt> [--out results.csv] [--threshold 80]
"""
from __future__ import annotations

import argparse

import pandas as pd
from rapidfuzz import fuzz, utils

from . import config

_SPLIT_SEPS = [" - ", " – ", ",", " by "]


def parse_line(line: str) -> tuple[str, str]:
    """Parse one "Song - Artist" / "Song, Artist" / "Song" line -> (song, artist)."""
    song, artist = line, ""
    for sep in _SPLIT_SEPS:
        if sep in line:
            song, artist = line.split(sep, 1)
            break
    return song.strip(), artist.strip()


def parse_song_list(path) -> list[tuple[str, str]]:
    """Parse a file of "Song - Artist" / "Song, Artist" / "Song" lines -> [(song, artist), ...]."""
    songs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                songs.append(parse_line(line))
    return songs


def _score(song: str, artist: str, cand_song: str, cand_artist: str) -> float:
    # processor=utils.default_process: lowercases and strips punctuation before
    # comparing, so case/apostrophe differences don't tank an otherwise-exact match.
    song_score = fuzz.token_sort_ratio(song, cand_song, processor=utils.default_process)
    if not artist:
        return song_score
    artist_score = fuzz.token_sort_ratio(artist, cand_artist, processor=utils.default_process)
    return 0.7 * song_score + 0.3 * artist_score


def check_songs(
    songs: list[tuple[str, str]],
    repertoire: pd.DataFrame,
    threshold: float = 80,
) -> pd.DataFrame:
    rows = []
    for song, artist in songs:
        best_score, best = -1.0, None
        for cand in repertoire.itertuples(index=False):
            s = _score(song, artist, cand.song_clean, cand.artist_corrected)
            if s > best_score:
                best_score, best = s, cand
        rows.append(
            {
                "query_song": song,
                "query_artist": artist,
                "in_repertoire": best_score >= threshold,
                "match_score": round(best_score, 1),
                "matched_line_no": best.line_no if best else None,
                "matched_song": best.song_clean if best else None,
                "matched_artist": best.artist_corrected if best else None,
            }
        )
    return pd.DataFrame(rows)


def run(list_path, out_csv=None, threshold: float = 80) -> pd.DataFrame:
    if not config.SONGS_CLEAN_CSV.exists():
        raise FileNotFoundError(f"{config.SONGS_CLEAN_CSV} not found. Run stage 2 (src.cleaning) first.")

    songs = parse_song_list(list_path)
    repertoire = pd.read_csv(config.SONGS_CLEAN_CSV, encoding="utf-8", keep_default_na=False)
    result = check_songs(songs, repertoire, threshold=threshold)

    if out_csv:
        result.to_csv(out_csv, index=False, encoding="utf-8")

    n_in = int(result["in_repertoire"].sum())
    print(f"[repertoire_check] {n_in}/{len(result)} songs found in the repertoire" + (f" -> {out_csv}" if out_csv else ""))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("list_path", help="text file, one song per line ('Song - Artist' or just 'Song')")
    parser.add_argument("--out", default=None, help="write full results to this CSV")
    parser.add_argument("--threshold", type=float, default=80, help="match score (0-100) to count as 'in repertoire'")
    args = parser.parse_args()

    result = run(args.list_path, out_csv=args.out, threshold=args.threshold)
    pd.set_option("display.max_rows", None, "display.width", None)
    print(result)
