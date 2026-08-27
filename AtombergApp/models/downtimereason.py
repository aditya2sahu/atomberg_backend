from django.db import models


class DowntimeReason(models.Model):
    class Category(models.TextChoices):
        PLANNED = "planned", "Planned"
        UNPLANNED = "unplanned", "Unplanned"

    reason_id = models.BigAutoField(primary_key=True)
    reason_code = models.CharField(max_length=50, unique=True)
    description = models.TextField()
    category = models.CharField(max_length=20, choices=Category.choices)

    class Meta:
        db_table = "downtime_reasons"

    def __str__(self):
        return self.reason_code
