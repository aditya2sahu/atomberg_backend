#!/usr/bin/env bash
# Self-contained demo: Postgres and the API in one container.
set -e

# The official Postgres entrypoint handles initdb and runs anything in
# /docker-entrypoint-initdb.d — which is where schema.sql lives.
docker-entrypoint.sh postgres &

until pg_isready -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q; do sleep 1; done

python3 manage.py makemigrations --noinput
python3 manage.py migrate --fake AtombergApp --noinput
python3 manage.py migrate --noinput
python3 manage.py load_csv data --if-empty
python3 manage.py collectstatic --noinput

exec gunicorn Atomberg.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers 3 --timeout 60
