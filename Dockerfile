FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render scans port 10000 unless PORT says otherwise.
EXPOSE 10000

# PORT is injected by Render; unset locally, so default to the port Render scans.
#
# A deploy sets itself up with no manual steps:
#   makemigrations  records what the models look like, so Django can track state
#   migrate --fake  marks AtombergApp applied without issuing any DDL
#   migrate         Django's own tables (auth, sessions, admin) for real
#   ensure_schema   creates the six factory tables from schema.sql if missing
#   load_csv        seeds only when empty, so a restart doesn't re-import 80k rows
CMD python manage.py makemigrations --noinput && \
    python manage.py migrate --fake AtombergApp --noinput && \
    python manage.py migrate --noinput && \
    python manage.py ensure_schema && \
    python manage.py load_csv data --if-empty && \
    python manage.py collectstatic --noinput && \
    gunicorn Atomberg.wsgi:application --bind 0.0.0.0:${PORT:-10000} --workers 3 --timeout 60
