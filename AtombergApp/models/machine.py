from django.db import models


class Machine(models.Model):
    machine_id = models.BigAutoField(primary_key=True)
    machine_code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    target_units_per_hour = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = "machines"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(target_units_per_hour__gt=0),
                name="machine_target_positive",
            ),
        ]

    def __str__(self):
        return f"{self.machine_code} - {self.name}"
