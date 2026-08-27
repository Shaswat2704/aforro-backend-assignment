from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.products.models import Category, Product
from apps.stores.models import Inventory, Store


class InventoryListingTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Widgets")
        self.store = Store.objects.create(name="Test Store", location="Test City")
        self.product_z = Product.objects.create(title="Zebra Widget", price=Decimal("9.99"), category=self.category)
        self.product_a = Product.objects.create(title="Apple Widget", price=Decimal("4.99"), category=self.category)
        Inventory.objects.create(store=self.store, product=self.product_z, quantity=10)
        Inventory.objects.create(store=self.store, product=self.product_a, quantity=20)

    def test_inventory_sorted_alphabetically_by_title(self):
        url = reverse("store-inventory-list", kwargs={"store_id": self.store.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        titles = [row["product_title"] for row in response.data["results"]]
        self.assertEqual(titles, ["Apple Widget", "Zebra Widget"])

    def test_inventory_includes_price_and_category(self):
        url = reverse("store-inventory-list", kwargs={"store_id": self.store.id})
        response = self.client.get(url)
        row = response.data["results"][0]
        self.assertIn("price", row)
        self.assertIn("category_name", row)
        self.assertEqual(row["category_name"], "Widgets")

    def test_unknown_store_returns_404(self):
        url = reverse("store-inventory-list", kwargs={"store_id":99999})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
