#!/bin/bash
set -e

echo "[entrypoint] waiting for postgres at ${POSTGRES_HOST}:${POSTGRES_PORT}..."
until nc -z "${POSTGRES_HOST}" "${POSTGRES_PORT}"; do
  sleep 1
done
echo "[entrypoint] postgres is up"

echo "[entrypoint] waiting for redis..."
until nc -z redis 6379; do
  sleep 1
done
echo "[entrypoint] redis is up"

# Only the main portal container should run migrations + collectstatic + createsuperuser
# Celery workers skip these (env SKIP_DJANGO_BOOTSTRAP=1)
if [ "${SKIP_DJANGO_BOOTSTRAP:-0}" != "1" ] && [[ "$1" == "gunicorn" || "$1" == "python" || -z "$1" ]]; then
  echo "[entrypoint] running migrations..."
  python manage.py migrate --noinput

  echo "[entrypoint] collecting static files..."
  python manage.py collectstatic --noinput || true

  echo "[entrypoint] ensuring admin user exists..."
  python manage.py shell <<'PYCODE' || true
import os
from django.contrib.auth import get_user_model
U = get_user_model()
username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "admin")
email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "admin@example.com")
password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "admin")
if not U.objects.filter(username=username).exists():
    U.objects.create_superuser(username=username, email=email, password=password)
    print(f"created superuser {username}")
else:
    print(f"superuser {username} already exists")
PYCODE
fi

echo "[entrypoint] starting: $@"
exec "$@"
