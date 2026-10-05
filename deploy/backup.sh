#!/usr/bin/env bash
# Dump the BotForge database to deploy/backups/botforge-<UTC timestamp>.dump.gz and keep the newest 14.
# The dump is pg_dump custom format (-Fc), then gzipped. Run from anywhere; exits non-zero on failure.
# Restore with deploy/restore.sh. Cron example: see the README ("Nightly backup").
set -euo pipefail

KEEP=14
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="$DEPLOY_DIR/backups"
cd "$DEPLOY_DIR"
mkdir -p "$BACKUP_DIR"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$BACKUP_DIR/botforge-$STAMP.dump.gz"
TMP="$OUT.partial"
trap 'rm -f "$TMP"' EXIT

# Credentials are read inside the container, so nothing secret appears on this command line.
docker compose exec -T db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' | gzip > "$TMP"

# pipefail already failed the script if pg_dump failed; also refuse an empty or corrupt archive.
gzip -t "$TMP"
[ -s "$TMP" ] || { echo "backup is empty" >&2; exit 1; }
mv "$TMP" "$OUT"
chmod 600 "$OUT"

# Keep the newest $KEEP dumps (names sort by timestamp).
# shellcheck disable=SC2012
ls -1 "$BACKUP_DIR"/botforge-*.dump.gz 2>/dev/null | sort -r | tail -n +"$((KEEP + 1))" | while IFS= read -r old; do
    rm -f -- "$old"
done

echo "backup written: $OUT ($(du -h "$OUT" | cut -f1))"
