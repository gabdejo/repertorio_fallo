// Page configuration. Everything here is a public identifier (PKCE needs no secret).
window.CONFIG = {
  // Spotify app client id (same as SPOTIPY_CLIENT_ID in .env).
  clientId: "0d6129299fe347eebe775e9b111e270b",

  // Drop the two NEW playlist ids (or full open.spotify.com URLs) here.
  // Create both empty, by hand, in Spotify first.
  finalPlaylistId: "https://open.spotify.com/playlist/3NOPz8sOXNphAIJ1g7cmW6?si=WthzFAZaRvCTAq82ZR-ScA",      // songs you choose
  descartesPlaylistId: "https://open.spotify.com/playlist/1ouZ9UXE8gJVovx9bXwu5J?si=AdfZnrPfSnWOPH2_FYjZ-w",  // songs you reject

  // Read-only playlists. The page refuses to start if one of them is a target,
  // and refuses any non-GET request that names one. The screen playlist lives here.
  protectedPlaylistIds: ["3hrZ99XBmRzUHfYibyz6BX"],

  // Default maximum per genre. Editable in the page ("Cupos"); edits are saved in the
  // Final playlist's description as JSON so phone and PC see the same numbers.
  quotas: {
    "Salsa": 32, "Latin Pop": 21, "Merengue": 15, "Reggaetón": 11, "Cumbia": 7,
    "Pop": 5, "Rock": 4, "Tropical": 2, "Reparto": 1, "Electronic": 1,
    "House": 1, "Banda": 1, "Reggae": 1
  }
};
