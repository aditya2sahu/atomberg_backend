# Order to Output — Solution Design

**Assignment:** Atomberg · Software Engineer, Full Stack (take-home)
**"Current time" for all calculations:** `2026-08-17 09:15` (local factory time — the data is a snapshot, not live, so this stands in for "now" everywhere in the app)

This is the plan for the assignment, written out in plain language: what to build, and — for every real decision — *why* that's the right call for this specific problem, not just a default. It covers schema, API, frontend, the auth question, and deployment.

---

## 1. Understanding the data before designing anything

Before picking a schema, it's worth actually looking at what's in the CSVs rather than just the brief's description of them:

| File | Columns |
|---|---|
| `machines.csv` | `machine_code, name, target_units_per_hour` |
| `skus.csv` | `sku_code, description, std_cycle_time_sec` |
| `orders.csv` | `order_no, sku_code, qty_planned, due_date, priority, status, machine_code` |
| `unit_events.csv` | `event_id, machine_code, order_no, completed_at, serial_no` |
| `downtime_events.csv` | `downtime_id, machine_code, started_at, ended_at, reason_code, note` |
| `downtime_reasons.csv` | `reason_code, description, category` (`planned` / `unplanned`) |

A few things jump out, and each one changes a design decision later:

- **An order never stores how many units are actually done.** `qty_planned` is on the order; the only place "how many finished" lives is as a count of rows in `unit_events` for that order. So "progress" has to be *calculated*, not stored — if we stored a `qty_done` column on the order and also had unit_events, the two would eventually disagree (a classic duplicated-data bug), and nobody would know which one to trust.
- **`orders.status` is a field someone typed in, not a fact derived from the data.** It could be stale — an order marked `in_progress` that's actually finished, or vice versa. The dashboards should compute the real state from `unit_events` and treat the stored `status` as what the planning team *believes*, flagging the two when they disagree, rather than blindly trusting either one.
- **A stoppage can still be happening** — `downtime_events.ended_at` is empty for a machine that's down right now. The floor board has to treat "no end time" as "still down," not as bad data.
- **`serial_no` looks like it identifies one physical unit.** If the same serial ever appears twice, that's a duplicate — worth a hard constraint so a re-run of the data pipeline can't silently double-count output.
- **No timezone anywhere.** Every timestamp is factory-local. The safest thing is to never convert it to anything else — just store and compare it as plain local time, so a server running in a different timezone can't quietly shift the numbers.
- **80,533 rows today, growing.** This is the one table (`unit_events`) that will actually get slow if it's not indexed correctly, because every screen — the order book, the floor board, and the analytics dashboard — ends up asking it questions.

---

## 2. Database: why Postgres, and why this shape

**Why a relational database at all, and why Postgres specifically:** the data is inherently relational — an order belongs to one SKU and one machine, a unit event belongs to one order and one machine, and the questions being asked ("how many units for this order," "how much downtime this week by reason") are aggregations and joins across those relationships. That's exactly what SQL is built for. Postgres specifically because it's free, well understood, has proper foreign keys and constraints to catch bad data at write time instead of finding out later, and its indexing options (partial indexes, composite indexes) map well onto the specific query patterns this app needs — see below.

**Why not just store progress on the order row, to save a `COUNT()` on every page load?** Because it would mean maintaining two sources of truth for the same fact. The moment a unit event is inserted and the order's count *isn't* updated in the same breath, they drift apart — and drift is the kind of bug that doesn't show up in testing, only in production, three weeks later, in a number the plant manager is trusting. Deriving it live keeps there being exactly one correct answer. If this ever becomes too slow at real scale (thousands of orders, millions of events — not the case yet at 68 orders / 80k events), the fix is a **summary table kept in sync by a database trigger**, not a manually-updated column — that's called out below as a "next step," not built now, because it's solving a performance problem that doesn't exist yet.

```sql
CREATE TABLE machines (
    machine_code        TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    target_units_per_hour  NUMERIC(10,2) NOT NULL CHECK (target_units_per_hour > 0)
);

CREATE TABLE skus (
    sku_code            TEXT PRIMARY KEY,
    description         TEXT NOT NULL,
    std_cycle_time_sec  NUMERIC(10,2) NOT NULL CHECK (std_cycle_time_sec > 0)
);

CREATE TYPE order_priority AS ENUM ('low', 'normal', 'high');
CREATE TYPE order_status   AS ENUM ('pending', 'in_progress', 'completed', 'cancelled');

CREATE TABLE orders (
    order_no       TEXT PRIMARY KEY,
    sku_code       TEXT NOT NULL REFERENCES skus(sku_code),
    qty_planned    INTEGER NOT NULL CHECK (qty_planned > 0),
    due_date       DATE NOT NULL,
    priority       order_priority NOT NULL DEFAULT 'normal',
    status         order_status NOT NULL DEFAULT 'pending',
    machine_code   TEXT NOT NULL REFERENCES machines(machine_code),
    created_at     TIMESTAMP NOT NULL DEFAULT now(),
    updated_at     TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE downtime_reasons (
    reason_code    TEXT PRIMARY KEY,
    description    TEXT NOT NULL,
    category       TEXT NOT NULL CHECK (category IN ('planned', 'unplanned'))
);

CREATE TABLE downtime_events (
    downtime_id    TEXT PRIMARY KEY,
    machine_code   TEXT NOT NULL REFERENCES machines(machine_code),
    started_at     TIMESTAMP NOT NULL,
    ended_at       TIMESTAMP,              -- empty = still down right now
    reason_code    TEXT NOT NULL REFERENCES downtime_reasons(reason_code),
    note           TEXT,
    CHECK (ended_at IS NULL OR ended_at >= started_at)
);

CREATE TABLE unit_events (
    event_id       TEXT PRIMARY KEY,
    machine_code   TEXT NOT NULL REFERENCES machines(machine_code),
    order_no       TEXT NOT NULL REFERENCES orders(order_no),
    completed_at   TIMESTAMP NOT NULL,
    serial_no      TEXT NOT NULL UNIQUE     -- catches duplicate/double-loaded units
);
```

**Why these specific indexes, and not just "index everything":**

```sql
CREATE INDEX idx_orders_status        ON orders(status);
CREATE INDEX idx_orders_machine       ON orders(machine_code);
CREATE INDEX idx_orders_due_date      ON orders(due_date);
CREATE INDEX idx_orders_priority      ON orders(priority);

CREATE INDEX idx_unit_events_order        ON unit_events(order_no);
CREATE INDEX idx_unit_events_machine_time ON unit_events(machine_code, completed_at);
CREATE INDEX idx_unit_events_time         ON unit_events(completed_at);

CREATE INDEX idx_downtime_machine_time ON downtime_events(machine_code, started_at);
CREATE INDEX idx_downtime_open         ON downtime_events(machine_code) WHERE ended_at IS NULL;
CREATE INDEX idx_downtime_reason       ON downtime_events(reason_code);
```

Every index above exists because a specific screen needs it fast:

- `idx_unit_events_order` — this is used constantly: every time anyone (any of the three people) looks at an order, the app counts its units. Without this index, that's a full scan of 80,000+ rows, every time.
- `idx_unit_events_machine_time` (both columns together) — the floor board asks "how many units has this machine finished recently," which filters on machine *and* time at once. A combined index answers that in one lookup instead of two.
- `idx_downtime_open` — a **partial** index, meaning it only indexes the handful of rows where `ended_at` is still empty. The floor board asks "is this machine down right now" on every single refresh (every 5–10 seconds). Since almost all downtime rows are closed, indexing only the open ones keeps that index tiny and that check nearly instant.
- `idx_orders_due_date` / `idx_orders_status` — these back the planning team's most common questions: what's due this week, what hasn't started.

Anything not queried directly (like `note` on downtime, or `description` on SKUs) is deliberately left unindexed — an index isn't free, it slows down every write, so it should only exist where a read actually needs it.

### Loading the CSVs
A load script that inserts in an order that respects the foreign keys — machines and SKUs first, then orders, then downtime reasons, then downtime events and unit events — using Postgres's bulk `COPY` command for the two big files (`orders`, `unit_events`) instead of inserting row by row, because row-by-row inserts on 80,000+ rows would be needlessly slow. The whole load runs inside one transaction, so if a row is malformed halfway through, the database rolls back cleanly instead of being left half-loaded.

---

## 3. API: why Django REST Framework, and what it needs to do

**Why Python + DRF over hand-rolling something in Node:** the assignment allows either. Django REST Framework gives three things almost for free that would otherwise have to be built by hand: request validation (rejecting bad data before it touches the database), pagination, and filtering/search. Since a large chunk of what this API needs to do *is* validation and filtering, using a framework that already does it well is less code and fewer places for bugs to hide, rather than reinventing it in a lighter Node framework.

| Endpoint | What it's for, and why it's shaped this way |
|---|---|
| `GET /api/machines` | Small, static reference list — machines don't change often, so this can be simple and even cached. |
| `GET /api/skus` | Same reasoning. |
| `GET /api/downtime-reasons` | Same reasoning. |
| `GET /api/orders` | The order book, with filters (`status`, `machine`, `priority`, due-date range, text search) and pagination — this is what the desk staff live in all day. |
| `POST /api/orders` | Create an order. Every field gets checked on the server (SKU and machine actually exist, quantity is positive, due date isn't already in the past) — see the validation note below for why this can't just be a UI-side check. |
| `PATCH /api/orders/{order_no}` | Reassign machine, change priority, update quantity — same validation as create, because an edit is just as capable of introducing bad data as a create is. |
| `GET /api/orders/{order_no}` | One order's detail: planned quantity, units done so far (counted from `unit_events`, not stored), and a rough "expected finish" based on the machine's target rate. |
| `GET /api/floor/status` | One single, small response built specifically for the wall board: per machine, its current order, progress, whether it's running or stopped, and why if it's stopped. This is a separate endpoint from `/orders` on purpose (explained below). |
| `GET /api/analytics/summary?from=&to=` | Everything the plant manager needs for a chosen date range: total output, on-time vs late, downtime broken down by reason, and how busy each machine was. |

**Why the floor board gets its own endpoint instead of reusing `/api/orders`:** the wall display polls constantly and needs to be fast and tiny — one machine card's worth of data, four times. `/api/orders` is built for browsing (pagination, filters, lots of optional detail). Mixing those two use cases into one endpoint would either make the order book bloated or make the floor board slow. Separating them means each one can be optimized for what it's actually doing.

**Why validation has to happen on the server, not just in the React forms:** the brief explicitly calls this out — "requests sent directly to the API, bypassing your UI, must be validated server-side" — and it's good practice regardless. A browser form can be skipped entirely by anyone calling the API directly (a script, a bug, or someone testing with `curl`). If the *only* check for "is this quantity positive" lives in a React form, then that check simply doesn't exist for anyone who isn't using that form. DRF's serializers run the same validation rules no matter who's calling, so a `POST` with an invalid `sku_code` gets rejected with a clear `400` error either way.

**Why cursor-based pagination for `unit_events`, but not for orders:** with 80,000+ rows, "give me page 500" using a normal `LIMIT/OFFSET` means the database still has to count through the first 499 pages to get there — that gets slower as the table grows. Cursor-based pagination ("give me everything after this specific row") stays fast no matter how big the table gets. The order list, at 68 rows today and growing much more slowly, doesn't have that problem, so plain pagination is fine there — no need to add the extra complexity where it isn't earning its keep.

**Why polling instead of a real-time push connection (websockets) for the floor board:** websockets solve the problem of "many clients need instant updates with minimal delay." Here there's exactly one screen, refreshing every 5–10 seconds is genuinely fast enough for a factory floor, and polling is much simpler to build, deploy, and debug. Reaching for websockets here would be solving a scale problem that doesn't exist.

---

## 4. Do we need login-based authentication? (addressing this directly)

The brief says: *"You are building for three different kinds of user, and they should not all be given the same screen."*

It's worth being precise about what that sentence is asking for, because there are two different things it *could* mean:

1. **"Show different screens to different roles"** — i.e., the *product* has to be role-aware: a desk-staff screen, a floor-board screen, and a manager screen, each built for what that person needs. This is definitely required — it's the whole point of Part 03 of the brief.
2. **"Log in as a role and be prevented from seeing the other screens"** — i.e., actual authentication (proving who you are) and authorization (restricting what you're allowed to see or do based on that).

**My read: the brief is asking for (1), not (2).** Nowhere does it mention login, credentials, sessions, or user accounts — the "people" section describes *how* each person works (desk, wall display with no keyboard, tablet in meetings), not how they'd log in. The wall-mounted display in particular is described as having **no mouse, no keyboard, nobody operating it** — which is hard to square with a login screen, since there'd be no one there to type a password into it. That description reads as "this is just the URL the TV is permanently pointed at," not "this requires a login."

So the practical plan: **build three separate routes** (`/orders` for desk staff, `/floor` for the wall board, `/analytics` for the plant manager) that each show the right thing, **without a login system**. This satisfies the letter of the brief without inventing a requirement that isn't there.

That said, it's a genuinely reasonable thing to flag as an assumption in the README rather than silently deciding it — if this were a real production factory app (not a take-home), you would absolutely want role-based access control, because right now anyone with the URL to `/orders` could edit an order meant only for the planning team. The honest way to handle this in a take-home is: **build it without auth, but say explicitly in the README that this was a deliberate scope decision** and describe how it would be added (a simple login for the desk and manager screens, machine restricted to internal network or an unguessable URL since nobody operates it) — that shows you noticed the gap rather than missed it.

---

## 5. Frontend: three screens, each built for how that person actually works

The three screens aren't just three different layouts of the same data — each one exists because that person's *situation* is different, and the design should follow from that, not from habit.

### Desk staff — Order Book (`/orders`)
**Why it looks like this:** this is the one persona that actually needs to *do* things — create orders, edit them, search for a specific one. So this is where forms, inline validation, and clear error messages matter, because they're the ones who'll hit a validation error and need to know exactly what to fix.
- Table with server-side search/filter/sort (status, machine, priority, due-date range) — server-side because with the dataset growing into the thousands, filtering in the browser after fetching everything won't hold up.
- Row expands into detail: a progress bar (units done vs planned) and a projected completion time.
- Create/edit as a form, with field-level errors shown next to the field that's wrong, sourced from the API's actual validation response — not a generic "something went wrong" toast, since the brief specifically calls out "clear feedback when something is rejected."

### Floor supervisor — Wall Board (`/floor`)
**Why it looks like this:** this person never touches the screen, glances at it from several metres away for a second or two, and usually has their hands full. Every design choice follows from that constraint, not from what looks nice on a laptop.
- Fixed layout sized for the 1920×1080 wall display, one card per machine, nothing that requires scrolling.
- Each card: current order, a large progress bar, actual vs target units/hour, and a color state (green = on pace, amber = behind, red = stopped) — color and size carry the meaning because there's no time to read paragraphs from across a room.
- If a machine is stopped, the downtime reason is shown in plain words, not a reason code — the supervisor shouldn't have to decode `DT-QAL`.
- No buttons, no navigation, nothing clickable — the brief is explicit that nobody operates this display, so anything interactive would just be wasted design.
- Refreshes itself automatically (polling); it has to "stay correct without anyone touching it," so it can never depend on a person hitting refresh.

### Plant manager — Analytics (`/analytics`)
**Why it looks like this:** this person is thinking in weeks, not minutes, and wants to walk away with a decision, not raw numbers — "depth matters more than immediacy" per the brief.
- A date range picker up top, since they choose the period themselves.
- Headline summary numbers (total output, total downtime hours, on-time %) before any charts, so the state of things is legible in the first three seconds, on a tablet, possibly in a meeting.
- A downtime breakdown by reason (a Pareto-style chart — which single cause is costing the most hours), because the brief specifically says they want to know "what is costing the factory the most," and a plain list of numbers doesn't answer that as directly as a chart sorted by impact does.
- Touch-sized controls, since this is used on a tablet — no reliance on hover states or tiny click targets.

---

## 6. Deployment

- **Database:** a managed Postgres instance (Render, Railway, or Supabase all have a free tier that's more than enough for 80k rows) — managed hosting means not having to babysit backups or patching for a take-home project.
- **API:** Render or Railway, deployed from the same repo, with the database URL and other secrets set as environment variables rather than hardcoded.
- **Frontend:** Vercel or Netlify, configured to call the deployed API's URL — both are effectively free and handle the build/deploy step automatically on every push.
- Database migrations run automatically as part of each deploy; the CSV data is loaded once, manually, against the live database after the first deploy.

---

## 7. README outline (what actually goes in the writeup once it's built)

1. **How to run it locally** — from `git clone` to a working app: environment setup, install dependencies, set env vars, run migrations, run the loader script, start the API, start the frontend.
2. **Schema and indexes, and why** — the tables above, and specifically: why progress is calculated instead of stored, why the open-downtime index is partial, why the machine+time index is composite.
3. **API shape, and what drove it** — the endpoint table, and why the floor board got its own lightweight endpoint instead of reusing the order list.
4. **What was built for each person, and why that** — tie each screen directly back to the constraint that shaped it: no interaction + readable from a distance → the wall board's whole design; needs to create and edit things → the desk staff's forms and validation feedback.
5. **What I noticed about the data, and what I did about it** — the null `ended_at` (still-down) handling, `orders.status` possibly disagreeing with reality, no timezones anywhere, the `serial_no` uniqueness check.
6. **Assumptions** — the snapshot timestamp stands in for "now" everywhere; a machine works one order at a time, so "current order per machine" is always well-defined; no login/auth was built, and why (see Section 4), with a note on how it'd be added for real production use.
7. **What was cut, and what I'd add next** — a summary table for order progress if the data grows much larger; websocket push for the floor board if 5–10 second polling ever isn't fast enough; real authentication and role-based access if this went to production; an audit trail on order edits.

---

## 8. Deliverables checklist
- [ ] Private Git repo with real, incremental commit history (schema → loader → API → each frontend screen as separate commits) — this lets the history itself show the order things were actually built in, rather than one squashed commit that hides the process.
- [ ] Live URL for the deployed frontend
- [ ] The README, following the outline above
