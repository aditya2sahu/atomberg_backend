from rest_framework import serializers
from AtombergApp.models import DowntimeReason


class DowntimeReasonSerializer(serializers.ModelSerializer):
    class Meta:
        model = DowntimeReason
        fields = [
            "reason_code", "description", "category",
        ]