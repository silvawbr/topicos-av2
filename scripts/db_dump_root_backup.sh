#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f ".env" ]; then
  echo ".env was not found. Run make db-up first." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source ".env"
set +a

POSTGRES_CONTAINER_NAME="${POSTGRES_CONTAINER_NAME:-topicos-av2-postgres}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-app_dev}"

if ! docker ps --format '{{.Names}}' | grep -Fx "$POSTGRES_CONTAINER_NAME" >/dev/null; then
  echo "PostgreSQL container is not running: $POSTGRES_CONTAINER_NAME" >&2
  exit 1
fi

output_file="backup_atividade_2.sql"

docker exec \
  -e PGPASSWORD="$POSTGRES_PASSWORD" \
  "$POSTGRES_CONTAINER_NAME" \
  pg_dump \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    --no-owner \
    --no-privileges > "$output_file"

echo "Root backup written to $output_file"
