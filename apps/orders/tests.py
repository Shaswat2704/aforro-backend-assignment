from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.orders.models import Order
from apps.products.models import Category, Product
from apps.stores.models import Inventory, Store


class OrderCreationTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Widgets")
        self.store = Store.objects.create(name="Test Store", location="Test City")
        self.product_a = Product.objects.create(
            title="Widget A", price=Decimal("10.00"), category=self.category
        )
        self.product_b = Product.objects.create(
            title="Widget B", price=Decimal("20.00"), category=self.category
        )
        Inventory.objects.create(store=self.store, product=self.product_a, quantity=10)
        Inventory.objects.create(store=self.store, product=self.product_b, quantity=5)
        self.url = reverse("order-create")

    def test_order_confirmed_when_stock_sufficient(self):
        payload = {
            "store_id": self.store.id,
            "items": [{"product_id": self.product_a.id, "quantity_requested": 4}],
        }
        response = self.client.post(self.url, payload, content_type="application/json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "CONFIRMED")

        self.product_a.refresh_from_db()
        inv = Inventory.objects.get(store=self.store, product=self.product_a)
        self.assertEqual(inv.quantity, 6)  # 10 - 4

    def test_order_rejected_when_stock_insufficient_and_no_deduction_occurs(self):
        payload = {
            "store_id": self.store.id,
            "items": [{"product_id": self.product_b.id, "quantity_requested": 999}],
        }
        response = self.client.post(self.url, payload, content_type="application/json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "REJECTED")
        self.assertIn("shortfalls", response.data)

        inv = Inventory.objects.get(store=self.store, product=self.product_b)
        self.assertEqual(inv.quantity, 5)  # untouched

    def test_multi_item_order_rejected_entirely_if_any_item_short(self):
        """One insufficient item must reject the WHOLE order — no partial fulfillment."""
        payload = {
            "store_id": self.store.id,
            "items": [
                {"product_id": self.product_a.id, "quantity_requested": 2},   # sufficient
                {"product_id": self.product_b.id, "quantity_requested": 999},  # insufficient
            ],
        }
        response = self.client.post(self.url, payload, content_type="application/json")

        self.assertEqual(response.data["status"], "REJECTED")
        inv_a = Inventory.objects.get(store=self.store, product=self.product_a)
        inv_b = Inventory.objects.get(store=self.store, product=self.product_b)
        # Product A had enough stock but must NOT be deducted since the order as a whole failed.
        self.assertEqual(inv_a.quantity, 10)
        self.assertEqual(inv_b.quantity, 5)

    def test_order_rejected_when_product_has_no_inventory_row_in_store(self):
        other_product = Product.objects.create(
            title="Widget C", price=Decimal("5.00"), category=self.category
        )
        payload = {
            "store_id": self.store.id,
            "items": [{"product_id": other_product.id, "quantity_requested": 1}],
        }
        response = self.client.post(self.url, payload, content_type="application/json")

        self.assertEqual(response.data["status"], "REJECTED")
        self.assertEqual(response.data["shortfalls"][0]["available"], 0)

    def test_duplicate_product_lines_are_aggregated_for_stock_check(self):
        """Two line items for the same product must be summed before checking stock."""
        payload = {
            "store_id": self.store.id,
            "items": [
                {"product_id": self.product_a.id, "quantity_requested": 6},
                {"product_id": self.product_a.id, "quantity_requested": 6},  # 12 total > 10 available
            ],
        }
        response = self.client.post(self.url, payload, content_type="application/json")

        self.assertEqual(response.data["status"], "REJECTED")
        inv = Inventory.objects.get(store=self.store, product=self.product_a)
        self.assertEqual(inv.quantity, 10)  # untouched

    def test_empty_items_list_is_rejected_with_validation_error(self):
        payload = {"store_id": self.store.id, "items": []}
        response = self.client.post(self.url, payload, content_type="application/json")
        self.assertEqual(response.status_code, 400)


class OrderListingTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Widgets")
        self.store = Store.objects.create(name="Test Store", location="Test City")
        self.product = Product.objects.create(
            title="Widget A", price=Decimal("10.00"), category=self.category
        )
        Inventory.objects.create(store=self.store, product=self.product, quantity=100)

    def test_orders_listed_newest_first_with_total_items(self):
        create_url = reverse("order-create")
        for qty in (1, 2, 3):
            self.client.post(
                create_url,
                {"store_id": self.store.id, "items": [{"product_id": self.product.id, "quantity_requested": qty}]},
                content_type="application/json",
            )

        list_url = reverse("store-order-list", kwargs={"store_id": self.store.id})
        response = self.client.get(list_url)

        self.assertEqual(response.status_code, 200)
        results = response.data["results"]
        self.assertEqual(len(results), 3)
        # Newest first: the last created order (qty=3) should be first.
        self.assertEqual(results[0]["total_items"], 3)
        self.assertEqual(results[-1]["total_items"], 1)

    def test_order_listing_query_count_is_constant_regardless_of_order_count(self):
        """Guards against N+1 queries on the total_items aggregation."""
        create_url = reverse("order-create")
        for qty in range(1, 6):
            self.client.post(
                create_url,
                {"store_id": self.store.id, "items": [{"product_id": self.product.id, "quantity_requested": qty}]},
                content_type="application/json",
            )

        list_url = reverse("store-order-list", kwargs={"store_id": self.store.id})
        with self.assertNumQueries(3):  # store existence check + paginated count + paginated select
            self.client.get(list_url)
