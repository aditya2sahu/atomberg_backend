# Order to Output

Backend for the Atomberg factory take-home. Fourteen days of production data —
four machines, eight products, 68 orders, 80k finished units, 307 stoppages —
loaded into Postgres from CSV and served as a REST API built around what three
very different people need from it.

**Snapshot time is `2026-08-17 09:15`.** The data is a saved export, not a live
feed, so that timestamp stands in for "now" everywhere. It lives in exactly one
place, `AtombergApp/clock.py`.

> **Status:** database, loader and API are complete and tested. The React
> frontend is the remaining deliverable.

---

## Contents

- [Setup](#setup) — three ways to run it
- [Configuration](#configuration)
- [Loading the data](#loading-the-data)
- [Tests](#tests)
- [Schema](#schema)
- [API](#api)
- [Built for three people](#built-for-three-people)
- [What the data turned out to be](#what-the-data-turned-out-to-be)
- [Assumptions](#assumptions)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)
- [Cut, and what's next](#cut-and-whats-next)

---

## Setup

Pick whichever fits. All three end up with identical data: 4 machines, 8 SKUs,
68 orders, 307 downtime events, 80,333 unit events.

### 1. Docker Compose — recommended for development

```bash
git clone <repo> && cd Atomberg
docker compose up --build
```

That's the whole thing. First start takes about a minute.

```
http://localhost:8000/api/machines/
http://localhost:8000/api/floor/status/
http://localhost:8000/api/analytics/summary/?from=2026-08-03&to=2026-08-17
```

Three services:

| Service | What it does |
|---|---|
| `db` | Postgres 16. `schema.sql` is mounted into `/docker-entrypoint-initdb.d/`, which Postgres runs on first init — so the tables and indexes come from the SQL, never from Django |
| `seed` | runs the CSV loader once, prints what it loaded, exits |
| `api` | waits for the seed to succeed, then serves on port 8000 |

Data lives in a named volume, so restarting doesn't re-import — the loader
checks and prints `Data already loaded, skipping.`

```bash
docker compose down       # stop, keep the data
docker compose down -v    # stop and wipe, next start reloads from CSV
docker compose logs -f api
docker compose exec api python manage.py shell
```

### 2. One self-contained image — for handing someone a demo

Postgres, schema, data and API all inside a single container:

```bash
docker build -f Dockerfile.standalone -t atomberg .
docker run -p 8000:8000 atomberg
```

Give it ~40 seconds, then use the same URLs. The data lives inside the
container, so removing it throws the data away and the next run re-imports.

This exists for convenience. The production `Dockerfile` runs one process and
talks to a managed database, which is how it should be.

### 3. Local Python — for working on the code

Needs Python 3.10+ and a Postgres you can reach.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # then edit it with your database details
createdb atomberg

# same four steps the container runs on boot — see Migrations below
python manage.py makemigrations
python manage.py migrate --fake AtombergApp
python manage.py migrate
python manage.py ensure_schema        # creates the tables from schema.sql

python manage.py load_csv data
python manage.py runserver
```

`http://localhost:8000/api/machines/`

DRF's browsable API works in a browser, so you can click around without a
frontend.

---

## Configuration

Settings are read from environment variables first, then a `.env` file next to
`manage.py`, then the default in the code. `.env.example` lists everything.

| Variable | Default | Notes |
|---|---|---|
| `SECRET_KEY` | **none** | required — the app refuses to start without it |
| `DEBUG` | `False` | `True` locally |
| `DATABASE_URL` | empty | preferred. If empty, falls back to the five `DB_*` variables below |
| `DB_NAME` `DB_USER` `DB_PASSWORD` `DB_HOST` `DB_PORT` | **none** | only used when `DATABASE_URL` is empty |
| `ALLOWED_HOSTS` | `*` | comma-separated |
| `CORS_ALLOWED_ORIGINS` | `localhost:5173,localhost:3000` | comma-separated frontend origins |
| `CSRF_TRUSTED_ORIGINS` | empty | comma-separated |
| `PORT` | `10000` | port gunicorn binds to |

Two shapes for the database so local and hosted environments can differ without
a code change: your `.env` uses the separate `DB_*` values, Render hands over a
single `DATABASE_URL`.

With `DEBUG=False` the app turns on the HTTPS redirect, secure cookies and HSTS,
and trusts `X-Forwarded-Proto` from the platform's proxy. `/healthz` is exempt
from the redirect so health checks get a clean 200.

---

## Loading the data

The six CSVs live in `data/`. The loader inserts in foreign-key order inside a
single transaction, so a malformed row rolls the whole thing back instead of
leaving a half-loaded database.

```bash
python manage.py load_csv data              # load
python manage.py load_csv data --flush      # wipe first, then load
python manage.py load_csv data --if-empty   # no-op if data is already there
```

```
Machine: 4 rows
SKU: 8 rows
DowntimeReason: 10 rows
Order: 68 rows
DowntimeEvent: 307 rows
UnitEvent: 80333 rows  (200 duplicate rows skipped)
```

It uses `bulk_create` rather than Postgres `COPY` — 80k rows land in about seven
seconds and it stays database-agnostic for the test suite. `COPY` is the upgrade
path if this ever becomes millions of rows.

Data can also be pushed over HTTP; see `POST /api/bulk/{resource}/` below.

---

## Tests

```bash
python manage.py makemigrations AtombergApp   # first time on a fresh clone
python manage.py test AtombergApp             # 17 tests
```

Django builds the test database from migrations, and the migrations folder holds
only `__init__.py` in version control (see *Migrations* below) — so on a fresh
clone the migration has to be generated once before the suite can run. After that
`manage.py test` is enough.

Tests cover the loader,
derived progress, the stored-vs-actual status mismatch, server-side validation,
the floor board including stopped machines, cursor pagination, downtime maths
against the snapshot clock, duplicate serials, and bulk insert rollback.

---

## Schema

`schema.sql` is hand-written — the brief asks for the `CREATE TABLE` statements
rather than ORM output. Every table, index and constraint in this project comes
from that one file, in every environment.

Six tables: `machines`, `skus`, `orders`, `downtime_reasons`, `downtime_events`,
`unit_events`.

**Surrogate primary keys, unique business keys.** Every table has a `BIGSERIAL`
id; the codes from the CSVs (`machine_code`, `order_no`, `sku_code`,
`reason_code`) sit alongside as `UNIQUE NOT NULL`. A code can be corrected
without rewriting every child row. Tables that get referenced name their key
after themselves — `machines.machine_id`, `orders.order_id` — so a join column
reads the same on both sides. The two event tables keep a plain `id`, because
nothing points at them and their CSV columns already occupy `downtime_id` and
`event_id`. The API speaks codes throughout; integer ids never leave the
database.

**Progress is never stored.** An order has `qty_planned`; how many units are
finished is a `COUNT` of `unit_events`. Storing both would create two sources of
truth for one fact, and they would drift — the kind of bug that shows up months
later in a number someone is trusting. If counting ever gets slow, the fix is a
summary table maintained by a trigger, not a hand-updated column.

**Constraints at the database, not just the serializer.** Positive quantities,
positive rates, `ended_at >= started_at`, category and status value lists, and
`serial_no UNIQUE`. A bad row can't get in through the loader or a `psql`
session either.

### Migrations

Django never creates a table here. `schema.sql` does, and migrations exist only
so the ORM knows what shape the database is.

**Nothing in `AtombergApp/migrations/` is committed except `__init__.py`.** The
migration is generated at startup and immediately faked:

```
makemigrations              writes the file, so Django can track model state
migrate --fake AtombergApp  marks it applied without issuing any DDL
ensure_schema               runs schema.sql if the tables aren't there
```

`ensure_schema` is a management command that checks for the `machines` table and
applies `schema.sql` only when it's missing. Since `migrate` is faked, something
has to actually run the SQL — this is it. It's safe on every boot and prints
either `Applied schema.sql.` or `Tables already present.`

This also repairs a database whose migration record says "applied" while the
tables are gone, which is otherwise a silent failure: `migrate` skips the work
and the first request dies with `relation "machines" does not exist`.

Trade-off worth naming: `schema.sql` doesn't update itself when a model changes.
Keeping the two in step is manual. With one schema version that's fine; if the
schema started evolving, a dedicated migration tool would earn its place.

### Indexes, and what each one is for

| Index | Why it exists |
|---|---|
| `idx_unit_events_order` | every screen counts one order's units; without it that's a scan of 80k rows |
| `idx_unit_events_machine_time` | composite — the floor board filters machine *and* time range at once |
| `idx_unit_events_time` | analytics filters the whole table by date range |
| `idx_downtime_open` | **partial**, only rows where `ended_at IS NULL`. "Is this machine down right now" runs on every wall-board refresh; indexing only the handful of open rows keeps it tiny |
| `idx_downtime_machine_time` | downtime history per machine |
| `idx_downtime_reason` | the analytics breakdown |
| `idx_orders_status` `_due_date` `_priority` `_machine` | the planning team's four standing questions |

Nothing else is indexed. An index slows every write, so it should exist only
where a read needs it. `note` and `description` are deliberately unindexed.

---

## API

Base path `/api/`.

| Endpoint | Purpose |
|---|---|
| `GET /machines/` `/skus/` `/downtime-reasons/` | small reference lists |
| `GET /orders/` | order book — filters, search, pagination |
| `POST /orders/` | create, validated server-side |
| `GET,PATCH /orders/{order_no}/` | detail with derived progress and projected finish |
| `GET /floor/status/` | one small payload for the wall board |
| `GET /unit-events/` | 80k rows, cursor paginated |
| `GET /analytics/summary/?from=&to=` | everything the plant manager needs for a period |
| `POST /bulk/{resource}/` | insert a batch, all or nothing |
| `GET /healthz` | liveness check, exempt from the HTTPS redirect |

### Order book

```
GET /api/orders/?status=in_progress&machine=MC-01&priority=high
                &due_from=2026-08-01&due_to=2026-08-31&search=4111
                &ordering=due_date&page=2&page_size=50
```

### Order detail

```
GET /api/orders/PO-2026-4111/
```
```json
{
  "order_no": "PO-2026-4111",
  "sku_code": "AB-STD-0900-WH",
  "qty_planned": 1800,
  "due_date": "2026-08-18",
  "priority": "low",
  "status": "in_progress",
  "machine_code": "MC-01",
  "units_done": 90,
  "progress_pct": 5.0,
  "derived_status": "in_progress",
  "status_mismatch": false,
  "is_late": false,
  "projected_completion": "2026-08-17T23:30:00"
}
```

`units_done` is counted from `unit_events`. `derived_status` is what those events
say; `status_mismatch` flags where that disagrees with the stored `status`.
`projected_completion` is the remaining units divided by the machine's target
rate, from the snapshot time.

### Floor board

```
GET /api/floor/status/
```
```json
{
  "machine_code": "MC-01",
  "machine_name": "Assembly Machine 1",
  "current_order": "PO-2026-4111",
  "sku_code": "AB-STD-0900-WH",
  "qty_planned": 1800,
  "units_completed": 90,
  "progress_pct": 5.0,
  "units_last_hour": 90,
  "target_units_per_hour": 120.0,
  "pace": "stopped",
  "is_down": true,
  "downtime_reason": "Material shortage",
  "downtime_category": "unplanned",
  "down_since": "2026-08-17T09:07:00",
  "down_minutes": 8
}
```

Every machine appears, including one with no current order. `pace` is
`on_pace` / `behind` / `stopped` / `idle`, so colour can carry the meaning from
across a room. The reason is in plain words, never the code `DT-QAL`.

**This is a separate endpoint from `/orders/` on purpose.** The wall display
polls constantly and needs one small fixed-shape response; the order book is
built for browsing, with pagination and optional detail. One endpoint serving
both would make one of them worse.

### Analytics

```
GET /api/analytics/summary/?from=2026-08-10&to=2026-08-16
```
```json
{
  "total_output": 40911,
  "total_downtime_hours": 77.52,
  "planned_downtime_hours": 36.75,
  "unplanned_downtime_hours": 40.77,
  "downtime_by_reason": [
    {"reason_code": "DT-BRK", "description": "Scheduled break",
     "category": "planned", "hours": 13.65, "events": 28}
  ],
  "orders_completed": 39,
  "orders_on_time": 33,
  "orders_late": 6,
  "orders_overdue_open": 0,
  "on_time_pct": 84.6,
  "per_machine": [
    {"machine_code": "MC-01", "units_produced": 10342, "target_units": 20160.0,
     "utilization_pct": 51.3, "downtime_hours": 20.77, "availability_pct": 87.6}
  ]
}
```

`downtime_by_reason` is sorted biggest-first, so the answer to "what is costing
us the most" is the first element. Downtime is clipped to the window: a stoppage
that began before the range, or is still open, only counts for the part inside —
and never past the snapshot time.

### Unit events

```
GET /api/unit-events/?machine=MC-01&order=PO-2026-4111&page_size=100
```

**Cursor pagination**, because at 80k rows `LIMIT/OFFSET` for page 500 makes the
database count through the first 499 pages. A cursor stays fast at any depth. The
order list is 68 rows and doesn't have that problem, so it uses plain page
numbers — no point paying for complexity that isn't earning anything.

### Bulk insert

```
POST /api/bulk/machines/
[{"machine_code": "MC-05", "name": "Assembly Machine 5", "target_units_per_hour": 120}]

201 {"resource": "machines", "created": 1}
```

Resources: `machines`, `skus`, `downtime-reasons`, `orders`, `downtime-events`,
`unit-events`. Up to 5000 rows per request.

The whole list is validated before anything is written, and the insert runs in
one transaction — one bad row rejects the batch rather than leaving a partial
load. Errors are keyed by row index, so a caller sending thousands learns exactly
which one failed:

```json
400 {"errors": {"1": {"machine_code": ["machine with this machine code already exists."]}}}
```

### Validation

Rules live in DRF serializers, so they apply to `curl` exactly as they do to a
form — the brief calls this out, and a browser form can be bypassed by anyone
calling the API directly.

- quantity must be positive
- due date can't be in the past when creating
- SKU and machine must exist
- quantity can't be edited below the units already produced
- `ended_at` can't precede `started_at`
- duplicate codes and serials are rejected

**Polling, not websockets.** One wall display refreshing every 5–10 seconds is
fast enough for a factory floor. Websockets would solve a scale problem that
doesn't exist here.

---

## Built for three people

Three people, three situations, three different shapes of response. The backend
is what exists today, so each of these is the API surface that screen sits on —
the constraint drove the payload, not the other way round.

### Planning team — the order book

**Their situation:** at a desk, all day, in one screen. They are the only people
who *create and change* things, so they are also the only people who will ever
hit a rejection and need to know exactly which field is wrong.

**So:** `GET /orders/` filters and paginates on the server (`status`, `machine`,
`priority`, due-date range, text search, `ordering`) — 68 rows today, thousands
later, and fetching everything to filter in the browser stops holding up long
before that. `POST` and `PATCH` validate in DRF serializers and return errors
keyed per field, so a form can put the message next to the input that caused it
rather than showing a generic toast. `GET /orders/{order_no}/` carries
`units_done`, `progress_pct` and `projected_completion` so the detail view has
its progress bar without a second call.

### Floor supervisor — the wall board

**Their situation:** a 1920×1080 screen bolted to a wall. No mouse, no keyboard,
nobody operating it. It gets glanced at from several metres away, for a second,
by someone whose hands are full.

**So:** `GET /floor/status/` is one small fixed-shape payload — every machine,
every refresh, no pagination and no query parameters to get wrong. Each machine
carries a `pace` of `on_pace` / `behind` / `stopped` / `idle`, precomputed
server-side, so the display maps it straight to a colour and the meaning carries
from across the room without anything being read. `downtime_reason` is the plain
description, never the code `DT-QAL`, because a supervisor should not have to
decode it. Every machine appears even with no current order, so the board never
silently loses a card. It is a **separate endpoint from `/orders/` on purpose**:
the wall polls every 5–10 seconds and wants one tiny response, the order book
wants browsing and detail — one endpoint serving both would make one of them
worse.

### Plant manager — analytics

**Their situation:** thinking in weeks, not minutes, usually on a tablet, often
mid-meeting. They want to leave with a decision, not a table to interpret.

**So:** `GET /analytics/summary/?from=&to=` answers a whole period in one
request — headline totals first (`total_output`, `total_downtime_hours`,
`on_time_pct`), so the state of things is legible in three seconds before any
chart renders. `downtime_by_reason` is returned **sorted biggest-first**, so
"what is costing us the most" is element zero rather than something the client
has to work out. `per_machine` gives utilisation and availability side by side.
Downtime is clipped to the window — a stoppage that started before the range or
is still open only counts for the part inside it, and never past the snapshot
time — so two adjacent ranges can be added up without double-counting.

---

## What the data turned out to be

- **`unit_events.csv` has 200 byte-identical duplicate rows** — same `event_id`,
  same `serial_no`. The real count is 80,333, not 80,533. The loader drops them
  and reports how many; `serial_no UNIQUE` catches them at the database too.
  Keeping them would have inflated every output figure.
- **12 of 68 orders have no machine assigned**, so `orders.machine_id` is
  nullable and the floor board handles a machine with no current order.
- **Two stoppages are still open** at the snapshot time. An empty `ended_at`
  means *still down*, not bad data, and analytics clips those at the snapshot so
  they can't accrue hours into the future.
- **`orders.status` is typed in by a person and can disagree with reality.** Six
  statuses appear in the file, including `on_hold`, `planned` and `released`.
  Every order response carries a `derived_status` computed from `unit_events` and
  a `status_mismatch` flag, rather than silently trusting either one.
- **No timezones anywhere.** Timestamps are plain factory-local time and stay
  that way — `USE_TZ = False` — so a server in another region can't shift the
  numbers.

---

## Assumptions

- The snapshot time `2026-08-17 09:15` is "now" everywhere.
- A machine works one order at a time, so "current order per machine" is
  well-defined.
- **No authentication was built.** The brief asks for three different screens for
  three kinds of user and never mentions login, accounts or sessions — and the
  wall display is explicitly described as having no keyboard and nobody operating
  it, which a login screen contradicts. So the three views are three routes, not
  three roles. A real deployment would want access control; see below.
- Utilisation is measured against wall-clock hours in the chosen range. Nothing in
  the data says when shifts run, so a multi-day range counts nights as available
  time and utilisation reads lower than a shift-based figure would.

---

## Deployment

`render.yaml` describes a web service plus a free Postgres. Note that Render only
reads it when the service is created **from a Blueprint** — a service created
through the dashboard needs its environment variables set by hand.

**A deploy needs no manual steps.** The container sets itself up on boot:

```
makemigrations              Django's record of the model state
migrate --fake AtombergApp  applied, but no DDL
migrate                     Django's own tables, for real
ensure_schema               creates the six tables from schema.sql if missing
load_csv data --if-empty    seeds 80,333 rows, skipped if already loaded
collectstatic
gunicorn
```

A restart is a no-op: `Tables already present.` and `Data already loaded,
skipping.` Push, and the next deploy builds the schema and loads the data by
itself.

Environment variables the service needs: `SECRET_KEY`, `DATABASE_URL`,
`DEBUG=False`, `ALLOWED_HOSTS`, `PORT=10000`, and the two CORS/CSRF origins once
a frontend exists.

---

## Troubleshooting

**`relation "machines" does not exist`**
The migration record says applied, but the tables aren't there — `migrate` is
faked, so it never creates them. Run `python manage.py ensure_schema`, which
applies `schema.sql` when the tables are missing. A redeploy does this on its
own; this is only for a database you're poking at by hand.

**Render: "No open ports detected"**
Gunicorn is on the wrong port. Render scans 10000; make sure `PORT=10000` is set
or that the bind falls back to it.

**Render: health check never succeeds**
With `DEBUG=False` every URL redirects to HTTPS, and Render's internal check
arrives without the `X-Forwarded-Proto` header, so it sees a 301 rather than a
200. Point the health check at `/healthz`, which is exempt.

**Render: deploy times out with no response**
The container isn't starting. `SECRET_KEY` and the database settings have no
defaults, so a missing one exits at startup — check the deploy log for the
traceback.

**Tests fail with `relation "machines" does not exist`**
No migration file, so Django had nothing to build the test database from. The
folder is empty in version control by design — run
`python manage.py makemigrations AtombergApp` once, then run the tests.

---

## Cut, and what's next

- **The React frontend** — the remaining deliverable.
- **Authentication and role-based access.** Right now anyone with the URL can
  edit an order. A real deployment wants login for the desk and manager views,
  with the wall display on an internal network or an unguessable URL.
- **A summary table for order progress**, maintained by a trigger, if counting
  `unit_events` ever gets slow. It isn't slow at 80k rows.
- **A dedicated SQL migration tool** — Flyway or Sqitch — if the schema starts
  evolving. `schema.sql` doesn't update itself when a model changes; today there
  is one schema version, so it hasn't come up.
- **`COPY` instead of `bulk_create`** in the loader, at millions of rows.
- **Websocket push** for the floor board, if 5–10 second polling stops being
  enough.
- **An audit trail on order edits.**

---

## Layout

```
schema.sql                     hand-written DDL — the source of truth
data/                          the six CSVs
Atomberg/settings.py           configuration, all env-driven
AtombergApp/
  clock.py                     the snapshot "now"
  models/                      one file per table
  serializers/                 validation, shared by every write path
  views/                       one file per resource
  management/commands/load_csv.py
  migrations/0001_initial.py   runs schema.sql, or is faked
  tests.py                     17 tests
Dockerfile                     production: one process, managed database
Dockerfile.standalone          demo: Postgres and API in one image
docker-compose.yml             development: db + seed + api
render.yaml                    Render blueprint
```
