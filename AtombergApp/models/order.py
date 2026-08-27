from django.db import models
from AtombergApp.models.machine import Machine
from AtombergApp.models.sku import SKU


class Order(models.Model):
    class Priority(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        PLANNED = "planned", "Planned"
        RELEASED = "released", "Released"
        ON_HOLD = "on_hold", "On Hold"
    TERMINAL = (Status.COMPLETED, Status.CANCELLED)

    order_id = models.BigAutoField(primary_key=True)
    order_no = models.CharField(max_length=100, unique=True)
    sku = models.ForeignKey(
        SKU,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    qty_planned = models.PositiveIntegerField()
    due_date = models.DateField()
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    machine = models.ForeignKey(
        Machine,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="orders",
    )
    # base
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "orders"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(qty_planned__gt=0),
                name="order_qty_positive",
            ),
        ]
        indexes = [
            models.Index(fields=["status"], name="idx_orders_status"),
            models.Index(fields=["machine"], name="idx_orders_machine"),
            models.Index(fields=["due_date"], name="idx_orders_due_date"),
            models.Index(fields=["priority"], name="idx_orders_priority"),
        ]

    def __str__(self):
        return self.order_no
