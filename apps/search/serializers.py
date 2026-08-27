from rest_framework import serializers


class ProductSearchResultSerializer(serializers.Serializer):
    """
    Plain Serializer (not ModelSerializer): results come from an annotated
    queryset (relevance score, optional store_quantity) rather than a bare
    Product instance, so field-by-field control is simpler here.
    """

    id = serializers.IntegerField()
    title = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    price = serializers.DecimalField(max_digits=10, decimal_places=2)
    category_id = serializers.IntegerField(source="category.id")
    category_name = serializers.CharField(source="category.name")
    created_at = serializers.DateTimeField()
    store_quantity = serializers.SerializerMethodField()

    def get_store_quantity(self, obj):
        # Only present when the request included store_id — see
        # ProductSearchView.get_queryset(). Absent otherwise (None).
        return getattr(obj, "store_quantity", None)
