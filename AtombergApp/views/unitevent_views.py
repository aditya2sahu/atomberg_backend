from datetime import datetime, timedelta

from django.db.models import Count
from rest_framework.decorators import api_view
from rest_framework.pagination import CursorPagination
from rest_framework.response import Response

from AtombergApp.clock import now
from AtombergApp.models import DowntimeEvent, Order, UnitEvent
from AtombergApp.serializers import UnitEventSerializer


class UnitEventPagination(CursorPagination):
    # Cursor, not offset: page 500 of 80k rows shouldn't get slower than page 1.
    page_size = 100
    max_page_size = 1000
    page_size_query_param = "page_size"
    ordering = ("-completed_at", "-event_id")


def _parse_range(request):
    """Naive local datetimes — the factory data has no timezone, so we add none."""
    current = now()
    date_from = request.GET.get("from")
    date_to = request.GET.get("to")
    start = datetime.strptime(date_from, "%Y-%m-%d") if date_from else current - timedelta(days=7)
    end = (
        datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1) if date_to else current
    )
    # Nothing can have happened after the snapshot, so a range covering today
    # stops at "now" — otherwise an open downtime would be billed hours into the future.
    return start, min(end, current)


@api_view(["GET"])
def unit_event_list(request):
    events = UnitEvent.objects.all()
    machine = request.GET.get("machine")
    if machine:
        events = events.filter(machine__machine_code=machine)
    order_no = request.GET.get("order")
    if order_no:
        events = events.filter(order__order_no=order_no)
    start, end = _parse_range(request)
    if request.GET.get("from") or request.GET.get("to"):
        events = events.filter(completed_at__gte=start, completed_at__lt=end)

    paginator = UnitEventPagination()
    page = paginator.paginate_queryset(events, request)
    return paginator.get_paginated_response(UnitEventSerializer(page, many=True).data)


@api_view(["GET"])
def analytics_summary(request):
    start, end = _parse_range(request)
    window_hours = max((end - start).total_seconds() / 3600, 0)

    units = UnitEvent.objects.filter(completed_at__gte=start, completed_at__lt=end)
    total_output = units.count()

    # Downtime clipped to the window: an event that starts before it or is still
    # open only counts for the part that falls inside.
    # ponytail: summed in Python — hundreds of rows. Push to SQL if it hits millions.
    overlapping = (
        DowntimeEvent.objects.filter(started_at__lt=end)
        .exclude(ended_at__lt=start)
        .select_related("reason", "machine")
    )
    by_reason = {}
    machine_downtime = {}
    planned_hours  = 0.0
    unplanned_hours = 0.0
    for dt in overlapping:
        finish = min(dt.ended_at or end, end)   # open event = still down right now
        began = max(dt.started_at, start)
        hours = max((finish - began).total_seconds() / 3600, 0)
        row = by_reason.setdefault(dt.reason.reason_code, {
            "reason_code": dt.reason.reason_code,
            "description": dt.reason.description,
            "category": dt.reason.category,
            "hours": 0.0,
            "events": 0,
        })
        row["hours"] += hours
        row["events"] += 1
        if dt.reason.category == "planned":
            planned_hours += hours
        else:
            unplanned_hours += hours
        code = dt.machine.machine_code
        machine_downtime[code] = machine_downtime.get(code, 0.0) + hours

    # Pareto order: biggest cost first, which is the question being asked.
    downtime_by_reason = sorted(by_reason.values(), key=lambda r: r["hours"], reverse=True)
    for row in downtime_by_reason:
        row["hours"] = round(row["hours"], 2)

    # On time vs late, judged on unit_events rather than the typed-in status.
    on_time = 0
    late = 0
    open_late = 0
    orders = Order.objects.annotate(units_done=Count("unit_events")).exclude(
        status=Order.Status.CANCELLED
    )
    for order in orders:
        if order.units_done >= order.qty_planned:
            last = (
                UnitEvent.objects.filter(order=order)
                .order_by("-completed_at")
                .values_list("completed_at", flat=True)
                .first()
            )
            if last and last.date() > order.due_date:
                late += 1
            else:
                on_time += 1
        elif order.due_date < now().date():
            open_late += 1
    finished = on_time + late

    per_machine = []
    machine_units = dict(
        units.values_list("machine__machine_code")
        .annotate(n=Count("id"))
        .values_list("machine__machine_code", "n")
    )
    from AtombergApp.models import Machine
    for machine in Machine.objects.all():
        produced = machine_units.get(machine.machine_code, 0)
        capacity = float(machine.target_units_per_hour) * window_hours
        down = machine_downtime.get(machine.machine_code, 0.0)
        per_machine.append({
            "machine_code": machine.machine_code,
            "machine_name": machine.name,
            "units_produced": produced,
            "target_units": round(capacity, 1),
            "utilization_pct": round(100.0 * produced / capacity, 1) if capacity else None,
            "downtime_hours": round(down, 2),
            "availability_pct": round(100.0 * (1 - down / window_hours), 1) if window_hours else None,
        })

    return Response({
        "from": start,
        "to": end,
        "total_output": total_output,
        "total_downtime_hours": round(planned_hours + unplanned_hours, 2),
        "planned_downtime_hours": round(planned_hours, 2),
        "unplanned_downtime_hours": round(unplanned_hours, 2),
        "downtime_by_reason": downtime_by_reason,
        "orders_completed": finished,
        "orders_on_time": on_time,
        "orders_late": late,
        "orders_overdue_open": open_late,
        "on_time_pct": round(100.0 * on_time / finished, 1) if finished else None,
        "per_machine": per_machine,
    })
