-- Surrogate BIGSERIAL primary keys; the codes from the CSVs stay as UNIQUE
-- business keys, so a code can be corrected without rewriting every child row.
--
-- Tables that get referenced name their key after themselves (machine_id,
-- sku_id, order_id, reason_id) so a join column reads the same on both sides.
-- The two event tables keep a plain `id`: nothing points at them, and their
-- CSV columns already occupy `downtime_id` / `event_id`.

CREATE TABLE machines (
    machine_id             BIGSERIAL PRIMARY KEY,
    machine_code           TEXT NOT NULL UNIQUE,
    name                   TEXT NOT NULL,
    target_units_per_hour  NUMERIC(10,2) NOT NULL
        CONSTRAINT machine_target_positive CHECK (target_units_per_hour > 0)
);

CREATE TABLE skus (
    sku_id              BIGSERIAL PRIMARY KEY,
    sku_code            TEXT NOT NULL UNIQUE,
    description         TEXT NOT NULL,
    std_cycle_time_sec  NUMERIC(10,2) NOT NULL
        CONSTRAINT sku_cycle_time_positive CHECK (std_cycle_time_sec > 0)
);

CREATE TABLE orders (
    order_id       BIGSERIAL PRIMARY KEY,
    order_no       TEXT NOT NULL UNIQUE,
    sku_id         BIGINT NOT NULL REFERENCES skus(sku_id),
    qty_planned    INTEGER NOT NULL
                   CONSTRAINT order_qty_positive CHECK (qty_planned > 0),
    due_date       DATE NOT NULL,
    priority       TEXT NOT NULL DEFAULT 'normal'
                   CHECK (priority IN ('low', 'normal', 'high')),
    status         TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'in_progress', 'completed',
                                    'cancelled', 'on_hold', 'planned', 'released')),
    machine_id     BIGINT NULL REFERENCES machines(machine_id),
    created_at     TIMESTAMP NOT NULL DEFAULT now(),
    updated_at     TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE downtime_reasons (
    reason_id      BIGSERIAL PRIMARY KEY,
    reason_code    TEXT NOT NULL UNIQUE,
    description    TEXT NOT NULL,
    category       TEXT NOT NULL CHECK (category IN ('planned', 'unplanned'))
);

CREATE TABLE downtime_events (
    id             BIGSERIAL PRIMARY KEY,
    downtime_id    TEXT NOT NULL UNIQUE,
    machine_id     BIGINT NOT NULL REFERENCES machines(machine_id),
    started_at     TIMESTAMP NOT NULL,
    ended_at       TIMESTAMP,              -- empty = still down right now
    reason_id      BIGINT NOT NULL REFERENCES downtime_reasons(reason_id),
    note           TEXT,
    CONSTRAINT downtime_ends_after_start
        CHECK (ended_at IS NULL OR ended_at >= started_at)
);

CREATE TABLE unit_events (
    id             BIGSERIAL PRIMARY KEY,
    event_id       TEXT NOT NULL UNIQUE,
    machine_id     BIGINT NOT NULL REFERENCES machines(machine_id),
    order_id       BIGINT NOT NULL REFERENCES orders(order_id),
    completed_at   TIMESTAMP NOT NULL,
    serial_no      TEXT NOT NULL UNIQUE     -- catches duplicate/double-loaded units
);

CREATE INDEX idx_orders_status        ON orders(status);
CREATE INDEX idx_orders_machine       ON orders(machine_id);
CREATE INDEX idx_orders_due_date      ON orders(due_date);
CREATE INDEX idx_orders_priority      ON orders(priority);

CREATE INDEX idx_unit_events_order        ON unit_events(order_id);
CREATE INDEX idx_unit_events_machine_time ON unit_events(machine_id, completed_at);
CREATE INDEX idx_unit_events_time         ON unit_events(completed_at);

CREATE INDEX idx_downtime_machine_time ON downtime_events(machine_id, started_at);
CREATE INDEX idx_downtime_open         ON downtime_events(machine_id) WHERE ended_at IS NULL;
CREATE INDEX idx_downtime_reason       ON downtime_events(reason_id);
