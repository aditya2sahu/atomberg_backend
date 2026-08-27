from rest_framework.serializers import ModelSerializer
from rest_framework import serializers

from AtombergApp.models import Machine, SKU


class SKUSerializer(ModelSerializer):
    class Meta:
        model = SKU
        fields = [
            "sku_code", "description", "std_cycle_time_sec",
        ]

    def validate_std_cycle_time_sec(self, value):
        if value <= 0:
            raise serializers.ValidationError( "Standard cycle time must be greater than 0." )
        return value