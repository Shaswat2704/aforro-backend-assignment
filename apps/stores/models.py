from django.db import models

from apps.products.models import Product


class Store(models.Model):
    name = models.CharField(max_length=255)
    location = models.CharField(max_length=255)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.location})"


class Inventory(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="inventory_items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="inventory_items")
    quantity = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name_plural = "inventory"
        constraints = [
            # "A store must have at most one inventory row per product."
            models.UniqueConstraint(fields=["store", "product"], name="unique_store_product")
        ]
        indexes = [
            models.Index(fields=["store", "product"]),
        ]

    def __str__(self):
        return f"{self.store} / {self.product} = {self.quantity}"
