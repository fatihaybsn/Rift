#!/bin/sh
set -e

echo "Running migrations..."
alembic upgrade head

exec "$@"