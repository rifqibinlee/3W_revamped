#!/bin/bash
set -e

echo "Waiting for PostgreSQL..."
while ! pg_isready -h "${POSTGRES_HOST:-postgres}" -p 5432 -U "${POSTGRES_USER:-threew}"; do
  sleep 1
done
echo "PostgreSQL ready."

echo "Running Alembic migrations..."
alembic upgrade head

echo "Booting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-2} --timeout-keep-alive 600
