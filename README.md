# 100 Discos Africanos

A separate local-first album journey built from OkayAfrica's reader-selected
list of 100 African albums. It keeps the daily reveal, stable journey URLs,
history, private ratings/reviews, catalogue search, inactivity freeze, backup,
and restore behavior of the Brazilian album app while using an independent
database, container project, identity, palette, and loopback port.

## Run

```bash
cp .env.example .env
docker compose up --build -d --wait
```

Open `http://127.0.0.1:5175`. The Brazilian application remains independently
available on its registered port `5174`.

For local development:

```bash
cd api
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
ALBUM_JOURNEY_DB=/tmp/african-album-journey.db .venv/bin/uvicorn app.main:app --reload --port 5175
```

## Catalogue and privacy

The release contains 100 normalized factual entries—artist, album title,
article position, and the source's country label—from [OkayAfrica's reader
list](https://www.okayafrica.com/the-100-best-african-albums-according-to-our-readers/1404354).
It does not copy article blurbs, images, embeds, or page markup. Position follows
the article's display order and is not presented as a best-to-worst ranking.

The running app never contacts OkayAfrica or another catalogue provider.
Journey names, assignments, ratings, and reviews stay in the app's own local
SQLite volume and are never shared with the Brazilian application.

Album covers are optional local release assets. `python3
scripts/import_cover_art.py` performs the explicit, rate-limited MusicBrainz
and Cover Art Archive preparation pass. The running app serves matched images
from `/static/covers/` and keeps the typographic fallback for unmatched albums;
it never asks the browser to load a third-party image.

Use `python3 scripts/import_cover_art.py --upgrade-500` to refresh the matched
local thumbnails at the same 500px source size used by the Brazilian list.

The current local bundle contains 63 matched covers and 37 deliberate
fallbacks. The cover directory is local release material and remains excluded
from remote publication until artwork rights are reviewed.

`python3 scripts/enrich_release_years.py` is a separate explicit MusicBrainz
preparation pass for release years. It accepts only a confident release-group
match and a parseable first release date, keeps an application-local trace, and
leaves uncertain years blank. The running app never performs this lookup.
The current local seed has 69 verified years and 31 intentional blanks.

`BACKUP_DIR=/secure/path make backup` creates a private SQL snapshot. Restore
is destructive and requires `BACKUP_FILE=/path/file.sql.gz make restore`.
