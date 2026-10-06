#!/usr/bin/env bash
# Back up BotForge into deploy/backups/, as a pair sharing one UTC timestamp, and keep the newest 14:
#   botforge-<stamp>.dump.gz         the database: pg_dump custom format (-Fc), then gzipped
#   botforge-<stamp>.uploads.tar.gz  the `uploads` volume (spreadsheet files, UPLOAD_DIR)
# Run from anywhere; exits non-zero on failure. Restore with deploy/restore.sh. Cron example: see the
# README ("Nightly backup").
set -euo pipefail

KEEP=14
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="$DEPLOY_DIR/backups"
cd "$DEPLOY_DIR"
mkdir -p "$BACKUP_DIR"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$BACKUP_DIR/botforge-$STAMP.dump.gz"
UPLOADS_OUT="$BACKUP_DIR/botforge-$STAMP.uploads.tar.gz"
TMP="$OUT.partial"
UPLOADS_TMP="$UPLOADS_OUT.partial"
trap 'rm -f "$TMP" "$UPLOADS_TMP"' EXIT

# Credentials are read inside the container, so nothing secret appears on this command line.
docker compose exec -T db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' | gzip > "$TMP"

# pipefail already failed the script if pg_dump failed; also refuse an empty or corrupt archive.
gzip -t "$TMP"
[ -s "$TMP" ] || { echo "backup is empty" >&2; exit 1; }

# The uploads volume, read through the one-shot uploads-init service (it mounts the volume and its
# image has tar), so this works whether or not the backend is running. Read-only use: nothing changes.
docker compose run --rm --no-deps -T --entrypoint tar uploads-init -C /data/uploads -czf - . > "$UPLOADS_TMP"
gzip -t "$UPLOADS_TMP"

mv "$TMP" "$OUT"
mv "$UPLOADS_TMP" "$UPLOADS_OUT"
chmod 600 "$OUT" "$UPLOADS_OUT"

# Keep the newest $KEEP of each kind (names sort by timestamp).
for pattern in 'botforge-*.dump.gz' 'botforge-*.uploads.tar.gz'; do
    # shellcheck disable=SC2012,SC2086
    ls -1 "$BACKUP_DIR"/$pattern 2>/dev/null | sort -r | tail -n +"$((KEEP + 1))" | while IFS= read -r old; do
        rm -f -- "$old"
    done
done

echo "backup written: $OUT ($(du -h "$OUT" | cut -f1))"
echo "uploads written: $UPLOADS_OUT ($(du -h "$UPLOADS_OUT" | cut -f1))"
