from django.db import models
from AtombergApp.models.machine import Machine
from AtombergApp.models.order import Order


class UnitEvent(models.Model):
    event_id = models.CharField(max_length=100, unique=True)
    machine = models.ForeignKey(
        Machine,
        on_delete=models.PROTECT,
        related_name="unit_events",
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.PROTECT,
        related_name="unit_events",
    )
    completed_at = models.DateTimeField()
    serial_no = models.CharField(
        max_length=100,
        unique=True,
    )

    class Meta:
        db_table = "unit_events"
        indexes = [
            models.Index(
                fields=["order"],
                name="idx_unit_events_order",
            ),
            models.Index(
                fields=["machine", "completed_at"],
                name="idx_unit_events_machine_time",
            ),
            models.Index(
                fields=["completed_at"],
                name="idx_unit_events_time",
            ),
        ]

    def __str__(self):
        return self.event_id
