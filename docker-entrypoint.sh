#!/bin/sh
set -e

# ── Wait for PostgreSQL ───────────────────────────────────────────────────────
echo "Waiting for PostgreSQL..."
until uv run python -c "
import os, psycopg2
psycopg2.connect(
    dbname=os.environ.get('DATABASE_NAME','hackathon_db'),
    host=os.environ.get('DATABASE_HOST','db'),
    port=int(os.environ.get('DATABASE_PORT',5432)),
    user=os.environ.get('DATABASE_USER','postgres'),
    password=os.environ.get('DATABASE_PASSWORD','postgres'),
)
" 2>/dev/null; do
  echo "  postgres not ready, retrying in 1s..."
  sleep 1
done
echo "PostgreSQL is ready."

# ── Wait for Redis ────────────────────────────────────────────────────────────
echo "Waiting for Redis..."
until uv run python -c "
import os, redis
r = redis.Redis(
    host=os.environ.get('REDIS_HOST','redis'),
    port=int(os.environ.get('REDIS_PORT',6379)),
    socket_connect_timeout=2,
)
r.ping()
" 2>/dev/null; do
  echo "  redis not ready, retrying in 1s..."
  sleep 1
done
echo "Redis is ready."

# ── Seed (app1 only) ──────────────────────────────────────────────────────────
if [ "$SEED_DB" = "true" ]; then
  echo "Seeding database..."
  uv run python seed.py
  echo "Seeding done."
fi

# ── Start gunicorn ────────────────────────────────────────────────────────────
echo "Starting Flask with gunicorn..."
exec uv run gunicorn \
  --bind 0.0.0.0:5000 \
  --workers 4 \
  --worker-class gevent \
  --timeout 120 \
  --keep-alive 5 \
  --access-logfile - \
  "app:create_app()"
