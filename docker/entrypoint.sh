#!/usr/bin/env sh
# Container entrypoint. Dispatches on the first argument.
#   api     -> FastAPI (uvicorn)
#   bot     -> Telegram bot (long polling / webhook)
#   worker  -> background job worker
#   migrate -> run alembic upgrade head and exit
set -eu

ROLE="${1:-api}"

case "$ROLE" in
  migrate)
    exec alembic upgrade head
    ;;
  api)
    # Apply migrations opportunistically in single-node deployments; in a
    # multi-node cluster run the dedicated `migrate` service first instead.
    alembic upgrade head || echo "WARN: migrations skipped/failed"
    exec uvicorn apps.api.main:app --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-8000}"
    ;;
  bot)
    exec python -m apps.bot
    ;;
  worker)
    exec python -m workers
    ;;
  *)
    echo "unknown role: $ROLE" >&2
    exit 64
    ;;
esac
