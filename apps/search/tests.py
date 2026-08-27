from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.products.models import Category, Product
from apps.stores.models import Inventory, Store


class ProductSearchTests(TestCase):
    def setUp(self):
        cache.clear()
        self.electronics = Category.objects.create(name="Electronics")
        self.books = Category.objects.create(name="Books")
        self.laptop = Product.objects.create(
            title="Gaming Laptop", description="High performance", price=Decimal("1200.00"),
            category=self.electronics,
        )
        self.novel = Product.objects.create(
            title="Mystery Novel", description="A thrilling laptop-themed heist story",
            price=Decimal("15.00"), category=self.books,
        )
        self.store = Store.objects.create(name="Test Store", location="Test City")
        Inventory.objects.create(store=self.store, product=self.laptop, quantity=0)
        Inventory.objects.create(store=self.store, product=self.novel, quantity=50)
        self.url = reverse("product-search")

    def test_keyword_matches_title_and_description(self):
        response = self.client.get(self.url, {"q": "laptop"})
        self.assertEqual(response.status_code, 200)
        titles = {r["title"] for r in response.data["results"]}
        # Matches both: title match (Gaming Laptop) and description match (Mystery Novel).
        self.assertEqual(titles, {"Gaming Laptop", "Mystery Novel"})

    def test_price_range_filter(self):
        response = self.client.get(self.url, {"price_min": "100", "price_max": "2000"})
        titles = {r["title"] for r in response.data["results"]}
        self.assertEqual(titles, {"Gaming Laptop"})

    def test_store_id_includes_store_quantity(self):
        response = self.client.get(self.url, {"q": "laptop", "store_id": self.store.id})
        by_title = {r["title"]: r["store_quantity"] for r in response.data["results"]}
        self.assertEqual(by_title["Gaming Laptop"], 0)
        self.assertEqual(by_title["Mystery Novel"], 50)

    def test_in_stock_filter_excludes_zero_quantity(self):
        response = self.client.get(self.url, {"store_id": self.store.id, "in_stock": "true"})
        titles = {r["title"] for r in response.data["results"]}
        self.assertNotIn("Gaming Laptop", titles)  # quantity 0 in this store
        self.assertIn("Mystery Novel", titles)

    def test_search_results_are_cached(self):
        with self.assertNumQueries(0):
            # First call populates the cache — do it outside assertNumQueries.
            pass
        self.client.get(self.url, {"q": "laptop"})
        # Second identical request should be served from cache: no DB hits.
        with self.assertNumQueries(0):
            self.client.get(self.url, {"q": "laptop"})

    def test_cache_invalidated_on_product_change(self):
        self.client.get(self.url, {"q": "laptop"})
        Product.objects.create(
            title="Laptop Stand", description="Aluminum", price=Decimal("30.00"), category=self.electronics
        )
        response = self.client.get(self.url, {"q": "laptop"})
        titles = {r["title"] for r in response.data["results"]}
        self.assertIn("Laptop Stand", titles)


class AutocompleteTests(TestCase):
    def setUp(self):
        cache.clear()
        category = Category.objects.create(name="Electronics")
        Product.objects.create(title="Blue Widget", price=Decimal("1.00"), category=category)
        Product.objects.create(title="Widget Blue Deluxe", price=Decimal("2.00"), category=category)
        self.url = reverse("product-suggest")

    def test_rejects_queries_under_three_chars(self):
        response = self.client.get(self.url, {"q": "wi"})
        self.assertEqual(response.status_code, 400)

    def test_prefix_matches_ranked_before_general_matches(self):
        response = self.client.get(self.url, {"q": "wid"})
        self.assertEqual(response.status_code, 200)
        results = response.data["results"]
        self.assertEqual(results[0], "Widget Blue Deluxe")  # prefix match
        self.assertIn("Blue Widget", results)  # substring match, ranked after

    def test_results_capped_at_ten(self):
        category = Category.objects.get(name="Electronics")
        for i in range(15):
            Product.objects.create(title=f"Zzz Item {i}", price=Decimal("1.00"), category=category)
        response = self.client.get(self.url, {"q": "zzz"})
        self.assertLessEqual(len(response.data["results"]), 10)
