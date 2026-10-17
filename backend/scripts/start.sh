#!/bin/sh
# Production entrypoint: migrate, seed demo data on a fresh database, then serve.
# Free hosts (e.g. Hugging Face Spaces) have ephemeral disks, so every cold start is a fresh database.
set -e
cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-.}"
mkdir -p storage/hr-policies storage/profile-photos storage/employee-documents storage/ai

alembic -c alembic.ini upgrade head
if python scripts/db_is_empty.py; then
  echo "Empty database: seeding demo data"
  python scripts/seed.py
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
