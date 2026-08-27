import random

from django.core.management.base import BaseCommand
from django.db import transaction
from faker import Faker

from apps.products.models import Category, Product
from apps.stores.models import Inventory, Store

fake = Faker()

CATEGORY_NAMES = [
    "Electronics", "Home & Kitchen", "Books", "Sports & Outdoors", "Toys & Games",
    "Beauty & Personal Care", "Grocery", "Automotive", "Office Supplies", "Health & Wellness",
    "Clothing", "Footwear", "Pet Supplies", "Garden & Outdoor",
]


class Command(BaseCommand):
    help = "Seeds the database with demo categories, products, stores, and per-store inventory."

    def add_arguments(self, parser):
        parser.add_argument("--categories", type=int, default=12)
        parser.add_argument("--products", type=int, default=1200)
        parser.add_argument("--stores", type=int, default=25)
        parser.add_argument(
            "--min-inventory-per-store", type=int, default=300,
            help="Minimum number of distinct products stocked by each store.",
        )
        parser.add_argument("--flush", action="store_true", help="Delete existing seeded data first.")

    def handle(self, *args, **options):
        n_categories = options["categories"]
        n_products = options["products"]
        n_stores = options["stores"]
        min_inventory = options["min_inventory_per_store"]

        if options["flush"]:
            self.stdout.write("Flushing existing data...")
            Inventory.objects.all().delete()
            Product.objects.all().delete()
            Category.objects.all().delete()
            Store.objects.all().delete()

        with transaction.atomic():
            categories = self._seed_categories(n_categories)
            self.stdout.write(self.style.SUCCESS(f"Categories: {len(categories)}"))

            products = self._seed_products(n_products, categories)
            self.stdout.write(self.style.SUCCESS(f"Products: {len(products)}"))

            stores = self._seed_stores(n_stores)
            self.stdout.write(self.style.SUCCESS(f"Stores: {len(stores)}"))

            self._seed_inventory(stores, products, min_inventory)
            self.stdout.write(self.style.SUCCESS("Inventory seeded for every store."))

        self.stdout.write(self.style.SUCCESS("Done."))

    def _seed_categories(self, n):
        names = list(dict.fromkeys(CATEGORY_NAMES))  # unique, preserve order
        while len(names) < n:
            names.append(fake.unique.word().title() + " Goods")
        names = names[:n]
        existing = {c.name: c for c in Category.objects.filter(name__in=names)}
        to_create = [Category(name=name) for name in names if name not in existing]
        Category.objects.bulk_create(to_create)
        return list(Category.objects.filter(name__in=names))

    def _seed_products(self, n, categories):
        batch = []
        for _ in range(n):
            batch.append(
                Product(
                    title=fake.unique.catch_phrase(),
                    description=fake.text(max_nb_chars=200),
                    price=round(random.uniform(4.99, 999.99), 2),
                    category=random.choice(categories),
                )
            )
        Product.objects.bulk_create(batch, batch_size=500)
        return list(Product.objects.all())

    def _seed_stores(self, n):
        batch = [
            Store(name=f"{fake.company()} #{i+1}", location=f"{fake.city()}, {fake.state_abbr()}")
            for i in range(n)
        ]
        Store.objects.bulk_create(batch)
        return list(Store.objects.all())

    def _seed_inventory(self, stores, products, min_inventory):
        for store in stores:
            sample_size = min(len(products), max(min_inventory, random.randint(min_inventory, min_inventory + 200)))
            chosen = random.sample(products, sample_size)
            rows = [
                Inventory(store=store, product=p, quantity=random.randint(0, 500))
                for p in chosen
            ]
            Inventory.objects.bulk_create(rows, batch_size=500, ignore_conflicts=True)
