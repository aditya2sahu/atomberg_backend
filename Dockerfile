FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# PORT is injected by Render; locally docker-compose leaves it unset, so default it.
# migrate builds the schema from schema.sql; load_csv seeds only if the DB is empty,
# so a restart doesn't re-import 80k rows.
CMD python manage.py migrate --noinput && \
    python manage.py load_csv data --if-empty && \
    python manage.py collectstatic --noinput && \
    gunicorn Atomberg.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 3 --timeout 60
