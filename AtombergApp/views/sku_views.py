from rest_framework.response import Response
from rest_framework.decorators import api_view

from AtombergApp.models import SKU
from AtombergApp.serializers import SKUSerializer


@api_view(["GET"])
def sku_list(request):
    skus = SKU.objects.all()
    serializer = SKUSerializer( skus, many=True )
    return Response(serializer.data)