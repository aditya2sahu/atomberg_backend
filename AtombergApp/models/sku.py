from django.db import models


class SKU(models.Model):
    sku_id = models.BigAutoField(primary_key=True)
    sku_code = models.CharField(max_length=50, unique=True)
    description = models.TextField()
    std_cycle_time_sec = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = "skus"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(std_cycle_time_sec__gt=0),
                name="sku_cycle_time_positive",
            ),
        ]

    def __str__(self):
        return self.sku_code
