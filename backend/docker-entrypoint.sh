#!/bin/sh
# Optionally apply database migrations, then exec the server. In multi-replica deployments run migrations as a
# one-off task instead (RUN_MIGRATIONS=false on the service) - see docs/deployment.md.
set -eu
if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  echo "applying database migrations"
  alembic upgrade head
fi
exec "$@"
