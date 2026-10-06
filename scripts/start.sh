#!/bin/sh
# Entrypoint del contenedor de producción.
#
# Lee HOST/PORT/UVICORN_WORKERS del entorno (ISSUE-010) y delega en el
# comando recibido por CMD (uvicorn por defecto). `exec` garantiza que
# uvicorn sea PID 1 y reciba SIGTERM/SIGINT directamente (graceful
# shutdown bajo stress).
set -e

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
UVICORN_WORKERS="${UVICORN_WORKERS:-1}"

exec "$@" --host "$HOST" --port "$PORT" --workers "$UVICORN_WORKERS"
