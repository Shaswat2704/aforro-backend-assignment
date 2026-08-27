from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.products.models import Category, Product
from apps.stores.models import Inventory

from .cache import invalidate_search_cache, invalidate_suggest_cache


@receiver([post_save, post_delete], sender=Product)
def on_product_change(sender, **kwargs):
    invalidate_search_cache()
    invalidate_suggest_cache()


@receiver([post_save, post_delete], sender=Category)
def on_category_change(sender, **kwargs):
    invalidate_search_cache()


@receiver([post_save, post_delete], sender=Inventory)
def on_inventory_change(sender, **kwargs):
    # Inventory changes affect in_stock filtering and per-store quantity,
    # not product titles, so autocomplete suggestions don't need clearing.
    invalidate_search_cache()
