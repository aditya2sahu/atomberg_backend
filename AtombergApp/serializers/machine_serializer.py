from rest_framework.serializers import ModelSerializer
from rest_framework import serializers
from AtombergApp.models import Machine


class MachineSerializer(ModelSerializer):
    class Meta:
        model = Machine
        fields = [
            "machine_code", "name", "target_units_per_hour",
        ]

    def validate_target_units_per_hour(self, value):
        if value <= 0:
            raise serializers.ValidationError( "Target units per hour must be greater than 0." )
        return value