import logging

from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores.models import Inventory, Store

from .models import Order, OrderItem
from .serializers import OrderCreateSerializer, OrderDetailSerializer, OrderListSerializer
from .tasks import send_order_confirmation

logger = logging.getLogger(__name__)


class OrderCreateView(APIView):
    """
    POST /orders/

    Body:
        {
            "store_id": 1,
            "items": [{"product_id": 10, "quantity_requested": 3}, ...]
        }

    Behaviour (all inside one transaction.atomic() block):
      1. Lock the relevant Inventory rows for this store with
         select_for_update(), in a fixed product_id order, so two
         concurrent orders competing for the same stock can't both read
         a stale quantity and both "succeed" (classic lost-update race).
         The fixed lock order also avoids deadlocking against another
         request that ordered the same products in reverse.
      2. If any requested product doesn't have enough stock (including
         products with no Inventory row at all, treated as 0), the whole
         order is rejected — no partial fulfillment, no partial deduction.
      3. Otherwise every line item's quantity is deducted and the order is
         confirmed.
      4. OrderItem rows are written for the *requested* quantities either
         way, so a REJECTED order still records what was asked for.
    """

    @extend_schema(
        request=OrderCreateSerializer,
        responses={201: OrderDetailSerializer},
        summary="Create an order (confirms or rejects based on stock)",
        description=(
            "Validates stock for every item atomically. If any item is short, "
            "the whole order is REJECTED and no stock is deducted. Otherwise "
            "all items are deducted and the order is CONFIRMED."
        ),
    )
    def post(self, request):
        input_serializer = OrderCreateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        store = input_serializer.validated_data["store"]
        items_data = input_serializer.validated_data["items"]

        # Aggregate requested quantity per product in case the same
        # product_id appears more than once in the payload — stock must be
        # checked against total demand, not against each line in isolation.
        demand = {}
        for item in items_data:
            product = item["product"]
            demand[product.id] = demand.get(product.id, 0) + item["quantity_requested"]

        with transaction.atomic():
            order = Order.objects.create(store=store, status=Order.Status.PENDING)

            OrderItem.objects.bulk_create(
                OrderItem(order=order, product=item["product"], quantity_requested=item["quantity_requested"])
                for item in items_data
            )

            locked_inventory = {
                inv.product_id: inv
                for inv in Inventory.objects.select_for_update()
                .filter(store=store, product_id__in=demand.keys())
                .order_by("product_id")
            }

            shortfalls = []
            for product_id, requested_qty in demand.items():
                inv = locked_inventory.get(product_id)
                available = inv.quantity if inv else 0
                if available < requested_qty:
                    shortfalls.append(
                        {"product_id": product_id, "requested": requested_qty, "available": available}
                    )

            if shortfalls:
                order.status = Order.Status.REJECTED
            else:
                for product_id, requested_qty in demand.items():
                    inv = locked_inventory[product_id]
                    inv.quantity -= requested_qty
                    inv.save(update_fields=["quantity"])
                order.status = Order.Status.CONFIRMED

            order.save(update_fields=["status"])

        if order.status == Order.Status.CONFIRMED:
            # Fired only after the transaction commits (see tasks.py /
            # transaction.on_commit note below in README) so we never queue
            # a confirmation for an order that ultimately rolled back.
            transaction.on_commit(lambda: send_order_confirmation.delay(order.id))
        else:
            logger.info("Order %s rejected for store %s: %s", order.id, store.id, shortfalls)

        response_data = OrderDetailSerializer(order).data
        if shortfalls:
            response_data["shortfalls"] = shortfalls
        return Response(response_data, status=status.HTTP_201_CREATED)


@extend_schema(summary="List a store's orders (newest first, with total item counts)")
class StoreOrderListView(ListAPIView):
    """
    GET /stores/<store_id>/orders/

    Newest first. total_items is summed via annotation (Coalesce guards
    against a null Sum if an order somehow has zero items) so this is a
    single query regardless of how many orders/items exist.
    """

    serializer_class = OrderListSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Order.objects.none()
        get_object_or_404(Store, pk=self.kwargs["store_id"])
        return (
            Order.objects.filter(store_id=self.kwargs["store_id"])
            .annotate(total_items=Coalesce(Sum("items__quantity_requested"), 0))
            .order_by("-created_at")
        )
