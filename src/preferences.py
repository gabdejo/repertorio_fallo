"""Stage 6 - Screen playlist workflow.

The user hand-curates a "screen" playlist in Spotify (a subset of the
repertoire plus occasional outside additions) and it stays the source of
truth for favoritism - membership in it IS the "liked" signal, no separate
rating needed. This stage stitches together the tools built to support that:

    check <song-or-list>   Fuzzy-check a candidate song (or list file) against
                            the repertoire (data/processed/songs_clean.csv),
                            attaching a Spotify track_id for confirmed matches.
    add <ids-or-csv>       Add confirmed track(s) to the screen playlist -
                            either explicit comma-separated track_ids, or a
                            `check` output CSV (adds every in_repertoire row).
    report                 Fetch the screen playlist live, join it back to
                            songs_final.csv by track_id, and print genre/year
                            coverage. Anything outside the repertoire gets a
                            live Last.fm genre lookup.
    label                  Export/reload the two missing-genre worklists for
                            the screen playlist (matched -> fix via
                            genre_overrides.json; unmatched -> fill-in CSV).

Run:  python -m src.preferences <check|add|report|label> ...
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from . import config, genre_analysis, lastfm_api, playlist_creation, playlist_diff, repertoire_check, spotify_api

MATCHED_MISSING_CSV = config.PROCESSED / "playlist_review_matched_missing_genre.csv"
UNMATCHED_FILL_CSV = config.PROCESSED / "playlist_review_unmatched_missing_genre.csv"


def _screen_playlist_id(playlist_id: str | None) -> str:
    load_dotenv()
    playlist_id = playlist_id or os.getenv("SCREEN_PLAYLIST_ID")
    if not playlist_id:
        raise ValueError("No playlist given. Pass one, or set SCREEN_PLAYLIST_ID in .env.")
    return playlist_id


def check(source: str, threshold: float = 80, out_csv=None) -> pd.DataFrame:
    """Fuzzy-check a song (or list file) against the repertoire; attach track_id for matches."""
    if not config.SONGS_CLEAN_CSV.exists():
        raise FileNotFoundError(f"{config.SONGS_CLEAN_CSV} not found. Run stage 2 (src.cleaning) first.")

    path = Path(source)
    songs = repertoire_check.parse_song_list(path) if path.exists() else [repertoire_check.parse_line(source)]

    repertoire = pd.read_csv(config.SONGS_CLEAN_CSV, encoding="utf-8", keep_default_na=False)
    result = repertoire_check.check_songs(songs, repertoire, threshold=threshold)

    metadata = pd.read_csv(config.SONGS_METADATA_CSV, encoding="utf-8", keep_default_na=False)[["line_no", "track_id"]]
    result = result.merge(metadata, left_on="matched_line_no", right_on="line_no", how="left").drop(columns=["line_no"])

    if out_csv:
        result.to_csv(out_csv, index=False, encoding="utf-8")

    n_in = int(result["in_repertoire"].sum())
    print(f"[preferences check] {n_in}/{len(result)} songs found in the repertoire" + (f" -> {out_csv}" if out_csv else ""))
    return result


def add(source: str, playlist_id: str | None = None) -> str:
    """Add confirmed track(s) - comma-separated track_ids, or a `check` output CSV - to the screen playlist."""
    playlist_id = _screen_playlist_id(playlist_id)

    path = Path(source)
    if path.exists():
        df = pd.read_csv(path, keep_default_na=False)
        if "in_repertoire" in df.columns:
            df = df[df["in_repertoire"].astype(str).str.lower() == "true"]
        track_ids = [t for t in df.get("track_id", pd.Series(dtype=str)).tolist() if t]
    else:
        track_ids = [t.strip() for t in source.split(",") if t.strip()]

    if not track_ids:
        raise ValueError("No track_ids to add.")

    sp = spotify_api.get_client()
    playlist_creation.add_in_batches(sp, playlist_id, track_ids)

    playlist = sp.playlist(playlist_id, fields="external_urls,name")
    url = playlist["external_urls"]["spotify"]
    print(f"[preferences add] added {len(track_ids)} tracks to '{playlist['name']}' -> {url}")
    return url


def _recover_catalog_duplicates(sp, df: pd.DataFrame, metadata: pd.DataFrame, threshold: float = 80) -> int:
    """Mutates df in place: for currently-unmatched rows, check if Spotify has
    the same recording (same ISRC) under a different track_id than the
    repertoire's stored match - a real Spotify catalog quirk (seen with e.g.
    "Carinito"/Los Hijos del Sol having two separate track entries).

    Scoped deliberately: only fetches ISRC for unmatched screen tracks plus
    their single best fuzzy song/artist candidate in the repertoire (reusing
    repertoire_check._score), not the whole ~1158-track repertoire - Spotify's
    batch /v1/tracks endpoint is blocked for this app, so ISRC lookups are
    one API call each and need to stay small.
    """
    unmatched_idx = df.index[df["line_no"].isna()]
    if not len(unmatched_idx):
        return 0

    candidates: dict[str, str] = {}  # screen track_id -> best-guess repertoire track_id
    for i in unmatched_idx:
        name, artist = df.at[i, "name"], df.at[i, "artist"]
        best_score, best_tid = -1.0, None
        for cand in metadata.itertuples(index=False):
            s = repertoire_check._score(name, artist, cand.song_clean, cand.artist_corrected)
            if s > best_score:
                best_score, best_tid = s, cand.track_id
        if best_score >= threshold:
            candidates[df.at[i, "track_id"]] = best_tid

    if not candidates:
        return 0

    isrcs = spotify_api.fetch_isrcs(sp, list(candidates.keys()) + list(candidates.values()))
    line_no_by_id = metadata.drop_duplicates(subset="track_id").set_index("track_id")["line_no"]

    recovered = 0
    for i in unmatched_idx:
        screen_tid = df.at[i, "track_id"]
        cand_tid = candidates.get(screen_tid)
        if cand_tid and isrcs.get(screen_tid) and isrcs.get(screen_tid) == isrcs.get(cand_tid):
            df.at[i, "line_no"] = line_no_by_id.at[cand_tid]
            recovered += 1
    return recovered


def report(playlist_id: str | None = None, out_csv=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch the screen playlist live, join to songs_final.csv by track_id, and
    fetch Last.fm genres for anything outside the pipeline.

    Returns (df, unmatched):
      df        every screen-playlist track, with repertoire columns
                (line_no, genre, subgenre, year, ...) where matched.
                liked=True for every row - playlist membership is the signal.
      unmatched the subset of df not found in the repertoire, with `genre`
                filled in from a live Last.fm lookup where found.
    """
    playlist_id = _screen_playlist_id(playlist_id)
    sp = spotify_api.get_client()
    screen = playlist_diff.get_playlist_tracks(sp, playlist_id)

    metadata = pd.read_csv(config.SONGS_METADATA_CSV, encoding="utf-8", keep_default_na=False)[
        ["track_id", "line_no", "song_clean", "artist_corrected"]
    ]
    metadata = metadata[metadata["track_id"] != ""]
    final = pd.read_csv(config.SONGS_FINAL_CSV).drop(columns=["artist", "song"])

    df = screen.merge(metadata[["track_id", "line_no"]], on="track_id", how="left").merge(final, on="line_no", how="left")

    recovered = _recover_catalog_duplicates(sp, df, metadata)
    if recovered:
        df = df.drop(columns=[c for c in final.columns if c != "line_no"]).merge(final, on="line_no", how="left")

    df["liked"] = True

    unmatched = df[df["line_no"].isna()][["name", "artist"]].copy()
    tags_by_artist = lastfm_api.fetch_artist_tags(unmatched["artist"].tolist())
    unmatched["genre"] = unmatched["artist"].map(
        lambda a: genre_analysis._first_canonical(tags_by_artist.get(a, []))
    )

    matched = df[df["line_no"].notna()]
    n_pipeline = matched["genre"].notna().sum()
    n_lastfm = unmatched["genre"].notna().sum()
    print(f"[preferences report] {len(screen)} tracks in the screen playlist")
    print(
        f"[preferences report] {len(matched)}/{len(df)} matched to the repertoire by track_id"
        + (f" ({recovered} more recovered via ISRC catalog-duplicate check)" if recovered else "")
    )
    print(f"[preferences report] {n_pipeline}/{len(matched)} matched songs have a genre from the pipeline")
    print(f"[preferences report] {n_lastfm}/{len(unmatched)} unmatched songs got a genre from Last.fm directly")

    if out_csv:
        df.to_csv(out_csv, index=False, encoding="utf-8")
        print(f"[preferences report] wrote {len(df)} rows -> {out_csv}")

    return df, unmatched


def label(playlist_id: str | None = None) -> None:
    """Export/reload the two missing-genre worklists for the screen playlist."""
    df, unmatched = report(playlist_id)
    matched = df[df["line_no"].notna()]

    matched_missing = matched[matched["genre"].isna()][["line_no", "name", "artist"]]
    matched_missing.to_csv(MATCHED_MISSING_CSV, index=False)
    print(
        f"[preferences label] {len(matched_missing)} matched songs still missing a genre "
        f"-> fix via genre_overrides.json, see {MATCHED_MISSING_CSV}"
    )

    still_missing = unmatched[unmatched["genre"].isna()][["name", "artist"]].copy()
    if UNMATCHED_FILL_CSV.exists():
        filled = pd.read_csv(UNMATCHED_FILL_CSV, keep_default_na=False)
        filled = filled[filled["genre"] != ""].drop_duplicates(subset=["name", "artist"])
        # left-merge on the deduped fill list preserves unmatched's row order/count 1:1,
        # so this Series can be safely re-indexed onto unmatched before filling nulls.
        merged_genre = unmatched.merge(filled, on=["name", "artist"], how="left", suffixes=("", "_filled"))[
            "genre_filled"
        ]
        unmatched["genre"] = unmatched["genre"].fillna(pd.Series(merged_genre.values, index=unmatched.index))
        still_missing = unmatched[unmatched["genre"].isna()][["name", "artist"]].copy()
        print(f"[preferences label] reloaded {len(filled)} hand-filled genres from {UNMATCHED_FILL_CSV}")

    still_missing["genre"] = ""  # fill this column by hand, save, re-run
    still_missing.to_csv(UNMATCHED_FILL_CSV, index=False)
    print(
        f"[preferences label] {len(still_missing)} unmatched songs still need a genre "
        f"-> fill in {UNMATCHED_FILL_CSV}, save, re-run"
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="check a song or song list against the repertoire")
    p_check.add_argument("source", help="a 'Song - Artist' string, or path to a list file")
    p_check.add_argument("--threshold", type=float, default=80)
    p_check.add_argument("--out", default=None)

    p_add = sub.add_parser("add", help="add confirmed track(s) to the screen playlist")
    p_add.add_argument("source", help="comma-separated track_ids, or a `check` output CSV")
    p_add.add_argument("--playlist", default=None, help="defaults to SCREEN_PLAYLIST_ID in .env")

    p_report = sub.add_parser("report", help="report the screen playlist's genre/year coverage")
    p_report.add_argument("--playlist", default=None, help="defaults to SCREEN_PLAYLIST_ID in .env")
    p_report.add_argument("--out", default=None, help="write the full joined table to this CSV")

    p_label = sub.add_parser("label", help="export/reload missing-genre lists for the screen playlist")
    p_label.add_argument("--playlist", default=None, help="defaults to SCREEN_PLAYLIST_ID in .env")

    args = parser.parse_args()

    if args.command == "check":
        result = check(args.source, threshold=args.threshold, out_csv=args.out)
        pd.set_option("display.max_rows", None, "display.width", None)
        print(result)
    elif args.command == "add":
        add(args.source, playlist_id=args.playlist)
    elif args.command == "report":
        report(args.playlist, out_csv=args.out)
    elif args.command == "label":
        label(args.playlist)
