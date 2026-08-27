from django.db import models
from AtombergApp.models.machine import Machine
from AtombergApp.models.downtimereason import DowntimeReason


class DowntimeEvent(models.Model):
    downtime_id = models.CharField(max_length=100, unique=True)

    machine = models.ForeignKey(
        Machine,
        on_delete=models.PROTECT,
        related_name="downtime_events",
    )

    started_at = models.DateTimeField()

    ended_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    reason = models.ForeignKey(
        DowntimeReason,
        on_delete=models.PROTECT,
        related_name="downtime_events",
    )

    note = models.TextField(
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "downtime_events"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ended_at__isnull=True) | models.Q(ended_at__gte=models.F("started_at")),
                name="downtime_ends_after_start",
            ),
        ]
        indexes = [
            models.Index(
                fields=["machine", "started_at"],
                name="idx_downtime_machine_time",
            ),
            models.Index(
                fields=["machine"],
                name="idx_downtime_open",
                condition=models.Q(ended_at__isnull=True),
            ),
            models.Index(
                fields=["reason"],
                name="idx_downtime_reason",
            ),
        ]

    def __str__(self):
        return self.downtime_id
