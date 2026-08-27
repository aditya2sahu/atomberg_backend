FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render scans port 10000 unless PORT says otherwise.
EXPOSE 10000

# PORT is injected by Render; unset locally, so default to the port Render scans.
# The six factory tables are created by running schema.sql against the database by
# hand, so AtombergApp's migration is faked here — Django only records that it ran,
# and never executes any DDL of its own. Django's own tables (auth, sessions,
# admin) still migrate for real.
CMD python manage.py makemigrations --noinput && \
    python manage.py migrate --fake AtombergApp --noinput && \
    python manage.py migrate --noinput && \
    python manage.py collectstatic --noinput && \
    gunicorn Atomberg.wsgi:application --bind 0.0.0.0:${PORT:-10000} --workers 3 --timeout 60
