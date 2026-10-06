#!/usr/bin/env bash
# Restore a backup made by deploy/backup.sh into the running stack.
#
#   ./restore.sh backups/botforge-20260101T030000Z.dump.gz --yes-overwrite [--database NAME]
#
# Without --database it restores into POSTGRES_DB and REPLACES its contents (pg_restore --clean), and,
# when the matching botforge-<stamp>.uploads.tar.gz sits next to the dump, REPLACES the contents of the
# `uploads` volume with it too (an older backup without one leaves the volume untouched, with a warning).
# Stop the backend first so nothing writes during the restore:  docker compose stop backend
# then start it again afterwards:                              docker compose start backend
# With --database NAME the dump goes into that database (created if missing), e.g. a scratch copy to
# inspect, and the live database and the uploads volume are not touched.
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
UPLOADS=""
case "$DUMP" in
    *.dump.gz) UPLOADS="${DUMP%.dump.gz}.uploads.tar.gz" ;;
esac
if [ -z "$TARGET" ] && [ -n "$UPLOADS" ] && [ -f "$UPLOADS" ]; then
    gzip -t "$UPLOADS"  # check both archives before anything is overwritten
else
    UPLOADS=""
fi
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ -n "$TARGET" ]; then
    # Create the scratch database if it does not exist yet (an existing one is reused).
    docker compose exec -T db sh -c 'createdb -U "$POSTGRES_USER" "$1" 2>/dev/null || true' sh "$TARGET"
    gzip -dc "$DUMP" | docker compose exec -T db sh -c \
        'pg_restore -U "$POSTGRES_USER" -d "$1" --no-owner --exit-on-error' sh "$TARGET"
else
    gzip -dc "$DUMP" | docker compose exec -T db sh -c \
        'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --exit-on-error'
    if [ -n "$UPLOADS" ]; then
        # Through the one-shot uploads-init service (it mounts the volume, runs as root, has tar):
        # empty the volume, unpack, and hand the files back to the app user (uid 10001).
        docker compose run --rm --no-deps -T --entrypoint sh uploads-init -c \
            'find /data/uploads -mindepth 1 -delete && tar -C /data/uploads -xzf - && chown -R 10001:10001 /data/uploads' \
            < "$UPLOADS"
        echo "uploads restored from $UPLOADS"
    else
        echo "warning: no uploads archive next to the dump; the uploads volume was left as it is" >&2
    fi
fi
echo "restore finished"
