#!/usr/bin/env bash
# Wrapper for the LOCAL REHEARSAL stack (never for the VPS):
#   ./local.sh up|down|logs|psql|backup|restore [args]
#   up       build and start (docker compose up -d --build)
#   down     stop and remove containers; add -v to also delete the database volume
#   logs     follow logs (optionally name services: ./local.sh logs backend)
#   psql     open psql in the db container (extra args go to psql)
#   backup   run backup.sh against this stack
#   restore  run restore.sh against this stack (arguments as for restore.sh)
# Any other command is passed to `docker compose` with the local files and env file.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
[ -f .env.local ] || { echo "missing deploy/.env.local: cp .env.local.example .env.local and fill it in" >&2; exit 1; }

# Docker Compose reads these, so backup.sh and restore.sh (plain `docker compose`) see the local stack too.
export COMPOSE_FILE=docker-compose.yml:docker-compose.local.yml
export COMPOSE_ENV_FILES=.env.local

cmd="${1:-}"
[ $# -gt 0 ] && shift
case "$cmd" in
    up) docker compose up -d --build "$@" ;;
    down) docker compose down "$@" ;;
    logs) docker compose logs -f "$@" ;;
    psql) docker compose exec db sh -c 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh "$@" ;;
    backup) ./backup.sh "$@" ;;
    restore) ./restore.sh "$@" ;;
    ps | build | exec | stop | start | restart | config) docker compose "$cmd" "$@" ;;
    *) echo "usage: $0 up|down|logs|psql|backup|restore|ps|exec ..." >&2; exit 2 ;;
esac
