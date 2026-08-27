"""
URL configuration for Atomberg project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.urls import path
from AtombergApp.views import *

urlpatterns = [
    path("machines/", machine_list, name="machine-list"),
    path("skus/", sku_list, name="sku_code-list"),
    path("downtime-reasons/", downtime_reason_list, name="downtime-reason-list"),
    path("orders/", get_order_list_and_add, name="order-list"),
    path("orders/<str:order_no>/", get_and_update_order_detail, name="order-detail"),
    path("floor/status/", floor_status, name="floor-status"),
    path("unit-events/", unit_event_list, name="unit-event-list"),
    path("bulk/<str:resource>/", bulk_create, name="bulk-create"),
    path("analytics/summary/", analytics_summary, name="analytics-summary"),
]

