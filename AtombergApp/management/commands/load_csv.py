"""Load the factory CSV snapshot. Foreign-key order matters; one transaction, all or nothing."""
import csv
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from AtombergApp.models import DowntimeEvent, DowntimeReason, Machine, Order, SKU, UnitEvent

BATCH = 5000


def _dt(value):
    """Factory timestamps are local and timezone-free; keep them naive."""
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=None)
        except ValueError:
            continue
    raise CommandError(f"Unrecognised timestamp: {value!r}")


def _date(value):
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def _rows(folder, name):
    path = Path(folder) / name
    if not path.exists():
        raise CommandError(f"Missing {path}")
    with path.open(newline="", encoding="utf-8-sig") as fh:
        yield from csv.DictReader(fh)


class Command(BaseCommand):
    help = "Load machines/skus/orders/downtime/unit events from a folder of CSVs."

    def add_arguments(self, parser):
        parser.add_argument("folder", help="Directory holding the six CSV files")
        parser.add_argument("--flush", action="store_true", help="Delete existing rows first")
        parser.add_argument("--if-empty", action="store_true",
                            help="Do nothing if the database already holds data (deploy boot)")

    @transaction.atomic
    def handle(self, *args, **opts):
        folder = opts["folder"]

        # Render's free tier gives no shell, so seeding runs on every boot and
        # has to be a no-op once the data is there.
        if opts["if_empty"] and Machine.objects.exists():
            self.stdout.write("Data already loaded, skipping.")
            return

        if opts["flush"]:
            UnitEvent.objects.all().delete()
            DowntimeEvent.objects.all().delete()
            Order.objects.all().delete()
            DowntimeReason.objects.all().delete()
            SKU.objects.all().delete()
            Machine.objects.all().delete()

        # ponytail: bulk_create, not COPY — 80k rows load in seconds and it stays
        # database-agnostic. Swap in COPY the day this is millions of rows.
        self._load(Machine, "machine_code", _rows(folder, "machines.csv"), lambda r: Machine(
            machine_code=r["machine_code"].strip(),
            name=r["name"].strip(),
            target_units_per_hour=r["target_units_per_hour"],
        ))
        self._load(SKU, "sku_code", _rows(folder, "skus.csv"), lambda r: SKU(
            sku_code=r["sku_code"].strip(),
            description=r["description"].strip(),
            std_cycle_time_sec=r["std_cycle_time_sec"],
        ))
        self._load(DowntimeReason, "reason_code", _rows(folder, "downtime_reasons.csv"), lambda r: DowntimeReason(
            reason_code=r["reason_code"].strip(),
            description=r["description"].strip(),
            category=r["category"].strip(),
        ))
        skus = dict(SKU.objects.values_list("sku_code", "pk"))
        machines = dict(Machine.objects.values_list("machine_code", "pk"))
        reasons = dict(DowntimeReason.objects.values_list("reason_code", "pk"))

        self._load(Order, "order_no", _rows(folder, "orders.csv"), lambda r: Order(
            order_no=r["order_no"].strip(),
            sku_id=skus[r["sku_code"].strip()],
            qty_planned=int(r["qty_planned"]),
            due_date=_date(r["due_date"]),
            priority=r["priority"].strip().lower(),
            status=r["status"].strip().lower(),
            machine_id=machines.get(r["machine_code"].strip()),
        ))
        self._load(DowntimeEvent, "downtime_id", _rows(folder, "downtime_events.csv"), lambda r: DowntimeEvent(
            downtime_id=r["downtime_id"].strip(),
            machine_id=machines[r["machine_code"].strip()],
            started_at=_dt(r["started_at"]),
            ended_at=_dt(r["ended_at"]),      # blank = still down right now
            reason_id=reasons[r["reason_code"].strip()],
            note=(r.get("note") or "").strip() or None,
        ))
        orders = dict(Order.objects.values_list("order_no", "pk"))

        self._load(UnitEvent, "event_id", _rows(folder, "unit_events.csv"), lambda r: UnitEvent(
            event_id=r["event_id"].strip(),
            machine_id=machines[r["machine_code"].strip()],
            order_id=orders[r["order_no"].strip()],
            completed_at=_dt(r["completed_at"]),
            serial_no=r["serial_no"].strip(),
        ))

    def _load(self, model, key, rows, build):
        # unit_events.csv ships 200 byte-identical duplicate rows — same event_id,
        # same serial. Dropping them here is the difference between real output and
        # double-counted output. Loudly, so nobody mistakes it for clean data.
        seen, objects, dupes = set(), [], 0
        for row in rows:
            obj = build(row)
            if getattr(obj, key) in seen:
                dupes += 1
                continue
            seen.add(getattr(obj, key))
            objects.append(obj)
        model.objects.bulk_create(objects, batch_size=BATCH)
        msg = f"{model.__name__}: {len(objects)} rows"
        if dupes:
            msg += f"  ({dupes} duplicate rows skipped)"
            self.stdout.write(self.style.WARNING(msg))
        else:
            self.stdout.write(self.style.SUCCESS(msg))
