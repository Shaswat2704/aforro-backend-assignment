from rest_framework import serializers

from .models import Inventory, Store


class InventoryListSerializer(serializers.ModelSerializer):
    """
    Flattened, read-only view of an inventory row for GET
    /stores/<store_id>/inventory/. Uses source= to pull through the related
    product/category fields the endpoint needs to expose, so the queryset
    can select_related() them in one hop instead of the serializer
    triggering extra lookups per row.
    """

    product_id = serializers.IntegerField(source="product.id")
    product_title = serializers.CharField(source="product.title")
    price = serializers.DecimalField(source="product.price", max_digits=10, decimal_places=2)
    category_name = serializers.CharField(source="product.category.name")

    class Meta:
        model = Inventory
        fields = ["product_id", "product_title", "price", "category_name", "quantity"]


class StoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Store
        fields = ["id", "name", "location"]
