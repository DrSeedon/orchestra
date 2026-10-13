# Sound layer attribution

The `sfx.py`, `mix.py`, `qa.py`, and `library.json` files are from
[Bodila51/opus-sound-layer](https://github.com/Bodila51/opus-sound-layer),
commit `52ac266a24b7dfd3cd06a28c34d5af360a8d7586`, licensed under MIT.
Copyright (c) 2026 Bodila51. See [LICENSE](LICENSE).
Local changes: kit and candidate defaults point into the user's Orchestra SFX data directory;
the mixer expands its default kit path there; Openverse search retains every result field from all
returned CC0 Freesound pages, while `--n` limits only which recordings are downloaded for review.

The downloadable sound recordings are CC0 and are stored outside this repository
in `~/.local/share/orchestra-sfx/`; see that directory's `CREDITS.md` for sources.
