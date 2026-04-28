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

output_dir="database/dumps"
output_file="${output_dir}/dump_respostas.sql"

mkdir -p "$output_dir"

docker exec \
  -e PGPASSWORD="$POSTGRES_PASSWORD" \
  "$POSTGRES_CONTAINER_NAME" \
  pg_dump \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    --data-only \
    --no-owner \
    --no-privileges \
    --table=public.modelos \
    --table=public.respostas_atividade_1 > "$output_file"

echo "Responses dump written to $output_file"
