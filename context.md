# Project Context: Band Repertory Analysis and Spotify Playlist Curation Pipeline

## Objective

I have a PDF repertory/list from a band containing song names and artists (song-artist pairs). My goal is to transform this unstructured list into a clean music database that allows me to analyze the repertoire, understand its composition, and build a diverse Spotify playlist.

The final objective is:

1. Analyze the repertoire by artist, genre, subgenre, year, popularity, duration, BPM, and other musical attributes.
2. Identify which songs are broadly known/popular versus more niche songs.
3. Identify patterns in the repertoire (genre concentration, decades, artists, styles).
4. Create a Spotify playlist containing the songs so I can listen, review them, and manually rate which ones I like.
5. Use my ratings and the extracted attributes to eventually create a balanced playlist focused on my favorite 3 genres while maintaining diversity.

---

# Main Problems to Solve

## 1. Extracting data from PDF

The PDF contains a list of songs and artists, but the format may not be perfectly structured.

Example:

Raw PDF:

| Song               | Artist      |
| ------------------ | ----------- |
| Sweet Child O Mine | Guns        |
| Imagine            | John Lennon |

Need to convert it into a structured dataframe:

Columns:

* song_raw
* artist_raw

Preserve the original values for auditing.

---

## 2. Cleaning and normalizing names

The repertory may contain inconsistent names:

Examples:

* Artist is listed as the singer instead of the official band:

  * "Freddie Mercury - Don't Stop Me Now"
  * Correct artist: Queen

* Artists with renamed versions:

  * Old name vs current official name

* Different spellings:

  * "The Beatles"
  * "Beatles"

Need a normalization layer:

Columns:

* song_clean
* artist_clean
* artist_corrected

Maintain an alias/correction dictionary:

Example:

artist_aliases:

{
"Freddie Mercury": "Queen",
"Beatles": "The Beatles"
}

---

# 3. Matching songs with external music databases

Need to retrieve metadata automatically.

For each:

(song, artist)

find the corresponding official track.

Possible information:

## Basic metadata

* official artist
* album
* release year
* duration
* popularity
* track ID

## Audio characteristics

* BPM
* energy
* danceability
* acousticness
* valence
* loudness

The main matching challenge is entity resolution:
finding the correct song despite imperfect input names.

---

# 4. Genre and subgenre classification

Genres are usually artist-level, not song-level.

Example:

Metallica:

* heavy metal
* thrash metal
* hard rock

A practical approach:

Create artist-level genres first:

artist -> genres

Then manually refine exceptions when necessary.

Final dataset:

song | artist | year | genre | subgenre | bpm | duration | popularity

---

# 5. Creating a Spotify playlist automatically

After matching songs with Spotify:

Workflow:

PDF
↓
Clean dataframe
↓
Spotify search
↓
Track IDs
↓
Create playlist
↓
Listen and rate songs

Need to upload all matched songs into a Spotify playlist for review.

---

# 6. Personal preference learning

After listening, add a rating column:

Example:

liked:

1 = liked
0 = disliked

Then analyze:

* favorite genres
* favorite artists
* favorite decades
* BPM preferences
* energy preferences

Example:

genre performance:

genre | average rating

Rock | 0.82
Funk | 0.75
Jazz | 0.40

Use this information to generate a personalized but diverse playlist.

---

# Recommended Python Stack

## PDF extraction

Packages:

* pymupdf (`fitz`)

  * Extract text from PDFs
  * Good general PDF parser

* camelot

  * Useful if PDF contains tables

* tabula-py

  * Alternative table extraction

---

## Data manipulation

Main package:

* pandas

Use for:

* cleaning
* joins
* grouping
* analysis
* exporting CSV files

---

## Fuzzy matching / entity resolution

Packages:

* rapidfuzz

Use for:

* approximate song matching
* artist correction
* handling spelling differences

Example:

"guns n roses"

matching:

"Guns N' Roses"

---

## Spotify integration

Package:

* spotipy

Use for:

* searching tracks
* retrieving metadata
* creating playlists
* adding tracks

---

## Optional external music databases

Possible sources:

* Spotify API
* MusicBrainz
* Last.fm API
* AcousticBrainz (if available)

---

## Visualization

Packages:

* matplotlib
* seaborn
* plotly

Possible plots:

* genre distribution
* decade distribution
* BPM histogram
* popularity distribution
* artist concentration

---

# Recommended Project Architecture

Folder structure:

music_project/

```
data/
    raw/
        repertory.pdf

    processed/
        songs_clean.csv
        songs_metadata.csv

src/

    pdf_extraction.py

    cleaning.py

    spotify_api.py

    genre_analysis.py

    playlist_creation.py

notebooks/

    exploration.ipynb
```

---

# Expected Final Dataset

Example:

| song             | artist    | year | genre      | subgenre  | duration | bpm | popularity | liked |
| ---------------- | --------- | ---- | ---------- | --------- | -------- | --- | ---------- | ----- |
| Hotel California | Eagles    | 1976 | Rock       | Soft Rock | 391      | 147 | 87         | 1     |
| One More Time    | Daft Punk | 2000 | Electronic | House     | 320      | 123 | 85         | 0     |

This dataset should allow:

* exploratory analysis
* playlist generation
* discovering favorite genres
* finding hidden gems
* creating balanced playlists

---

# Development Approach

Start simple:

1. Extract PDF.
2. Create clean dataframe.
3. Manually correct problematic artists.
4. Match with Spotify.
5. Add metadata.
6. Create first playlist.
7. Listen and rate.
8. Improve recommendations based on preferences.

The key technical challenge is not the analysis itself, but accurately matching messy repertory entries with official music entities.
