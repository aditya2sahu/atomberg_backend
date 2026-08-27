from AtombergApp.clock import now
from AtombergApp.models import Machine, Order, SKU
from rest_framework import serializers


class OrderSerializer(serializers.ModelSerializer):
    """Progress is always derived from unit_events, never stored on the order."""

    sku_code = serializers.SlugRelatedField(
        source="sku", slug_field="sku_code", queryset=SKU.objects.all()
    )
    machine_code = serializers.SlugRelatedField(
        source="machine",
        slug_field="machine_code",
        queryset=Machine.objects.all(),
        allow_null=True,
        required=False,
    )
    units_done = serializers.SerializerMethodField()
    progress_pct = serializers.SerializerMethodField()
    derived_status = serializers.SerializerMethodField()
    status_mismatch = serializers.SerializerMethodField()
    is_late = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "order_no", "sku_code", "qty_planned", "due_date", "priority", "status",
            "machine_code", "created_at", "updated_at",
            "units_done", "progress_pct", "derived_status", "status_mismatch", "is_late",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_units_done(self, obj):
        # Annotated by the list view; falls back to a COUNT for single-object reads.
        done = getattr(obj, "units_done", None)
        return done if done is not None else obj.unit_events.count()

    def get_progress_pct(self, obj):
        if not obj.qty_planned:
            return 0.0
        return round(min(100.0, 100.0 * self.get_units_done(obj) / obj.qty_planned), 1)

    def get_derived_status(self, obj):
        """What unit_events say, as opposed to what the planning team typed in."""
        done = self.get_units_done(obj)
        if done >= obj.qty_planned:
            return Order.Status.COMPLETED
        return Order.Status.IN_PROGRESS if done else Order.Status.PENDING

    def get_status_mismatch(self, obj):
        derived = self.get_derived_status(obj)
        if obj.status == Order.Status.CANCELLED:
            return False
        if derived == Order.Status.COMPLETED:
            return obj.status != Order.Status.COMPLETED
        return obj.status == Order.Status.COMPLETED

    def get_is_late(self, obj):
        if self.get_derived_status(obj) == Order.Status.COMPLETED:
            last = obj.unit_events.order_by("-completed_at").values_list("completed_at", flat=True).first()
            return bool(last and last.date() > obj.due_date)
        return obj.due_date < now().date() and obj.status not in Order.TERMINAL

    def validate_qty_planned(self, value):
        if value <= 0:
            raise serializers.ValidationError("Planned quantity must be greater than 0.")
        return value

    def validate_due_date(self, value):
        if self.instance is None and value < now().date():
            raise serializers.ValidationError("Due date cannot be in the past.")
        return value

    def validate(self, attrs):
        qty = attrs.get("qty_planned", getattr(self.instance, "qty_planned", None))
        if self.instance is not None and qty is not None:
            done = self.instance.unit_events.count()
            if qty < done:
                raise serializers.ValidationError(
                    {"qty_planned": f"Cannot drop below {done} units already produced."}
                )
        return attrs
