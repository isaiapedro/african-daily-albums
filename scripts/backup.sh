#!/bin/sh
set -eu

: "${BACKUP_DIR:?Set BACKUP_DIR to an encrypted, access-controlled host directory}"
: "${BACKUP_RETENTION_DAYS:=14}"

umask 077
mkdir -p "$BACKUP_DIR"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
target="$BACKUP_DIR/african-album-journey-$stamp.sql.gz"

docker compose exec -T app python -c 'import sqlite3; connection = sqlite3.connect("/data/african_album_journey.db"); print("\n".join(connection.iterdump()))' | gzip -9 > "$target"
find "$BACKUP_DIR" -type f -name 'african-album-journey-*.sql.gz' -mtime +"$BACKUP_RETENTION_DAYS" -delete
printf '%s\n' "Created $target"
