"""One end-to-end check: load a tiny CSV snapshot, hit every endpoint, assert the numbers.

Run: python manage.py test AtombergApp
"""
import tempfile
from datetime import datetime
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from AtombergApp.clock import FACTORY_NOW

CSVS = {
    "machines.csv": "machine_code,name,target_units_per_hour\nM1,Line One,10\nM2,Line Two,20\n",
    "skus.csv": "sku_code,description,std_cycle_time_sec\nS1,Fan Blade,30\n",
    "downtime_reasons.csv": (
        "reason_code,description,category\n"
        "DT-QAL,Quality hold,unplanned\nDT-CLN,Scheduled cleaning,planned\n"
    ),
    "orders.csv": (
        "order_no,sku_code,qty_planned,due_date,priority,status,machine_code\n"
        "O1,S1,4,2026-08-20,high,in_progress,M1\n"      # 2 of 4 done
        "O2,S1,2,2026-08-10,normal,in_progress,M2\n"    # actually finished, but late
        "O3,S1,5,2026-08-12,low,pending,M1\n"           # overdue, nothing produced
    ),
    "downtime_events.csv": (
        "downtime_id,machine_code,started_at,ended_at,reason_code,note\n"
        "D1,M1,2026-08-17 07:15:00,,DT-QAL,still down\n"          # open, 2h to "now"
        "D2,M2,2026-08-16 08:00:00,2026-08-16 09:00:00,DT-CLN,\n"  # 1h planned
    ),
    "unit_events.csv": (
        "event_id,machine_code,order_no,completed_at,serial_no\n"
        "E1,M1,O1,2026-08-17 08:30:00,SN1\n"
        "E2,M1,O1,2026-08-17 08:45:00,SN2\n"
        "E3,M2,O2,2026-08-14 10:00:00,SN3\n"
        "E4,M2,O2,2026-08-14 11:00:00,SN4\n"
    ),
}


class OrderToOutputTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        folder = Path(tempfile.mkdtemp())
        for name, body in CSVS.items():
            (folder / name).write_text(body)
        call_command("load_csv", str(folder))

    def test_loader_respects_foreign_keys_and_blank_end_times(self):
        from AtombergApp.models import DowntimeEvent, Order, UnitEvent

        self.assertEqual(Order.objects.count(), 3)
        self.assertEqual(UnitEvent.objects.count(), 4)
        self.assertIsNone(DowntimeEvent.objects.get(downtime_id="D1").ended_at)
        self.assertEqual(Order.objects.get(order_no="O1").machine.machine_code, "M1")

    def test_order_progress_is_derived_not_stored(self):
        body = self.client.get("/api/orders/O1/").json()
        self.assertEqual(body["units_done"], 2)
        self.assertEqual(body["progress_pct"], 50.0)
        self.assertEqual(body["derived_status"], "in_progress")
        self.assertFalse(body["status_mismatch"])
        # 2 remaining at 10/hr = 12 minutes past the snapshot time.
        self.assertEqual(body["projected_completion"][:16], "2026-08-17T09:27")

    def test_stored_status_disagreeing_with_events_is_flagged(self):
        body = self.client.get("/api/orders/O2/").json()
        self.assertEqual(body["derived_status"], "completed")   # events say done
        self.assertEqual(body["status"], "in_progress")          # planning team says not
        self.assertTrue(body["status_mismatch"])
        self.assertTrue(body["is_late"])                         # finished after due date

    def test_order_list_filters_and_paginates(self):
        body = self.client.get("/api/orders/?machine=M1&status=in_progress").json()
        self.assertEqual([o["order_no"] for o in body["results"]], ["O1"])

    def test_validation_runs_server_side(self):
        bad = self.client.post("/api/orders/", {
            "order_no": "O9", "sku_code": "NOPE", "qty_planned": 0,
            "due_date": "2020-01-01", "machine_code": "M1",
        }, content_type="application/json")
        self.assertEqual(bad.status_code, 400)
        for field in ("sku_code", "qty_planned", "due_date"):
            self.assertIn(field, bad.json())

        ok = self.client.post("/api/orders/", {
            "order_no": "O9", "sku_code": "S1", "qty_planned": 3,
            "due_date": "2026-09-01", "machine_code": "M1",
        }, content_type="application/json")
        self.assertEqual(ok.status_code, 201, ok.json())

    def test_cannot_shrink_qty_below_units_already_produced(self):
        resp = self.client.patch("/api/orders/O1/", {"qty_planned": 1},
                                 content_type="application/json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("qty_planned", resp.json())

    def test_floor_board_lists_every_machine_including_stopped_ones(self):
        body = self.client.get("/api/floor/status/").json()
        cards = {m["machine_code"]: m for m in body["machines"]}
        self.assertEqual(set(cards), {"M1", "M2"})          # the loop used to return after one
        self.assertTrue(cards["M1"]["is_down"])
        self.assertEqual(cards["M1"]["downtime_reason"], "Quality hold")  # words, not DT-QAL
        self.assertEqual(cards["M1"]["pace"], "stopped")
        self.assertEqual(cards["M1"]["down_minutes"], 120)
        self.assertEqual(cards["M2"]["pace"], "behind")

    def test_unit_events_use_cursor_pagination(self):
        body = self.client.get("/api/unit-events/?page_size=2").json()
        self.assertEqual(len(body["results"]), 2)
        self.assertIsNotNone(body["next"])
        self.assertNotIn("count", body)   # no COUNT(*) over 80k rows per page

    def test_analytics_reports_hours_by_reason_and_on_time_split(self):
        body = self.client.get("/api/analytics/summary/?from=2026-08-14&to=2026-08-17").json()
        self.assertEqual(body["total_output"], 4)
        # Open downtime is clipped at the snapshot "now": 07:15 -> 09:15 = 2h.
        reasons = {r["reason_code"]: r for r in body["downtime_by_reason"]}
        self.assertEqual(reasons["DT-QAL"]["hours"], 2.0)
        self.assertEqual(reasons["DT-CLN"]["hours"], 1.0)
        self.assertEqual(body["downtime_by_reason"][0]["reason_code"], "DT-QAL")  # Pareto order
        self.assertEqual(body["unplanned_downtime_hours"], 2.0)
        self.assertEqual(body["planned_downtime_hours"], 1.0)
        self.assertEqual(body["orders_late"], 1)      # O2 finished after its due date
        self.assertEqual(body["orders_on_time"], 0)
        self.assertEqual(body["orders_overdue_open"], 1)   # O3, past due, nothing made
        self.assertEqual(body["on_time_pct"], 0.0)
        per_machine = {m["machine_code"]: m for m in body["per_machine"]}
        self.assertEqual(per_machine["M1"]["units_produced"], 2)
        self.assertEqual(per_machine["M2"]["downtime_hours"], 1.0)

    def test_duplicate_serial_is_rejected_by_the_database(self):
        from django.db import IntegrityError
        from AtombergApp.models import Machine, Order, UnitEvent
        with self.assertRaises(IntegrityError):
            UnitEvent.objects.create(
                event_id="E99",
                machine=Machine.objects.get(machine_code="M1"),
                order=Order.objects.get(order_no="O1"),
                completed_at=FACTORY_NOW, serial_no="SN1")

    def test_snapshot_now_is_not_shifted_by_a_timezone(self):
        stored = datetime.strptime("2026-08-17 08:30:00", "%Y-%m-%d %H:%M:%S")
        from AtombergApp.models import UnitEvent
        self.assertEqual(UnitEvent.objects.get(event_id="E1").completed_at, stored)


class BulkCreateTests(TestCase):
    """POST /api/bulk/<resource>/ — a list in, all or nothing."""

    def test_inserts_a_batch(self):
        resp = self.client.post("/api/bulk/machines/", [
            {"machine_code": "MC-01", "name": "One", "target_units_per_hour": 120},
            {"machine_code": "MC-02", "name": "Two", "target_units_per_hour": 90},
        ], content_type="application/json")
        self.assertEqual(resp.status_code, 201, resp.json())
        self.assertEqual(resp.json(), {"resource": "machines", "created": 2})

    def test_one_bad_row_rolls_back_the_whole_batch(self):
        from AtombergApp.models import Machine

        resp = self.client.post("/api/bulk/machines/", [
            {"machine_code": "MC-09", "name": "Good", "target_units_per_hour": 120},
            {"machine_code": "MC-10", "name": "Bad", "target_units_per_hour": -5},
        ], content_type="application/json")
        self.assertEqual(resp.status_code, 400)
        errors = resp.json()["errors"]           # keyed by row index, failing rows only
        self.assertNotIn("0", errors)             # row 0 was fine
        self.assertIn("target_units_per_hour", errors["1"])
        self.assertFalse(Machine.objects.filter(machine_code="MC-09").exists())

    def test_duplicate_key_rolls_back_and_reports_400(self):
        from AtombergApp.models import Machine

        Machine.objects.create(machine_code="MC-01", name="One", target_units_per_hour=120)
        resp = self.client.post("/api/bulk/machines/", [
            {"machine_code": "MC-77", "name": "New", "target_units_per_hour": 60},
            {"machine_code": "MC-01", "name": "Dupe", "target_units_per_hour": 60},
        ], content_type="application/json")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Machine.objects.filter(machine_code="MC-77").exists())

    def test_child_rows_resolve_their_parents_by_code(self):
        from AtombergApp.models import UnitEvent

        self.client.post("/api/bulk/machines/", [
            {"machine_code": "MC-01", "name": "One", "target_units_per_hour": 120}],
            content_type="application/json")
        self.client.post("/api/bulk/skus/", [
            {"sku_code": "S1", "description": "x", "std_cycle_time_sec": 30}],
            content_type="application/json")
        self.client.post("/api/bulk/orders/", [
            {"order_no": "O1", "sku_code": "S1", "qty_planned": 5,
             "due_date": "2026-09-01", "machine_code": "MC-01"}],
            content_type="application/json")
        resp = self.client.post("/api/bulk/unit-events/", [
            {"event_id": "E1", "machine_code": "MC-01", "order_no": "O1",
             "completed_at": "2026-08-17T08:00:00", "serial_no": "SN1"}],
            content_type="application/json")
        self.assertEqual(resp.status_code, 201, resp.json())
        self.assertEqual(UnitEvent.objects.get(event_id="E1").order.order_no, "O1")

    def test_unknown_parent_code_is_rejected_not_crashed(self):
        resp = self.client.post("/api/bulk/orders/", [
            {"order_no": "O9", "sku_code": "NOPE", "qty_planned": 5,
             "due_date": "2026-09-01", "machine_code": "MC-01"}],
            content_type="application/json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("sku_code", resp.json()["errors"]["0"])

    def test_rejects_bad_shapes_and_unknown_resources(self):
        self.assertEqual(self.client.post("/api/bulk/widgets/", [], content_type="application/json").status_code, 404)
        self.assertEqual(self.client.post("/api/bulk/machines/", [], content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post("/api/bulk/machines/", {"machine_code": "X"},
                                          content_type="application/json").status_code, 400)
