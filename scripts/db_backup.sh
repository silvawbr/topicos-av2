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
timestamp="$(date +%Y%m%d_%H%M%S)"
backup_dir="outputs/backup"
backup_file="${backup_dir}/atividade_2_${timestamp}.sql"

mkdir -p "$backup_dir"

docker exec \
  -e PGPASSWORD="$POSTGRES_PASSWORD" \
  "$POSTGRES_CONTAINER_NAME" \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" > "$backup_file"

echo "Backup written to $backup_file"
