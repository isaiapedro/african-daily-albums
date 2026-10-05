#!/bin/sh
set -eu

: "${BACKUP_FILE:?Set BACKUP_FILE to a reviewed backup file}"
test -r "$BACKUP_FILE"

printf '%s\n' "Restore replaces the local journey database. Stop now with Ctrl-C if that is not intended." >&2
docker compose stop app
gzip -dc "$BACKUP_FILE" | docker compose run --rm -T --no-deps app python -c 'from pathlib import Path; import sqlite3, sys; [path.unlink(missing_ok=True) for path in (Path("/data/african_album_journey.db"), Path("/data/african_album_journey.db-wal"), Path("/data/african_album_journey.db-shm"))]; connection = sqlite3.connect("/data/african_album_journey.db"); connection.executescript(sys.stdin.read()); connection.close()'
printf '%s\n' "Restore complete. Run 'make up' to start the app."
