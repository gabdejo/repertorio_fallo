"""Stage 6 - Preference learning from manual ratings. (SCAFFOLD)

After the user fills the ``liked`` column (1=liked, 0=disliked) in the final
dataset, aggregate ratings by genre / artist / decade / BPM / energy and build
a balanced playlist around the top 3 genres while preserving diversity.

Run:  python -m src.preferences
"""
from __future__ import annotations


def run() -> None:
    raise NotImplementedError(
        "Stage 6 scaffold: groupby genre/artist/decade -> mean('liked'), surface "
        "favorites, then sample a diverse playlist weighted toward the top 3 "
        "genres. Visuals belong in notebooks/exploration.ipynb."
    )


if __name__ == "__main__":
    run()
