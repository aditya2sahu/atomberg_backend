from rest_framework import serializers

from AtombergApp.models import Machine, Order, UnitEvent


class UnitEventSerializer(serializers.ModelSerializer):
    # Parents are addressed by their business code; the surrogate id stays internal.
    machine_code = serializers.SlugRelatedField(
        source="machine", slug_field="machine_code", queryset=Machine.objects.all()
    )
    order_no = serializers.SlugRelatedField(
        source="order", slug_field="order_no", queryset=Order.objects.all()
    )

    class Meta:
        model = UnitEvent
        fields = ["event_id", "machine_code", "order_no", "completed_at", "serial_no"]
