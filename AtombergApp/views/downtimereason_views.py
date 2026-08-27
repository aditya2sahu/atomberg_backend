from AtombergApp.models import DowntimeReason
from AtombergApp.serializers import DowntimeReasonSerializer

from rest_framework.response import Response
from rest_framework.decorators import api_view


@api_view(["GET"])
def downtime_reason_list(request):
    reasons = DowntimeReason.objects.all()
    serializer = DowntimeReasonSerializer( reasons, many=True )
    return Response(serializer.data)