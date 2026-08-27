from rest_framework import serializers

from apps.products.models import Product
from apps.stores.models import Store

from .models import Order, OrderItem


class OrderItemInputSerializer(serializers.Serializer):
    product_id = serializers.PrimaryKeyRelatedField(
        source="product", queryset=Product.objects.all()
    )
    quantity_requested = serializers.IntegerField(min_value=1)


class OrderCreateSerializer(serializers.Serializer):
    """
    Validates the POST /orders/ payload shape. Deliberately a plain
    Serializer (not a ModelSerializer) because order creation is a
    multi-step domain operation — stock check, conditional deduction,
    status assignment — not a straight model insert. The view owns that
    logic inside a single transaction; this only validates input shape.
    """

    store_id = serializers.PrimaryKeyRelatedField(source="store", queryset=Store.objects.all())
    items = OrderItemInputSerializer(many=True)

    def validate_items(self, items):
        if not items:
            raise serializers.ValidationError("At least one item is required.")
        return items


class OrderItemOutputSerializer(serializers.ModelSerializer):
    product_id = serializers.IntegerField(source="product.id")
    title = serializers.CharField(source="product.title")

    class Meta:
        model = OrderItem
        fields = ["product_id", "title", "quantity_requested"]


class OrderDetailSerializer(serializers.ModelSerializer):
    """Full order representation returned by POST /orders/."""

    items = OrderItemOutputSerializer(many=True, read_only=True)
    store_id = serializers.IntegerField(source="store.id", read_only=True)

    class Meta:
        model = Order
        fields = ["id", "store_id", "status", "created_at", "items"]


class OrderListSerializer(serializers.ModelSerializer):
    """
    Row shape for GET /stores/<store_id>/orders/. total_items comes from an
    annotation on the queryset (see views.StoreOrderListView) so it costs
    zero extra queries per row.
    """

    total_items = serializers.IntegerField(read_only=True)

    class Meta:
        model = Order
        fields = ["id", "status", "created_at", "total_items"]
