from datetime import timedelta

from django.db.models import Count
from rest_framework.decorators import api_view
from rest_framework.response import Response

from AtombergApp.clock import now
from AtombergApp.models import Machine, Order, DowntimeEvent, UnitEvent
from AtombergApp.serializers import MachineSerializer

PACE_AMBER_RATIO = 0.9  # below 90% of target rate = behind


@api_view(["GET"])
def machine_list(request):
    machines = Machine.objects.all()
    serializer = MachineSerializer(machines, many=True)
    return Response(serializer.data)


@api_view(["GET"])
def floor_status(request):
    """One small payload for the wall board: every machine, every refresh."""
    current = now()
    window_start = current - timedelta(hours=1)
    result = []

    # ponytail: a per-machine loop is fine for a handful of machines.
    # Group by machine_id in one query if this ever runs on hundreds.
    for machine in Machine.objects.all():
        current_order = (
            Order.objects.filter(machine=machine, status=Order.Status.IN_PROGRESS)
            .select_related("sku")
            .order_by("-priority", "due_date")
            .annotate(units_done=Count("unit_events"))
            .first()
        )
        downtime = (
            DowntimeEvent.objects.filter(machine=machine, ended_at__isnull=True)
            .select_related("reason")
            .order_by("started_at")
            .first()
        )
        recent_units = UnitEvent.objects.filter(
            machine=machine, completed_at__gte=window_start, completed_at__lte=current
        ).count()

        target = float(machine.target_units_per_hour)
        if downtime is not None:
            pace = "stopped"
        elif current_order is None:
            pace = "idle"
        elif recent_units < target * PACE_AMBER_RATIO:
            pace = "behind"
        else:
            pace = "on_pace"

        result.append({
            "machine_code": machine.machine_code,
            "machine_name": machine.name,
            "current_order": current_order.order_no if current_order else None,
            "sku_code": current_order.sku.sku_code if current_order else None,
            "qty_planned": current_order.qty_planned if current_order else None,
            "units_completed": current_order.units_done if current_order else None,
            "progress_pct": (
                round(min(100.0, 100.0 * current_order.units_done / current_order.qty_planned), 1)
                if current_order and current_order.qty_planned else None
            ),
            "units_last_hour": recent_units,
            "target_units_per_hour": target,
            "pace": pace,
            "is_down": downtime is not None,
            # Plain words, not a reason code — nobody decodes DT-QAL from across a room.
            "downtime_reason": downtime.reason.description if downtime else None,
            "downtime_category": downtime.reason.category if downtime else None,
            "down_since": downtime.started_at if downtime else None,
            "down_minutes": (
                round((current - downtime.started_at).total_seconds() / 60) if downtime else None
            ),
        })

    return Response({"as_of": current, "machines": result})
