from datetime import timedelta

from django.db.models import Count
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from rest_framework.pagination import PageNumberPagination

from AtombergApp.clock import now
from AtombergApp.models import Order
from AtombergApp.serializers import OrderSerializer


class OrderPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def _base_queryset():
    return (
        Order.objects.select_related("sku", "machine")
        .annotate(units_done=Count("unit_events"))
    )


def _projected_completion(order, units_done):
    """Rough finish time from the machine's target rate — no machine, no estimate."""
    if order.machine is None or units_done >= order.qty_planned:
        return None
    rate = float(order.machine.target_units_per_hour)
    if rate <= 0:
        return None
    return now() + timedelta(hours=(order.qty_planned - units_done) / rate)


@api_view(["GET", "POST"])
def get_order_list_and_add(request):
    if request.method == "GET":
        orders = _base_queryset()

        status_filter = request.GET.get("status")
        if status_filter:
            orders = orders.filter(status=status_filter)

        machine = request.GET.get("machine")
        if machine:
            orders = orders.filter(machine__machine_code=machine)

        priority = request.GET.get("priority")
        if priority:
            orders = orders.filter(priority=priority)

        due_from = request.GET.get("due_from")
        if due_from:
            orders = orders.filter(due_date__gte=due_from)

        due_to = request.GET.get("due_to")
        if due_to:
            orders = orders.filter(due_date__lte=due_to)

        search = request.GET.get("search")
        if search:
            orders = orders.filter(order_no__icontains=search)

        orders = orders.order_by(request.GET.get("ordering") or "due_date")

        paginator = OrderPagination()
        page = paginator.paginate_queryset(orders, request)
        serializer = OrderSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    serializer = OrderSerializer(data=request.data)
    if serializer.is_valid():
        order = serializer.save()
        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "PATCH"])
def get_and_update_order_detail(request, order_no):
    order = get_object_or_404(_base_queryset(), order_no=order_no)

    if request.method == "PATCH":
        serializer = OrderSerializer(order, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        order = serializer.save()
        order.units_done = order.unit_events.count()

    data = OrderSerializer(order).data
    data["projected_completion"] = _projected_completion(order, data["units_done"])
    return Response(data)
