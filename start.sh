#!/bin/sh
set -e

echo "Waiting for PostgreSQL..."
until python -c "
import socket, sys
try:
    s = socket.create_connection(('localhost', 5432), timeout=2)
    s.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
"; do
  echo "  postgres not ready, retrying in 2s..."
  sleep 2
done

echo "Running migrations..."
python manage.py migrate --noinput

echo "Starting gunicorn..."
exec gunicorn dormwatch.wsgi:application \
  -w 4 \
  --bind 0.0.0.0:8000 \
  --worker-tmp-dir /dev/shm \
  --access-logfile -
