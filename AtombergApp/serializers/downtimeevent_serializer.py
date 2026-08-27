from rest_framework import serializers

from AtombergApp.models import DowntimeEvent, DowntimeReason, Machine


class DowntimeEventSerializer(serializers.ModelSerializer):
    machine_code = serializers.SlugRelatedField(
        source="machine", slug_field="machine_code", queryset=Machine.objects.all()
    )
    reason_code = serializers.SlugRelatedField(
        source="reason", slug_field="reason_code", queryset=DowntimeReason.objects.all()
    )

    class Meta:
        model = DowntimeEvent
        fields = ["downtime_id", "machine_code", "started_at", "ended_at", "reason_code", "note"]

    def validate(self, attrs):
        started_at = attrs.get("started_at", getattr(self.instance, "started_at", None))
        ended_at = attrs.get("ended_at", getattr(self.instance, "ended_at", None))
        if ended_at is not None and started_at is not None and ended_at < started_at:
            raise serializers.ValidationError(
                {"ended_at": "End time must be greater than or equal to start time."}
            )
        return attrs
