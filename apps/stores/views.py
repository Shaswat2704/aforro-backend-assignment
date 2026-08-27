from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.generics import ListAPIView

from .models import Inventory, Store
from .serializers import InventoryListSerializer


@extend_schema(summary="List a store's inventory (alphabetical by product title)")
class StoreInventoryListView(ListAPIView):
    """
    GET /stores/<store_id>/inventory/

    Returns every inventory row for a store: product title, price, category
    name, and quantity — sorted alphabetically by product title.

    select_related() pulls product + category in the same query as
    inventory, so listing N rows costs 1 query instead of 1 + N.
    """

    serializer_class = InventoryListSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            # drf-spectacular introspects get_queryset() without real URL
            # kwargs while building the schema; short-circuit cleanly here
            # instead of raising on the missing store_id.
            return Inventory.objects.none()
        get_object_or_404(Store, pk=self.kwargs["store_id"])
        return (
            Inventory.objects.filter(store_id=self.kwargs["store_id"])
            .select_related("product", "product__category")
            .order_by("product__title")
        )
