#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required but was not found in PATH." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker is installed, but the Docker daemon is not running." >&2
  exit 1
fi

if [ ! -f ".env" ]; then
  cp ".env.example" ".env"
  echo "Created .env from .env.example."
fi

set -a
# shellcheck disable=SC1091
source ".env"
set +a

WEB_PORT="${WEB_PORT:-8000}"

if [[ ! "$WEB_PORT" =~ ^[0-9]+$ ]] || [ "$WEB_PORT" -lt 1 ] || [ "$WEB_PORT" -gt 65535 ]; then
  echo "WEB_PORT must be a TCP port between 1 and 65535: $WEB_PORT" >&2
  exit 1
fi

stop_containers_on_port() {
  local container_ids

  container_ids="$(
    docker ps --filter "publish=${WEB_PORT}" --format "{{.ID}}" | sort -u
  )"

  if [ -z "$container_ids" ]; then
    return 0
  fi

  echo "Stopping Docker container(s) already publishing WEB_PORT=${WEB_PORT}:"
  docker ps --filter "publish=${WEB_PORT}" --format "  {{.Names}} ({{.ID}})"
  docker stop $container_ids >/dev/null
}

stop_host_processes_on_port() {
  if ! command -v lsof >/dev/null 2>&1; then
    echo "lsof was not found; cannot inspect host processes using WEB_PORT=${WEB_PORT}." >&2
    return 0
  fi

  local pids
  pids="$(
    lsof -nP -iTCP:"${WEB_PORT}" -sTCP:LISTEN -t 2>/dev/null | sort -u || true
  )"

  if [ -z "$pids" ]; then
    return 0
  fi

  echo "Stopping host process(es) already listening on WEB_PORT=${WEB_PORT}:"
  lsof -nP -iTCP:"${WEB_PORT}" -sTCP:LISTEN || true

  kill $pids 2>/dev/null || true
  sleep 2

  local remaining_pids
  remaining_pids="$(
    lsof -nP -iTCP:"${WEB_PORT}" -sTCP:LISTEN -t 2>/dev/null | sort -u || true
  )"

  if [ -n "$remaining_pids" ]; then
    echo "Force stopping process(es) still listening on WEB_PORT=${WEB_PORT}."
    kill -9 $remaining_pids 2>/dev/null || true
  fi
}

stop_containers_on_port
stop_host_processes_on_port

docker compose --env-file ".env" up -d --build --force-recreate judge-web

echo "Web UI is available at http://127.0.0.1:${WEB_PORT}"
