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

required_tables=(
  datasets
  modelos
  perguntas
  respostas_atividade_1
  avaliacoes_juiz
)

for table_name in "${required_tables[@]}"; do
  exists="$(
    docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$POSTGRES_CONTAINER_NAME" \
      psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
      "SELECT to_regclass('public.${table_name}') IS NOT NULL;"
  )"

  if [ "$exists" != "t" ]; then
    echo "Missing required table: public.${table_name}" >&2
    exit 1
  fi

  row_count="$(
    docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$POSTGRES_CONTAINER_NAME" \
      psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
      "SELECT count(*) FROM public.${table_name};"
  )"
  echo "public.${table_name}: ${row_count} row(s)"
done

echo "Restore validation passed."
