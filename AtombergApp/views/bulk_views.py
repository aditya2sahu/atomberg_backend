from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from AtombergApp.serializers import (
    DowntimeEventSerializer,
    DowntimeReasonSerializer,
    MachineSerializer,
    OrderSerializer,
    SKUSerializer,
    UnitEventSerializer,
)

# The resource name in the URL picks the serializer; everything else is shared.
RESOURCES = {
    "machines": MachineSerializer,
    "skus": SKUSerializer,
    "downtime-reasons": DowntimeReasonSerializer,
    "orders": OrderSerializer,
    "downtime-events": DowntimeEventSerializer,
    "unit-events": UnitEventSerializer,
}

# One request shouldn't be able to hold a write transaction open indefinitely.
MAX_BATCH = 5000


@api_view(["POST"])
def bulk_create(request, resource):
    serializer_class = RESOURCES.get(resource)
    if serializer_class is None:
        return Response(
            {"detail": f"Unknown resource '{resource}'.", "valid": sorted(RESOURCES)},
            status=status.HTTP_404_NOT_FOUND,
        )

    rows = request.data
    if not isinstance(rows, list):
        return Response({"detail": "Expected a JSON list of objects."},
                        status=status.HTTP_400_BAD_REQUEST)
    if not rows:
        return Response({"detail": "Empty list."}, status=status.HTTP_400_BAD_REQUEST)
    if len(rows) > MAX_BATCH:
        return Response({"detail": f"At most {MAX_BATCH} rows per request, got {len(rows)}."},
                        status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

    # many=True reports errors keyed by row index — only the rows that failed —
    # so a caller sending 5000 rows learns exactly which ones were rejected.
    serializer = serializer_class(data=rows, many=True)
    if not serializer.is_valid():
        return Response({"errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    model = serializer_class.Meta.model
    objects = [model(**attrs) for attrs in serializer.validated_data]
    try:
        with transaction.atomic():
            model.objects.bulk_create(objects, batch_size=1000)
    except IntegrityError as exc:
        # Duplicate primary key or serial_no — the whole batch rolls back.
        return Response({"detail": str(exc).splitlines()[0]},
                        status=status.HTTP_400_BAD_REQUEST)

    return Response({"resource": resource, "created": len(objects)},
                    status=status.HTTP_201_CREATED)
