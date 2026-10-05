#!/usr/bin/env bash
# Restore a dump made by deploy/backup.sh into the running stack's database.
#
#   ./restore.sh backups/botforge-20260101T030000Z.dump.gz --yes-overwrite [--database NAME]
#
# Without --database it restores into POSTGRES_DB and REPLACES its contents (pg_restore --clean).
# Stop the backend first so nothing writes during the restore:  docker compose stop backend
# then start it again afterwards:                              docker compose start backend
# With --database NAME the dump goes into that database (created if missing), e.g. a scratch copy to
# inspect, and the live database is not touched.
set -euo pipefail

usage() {
    echo "usage: $0 <dump.gz> --yes-overwrite [--database NAME]" >&2
    exit 2
}

DUMP=""
CONFIRM=0
TARGET=""
while [ $# -gt 0 ]; do
    case "$1" in
        --yes-overwrite) CONFIRM=1 ;;
        --database) shift; [ $# -gt 0 ] || usage; TARGET="$1" ;;
        -h | --help) usage ;;
        -*) usage ;;
        *) [ -z "$DUMP" ] || usage; DUMP="$1" ;;
    esac
    shift
done
[ -n "$DUMP" ] || usage
[ -f "$DUMP" ] || { echo "no such file: $DUMP" >&2; exit 1; }
[ "$CONFIRM" -eq 1 ] || { echo "refusing to restore without --yes-overwrite" >&2; exit 2; }
case "$TARGET" in
    *[!A-Za-z0-9_]*) echo "--database may contain only letters, digits and underscores" >&2; exit 2 ;;
esac

DUMP="$(cd "$(dirname "$DUMP")" && pwd)/$(basename "$DUMP")"
gzip -t "$DUMP"
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ -n "$TARGET" ]; then
    # Create the scratch database if it does not exist yet (an existing one is reused).
    docker compose exec -T db sh -c 'createdb -U "$POSTGRES_USER" "$1" 2>/dev/null || true' sh "$TARGET"
    gzip -dc "$DUMP" | docker compose exec -T db sh -c \
        'pg_restore -U "$POSTGRES_USER" -d "$1" --no-owner --exit-on-error' sh "$TARGET"
else
    gzip -dc "$DUMP" | docker compose exec -T db sh -c \
        'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --exit-on-error'
fi
echo "restore finished"
