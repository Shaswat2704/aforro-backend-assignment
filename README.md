# Aforro — Backend Developer Assignment (Round 2)

A Django + DRF backend implementing order processing, inventory management,
and product search/autocomplete, with Redis (caching **and** rate limiting)
and Celery (async tasks + a scheduled job), fully containerized.

Every endpoint, the seed command, and the full test suite were run against
real Postgres and Redis instances while building this — not just written
and assumed correct.

## Stack

- Django 6.1 / Django REST Framework
- PostgreSQL 16
- Redis 7 (cache backend via `django-redis`, used for both search-result
  caching and autocomplete rate-limit counters)
- Celery 5 (Redis as broker + result backend), with Celery Beat for the
  scheduled job
- Docker Compose for orchestration

## Project layout

```
project/            settings, root urls, celery app bootstrap, wsgi/asgi
apps/
  products/          Category, Product models + seed_data management command
  stores/            Store, Inventory models + inventory listing endpoint
  orders/            Order, OrderItem models + order creation/listing + celery tasks
  search/            product search + autocomplete (no models — reads products/stores)
  common/            shared DRF exception handler
```

Cross-app FKs (orders → stores/products, stores → products) are normal in
Django and keep each app focused on one bounded concern rather than forcing
everything into a single models.py.

## Running with Docker (recommended)

```bash
cp .env.example .env        # already done in this submission; edit if needed
docker compose up --build
```

This starts, in order: `db` (Postgres) → `redis` → `web` (runs migrations,
then serves on :8000) → `celery_worker` → `celery_beat`. Healthchecks on
db/redis mean `web` won't start until both are actually accepting
connections, not just "container up".

Seed the database (run once, from another terminal):

```bash
docker compose exec web python manage.py seed_data
```

This creates 12 categories, 1,200 products, 25 stores, and inventory for
every store covering 300+ products each (defaults; all overridable — see
`--help`).

Create an admin user if you want to browse `/admin/`:

```bash
docker compose exec web python manage.py createsuperuser
```

## Running locally without Docker

Requires a local Postgres and Redis.

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

export DB_ENGINE=sqlite            # or configure POSTGRES_* env vars for real Postgres
export REDIS_URL=redis://localhost:6379/0

python manage.py migrate
python manage.py seed_data
python manage.py runserver

# in separate terminals:
celery -A project worker --loglevel=info
celery -A project beat --loglevel=info
```

## Sample API requests

**Create an order** (rejects atomically if any item is short on stock):

```bash
curl -X POST http://localhost:8000/orders/ \
  -H "Content-Type: application/json" \
  -d '{
        "store_id": 1,
        "items": [
          {"product_id": 42, "quantity_requested": 3},
          {"product_id": 7,  "quantity_requested": 1}
        ]
      }'
```

Response (confirmed):
```json
{"id": 12, "store_id": 1, "status": "CONFIRMED", "created_at": "...",
 "items": [{"product_id": 42, "title": "...", "quantity_requested": 3}, ...]}
```

Response (rejected — includes a `shortfalls` block for debugging, beyond
what the spec requires, but useful and cheap to add):
```json
{"id": 13, "store_id": 1, "status": "REJECTED", "created_at": "...",
 "items": [...],
 "shortfalls": [{"product_id": 7, "requested": 999, "available": 5}]}
```

**List a store's orders:**
```bash
curl http://localhost:8000/stores/1/orders/
```

**List a store's inventory** (alphabetical by product title):
```bash
curl http://localhost:8000/stores/1/inventory/
```

**Search products:**
```bash
curl "http://localhost:8000/api/search/products/?q=laptop&price_min=100&price_max=2000&store_id=1&in_stock=true&sort=price"
```

**Autocomplete:**
```bash
curl "http://localhost:8000/api/search/suggest/?q=lap"
```

## Design notes

### Order creation — consistency under concurrency
The whole operation runs inside `transaction.atomic()`. Before checking
stock, the relevant `Inventory` rows are locked with
`select_for_update()`, fetched in a fixed `product_id` order. This does
two things:
- Prevents the classic race where two simultaneous orders both read
  "5 in stock", both think they can fulfill a request for 4, and both
  deduct — overselling.
- Locking in a consistent order across all requests avoids deadlocks
  between two orders that touch the same products in different sequences.

If a product appears more than once in the request payload, quantities
are summed before the stock check — checking each line independently
would let `[{"qty": 6}, {"qty": 6}]` against 10 units of stock slip
through as two "sufficient" checks of 6 ≤ 10.

`OrderItem` rows are written for the requested quantities regardless of
outcome, so a REJECTED order still has a full audit trail of what was
asked for.

### Query efficiency
- Order listing: `annotate(total_items=Coalesce(Sum(...), 0))` — one
  query regardless of order count. Covered by a test that asserts a fixed
  query count as more orders are added.
- Inventory listing: `select_related("product", "product__category")` —
  one query for N rows instead of 1+N.
- Search: `select_related("category")`; store-scoped quantity uses a
  correlated `Subquery` (one extra join, not one query per row).

### Redis — both caching and rate limiting were implemented
The assignment asks for **one** of caching or rate limiting; both are
included since they're small in isolation and demonstrate the pattern
end-to-end:
- **Caching**: `GET /api/search/products/` responses (post-pagination)
  are cached for 60s, keyed by a hash of the sorted query string.
  Invalidated via Django signals on `Product`, `Category`, and
  `Inventory` writes (`apps/search/signals.py`) — so a newly-added
  product or a stock change is visible immediately, not after a TTL.
  `django-redis`'s `delete_pattern` is used for a surgical wildcard
  delete rather than flushing the whole cache.
- **Rate limiting**: `GET /api/search/suggest/` is throttled to
  20 requests/minute per authenticated user (or per IP for anonymous
  callers) via a custom DRF `SimpleRateThrottle` subclass, backed by a
  separate Redis-backed cache alias (`throttle`) so its counters never
  collide with or get cleared by search-cache invalidation.
- Autocomplete results are also cached briefly (30s) since users retype
  overlapping prefixes rapidly.

### Celery
Two tasks:
1. `send_order_confirmation` — fired via `transaction.on_commit(...)`
   after a successful `CONFIRMED` order, so a task is never queued for
   an order that ends up rolling back. Retries up to 3 times (stubbed —
   a real provider integration would raise on transient failures here).
2. `generate_daily_inventory_summary` — a periodic job registered in
   `CELERY_BEAT_SCHEDULE`, logging a low-stock summary per store. Run by
   `celery_beat`, executed by `celery_worker`.

In tests, `CELERY_TASK_ALWAYS_EAGER=true` runs tasks synchronously so the
suite doesn't need a live broker. Outside tests, `docker compose logs
celery_worker` shows tasks executing for real (verified locally with an
actual Redis-backed worker before delivering this).

### The `created_at` field on `Product`
Not in the original spec's model bullet list, but the search API asks for
a "newest" sort option, and there's no honest way to express "newest"
without a timestamp. Added `Product.created_at` (auto-set) rather than
faking recency off the auto-increment ID.

### "Total number of items" on order listing
Interpreted as the *sum of quantities* across an order's line items
(`Sum("items__quantity_requested")`), not the count of distinct line
items — this matches how "how many items did they order" is normally
understood. Noting the assumption here since the spec doesn't disambiguate.

## Testing

```bash
docker compose exec web python manage.py test
# or locally:
python manage.py test
```

20 tests across three apps, covering:
- Order confirmed when stock is sufficient, with exact deduction verified
- Order rejected when stock is insufficient, with **zero** deduction verified
- A multi-item order where only one item is short is rejected **in full**
  (no partial fulfillment) — including that the sufficient item is *not*
  deducted
- Duplicate product lines in one request are aggregated before the stock
  check
- A product with no `Inventory` row in the store is treated as 0 stock
- Order listing sort order + a fixed-query-count assertion (N+1 guard)
- Inventory listing alphabetical sort + 404 on unknown store
- Search: keyword matching across title/description, price range filter,
  store-scoped quantity, in-stock filter, cache hit (0 queries on repeat
  request) and cache invalidation on product change
- Autocomplete: minimum-length validation, prefix-before-substring
  ranking, 10-result cap

## Scalability considerations

- **Read-heavy endpoints** (search, autocomplete, inventory) are the ones
  most worth caching/indexing further under real load; `Product` has
  indexes on `title`, `price`, `created_at`, and `(category, price)` to
  keep filter+sort combinations off full table scans.
- **`icontains` search** is fine at the assignment's data volume but
  doesn't scale to millions of rows — the natural next step is Postgres
  full-text search (`SearchVector`/`SearchRank`, GIN-indexed) or an
  external index (OpenSearch/Elasticsearch) behind the same
  `ProductSearchView` interface, swapping the query-building internals
  without changing the API contract.
- **Inventory contention**: `select_for_update()` serializes writes to
  hot products in a single store. Fine at moderate order volume; if a
  specific store/product becomes a genuine hotspot, the standard next
  step is a queue-based sequential deduction (or moving to an
  optimistic-concurrency `F()`-expression update with a retry loop
  instead of row locks) to reduce lock contention.
- **Celery** currently runs one queue; splitting into priority queues
  (e.g., `orders` vs `reports`) would stop a burst of daily-summary jobs
  from delaying time-sensitive order confirmations.
- **Horizontal scaling**: `web` and `celery_worker` are both stateless
  and can be scaled with `docker compose up --scale web=3
  --scale celery_worker=3`; session/cache state already lives in Redis,
  not in-process, so this requires no code changes.
