from django.core.cache import cache
from django.db.models import Case, Exists, IntegerField, OuterRef, Q, Subquery, Value, When
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.products.models import Product
from apps.stores.models import Inventory

from .cache import SEARCH_CACHE_TTL, SUGGEST_CACHE_TTL, build_search_cache_key
from .serializers import ProductSearchResultSerializer
from .throttles import AutocompleteRateThrottle

SORT_OPTIONS = {
    "price": ["price"],
    "newest": ["-created_at"],
    "relevance": ["-relevance", "title"],
}


@extend_schema(
    summary="Search products by keyword with filters, sorting, and pagination",
    parameters=[
        OpenApiParameter("q", str, description="Keyword — matched against title, description, category name"),
        OpenApiParameter("category", str, description="Category id (e.g. '3') or name (e.g. 'Books')"),
        OpenApiParameter("price_min", str, description="Inclusive minimum price"),
        OpenApiParameter("price_max", str, description="Inclusive maximum price"),
        OpenApiParameter("store_id", int, description="If set, each result includes store_quantity for this store"),
        OpenApiParameter("in_stock", bool, description="If true, only products with quantity > 0"),
        OpenApiParameter(
            "sort", str, enum=["price", "newest", "relevance"],
            description="Defaults to 'relevance' when q is set, else 'newest'",
        ),
    ],
)
class ProductSearchView(ListAPIView):
    """
    GET /api/search/products/?q=&category=&price_min=&price_max=&store_id=&in_stock=&sort=

    - q: keyword, matched (icontains) against title, description, and
      category name.
    - category: category id, or category name (falls back to icontains).
    - price_min / price_max: inclusive DecimalField bounds.
    - store_id: when present, each result includes store_quantity — that
      product's inventory quantity in this specific store (0 if no row).
    - in_stock=true: only products with quantity > 0. Scoped to store_id
      if given, otherwise "in stock somewhere" (any store).
    - sort: price | newest | relevance (default: relevance when q is set,
      else newest).

    Whole response (post-pagination) is cached for SEARCH_CACHE_TTL
    seconds, keyed by the normalized query string. Cache is invalidated
    on any Product/Category/Inventory write — see search/signals.py.
    """

    serializer_class = ProductSearchResultSerializer

    def get_queryset(self):
        params = self.request.query_params
        q = params.get("q", "").strip()
        category = params.get("category", "").strip()
        price_min = params.get("price_min")
        price_max = params.get("price_max")
        store_id = params.get("store_id")
        in_stock = params.get("in_stock")
        sort = params.get("sort") or ("relevance" if q else "newest")

        if sort not in SORT_OPTIONS:
            raise ValidationError({"sort": f"Must be one of {list(SORT_OPTIONS)}."})

        qs = Product.objects.select_related("category")

        if q:
            qs = qs.filter(
                Q(title__icontains=q) | Q(description__icontains=q) | Q(category__name__icontains=q)
            )
            relevance = Case(
                When(title__iexact=q, then=Value(100)),
                When(title__icontains=q, then=Value(50)),
                When(category__name__icontains=q, then=Value(20)),
                When(description__icontains=q, then=Value(10)),
                default=Value(0),
                output_field=IntegerField(),
            )
            qs = qs.annotate(relevance=relevance)

        if category:
            qs = qs.filter(category_id=category) if category.isdigit() else qs.filter(
                category__name__icontains=category
            )

        if price_min:
            qs = qs.filter(price__gte=price_min)
        if price_max:
            qs = qs.filter(price__lte=price_max)

        if store_id:
            qs = qs.annotate(
                store_quantity=Subquery(
                    Inventory.objects.filter(store_id=store_id, product_id=OuterRef("pk")).values("quantity")[:1]
                )
            )
            if in_stock and in_stock.lower() in ("1", "true", "yes"):
                qs = qs.filter(
                    Exists(
                        Inventory.objects.filter(
                            store_id=store_id, product_id=OuterRef("pk"), quantity__gt=0
                        )
                    )
                )
        elif in_stock and in_stock.lower() in ("1", "true", "yes"):
            qs = qs.filter(
                Exists(Inventory.objects.filter(product_id=OuterRef("pk"), quantity__gt=0))
            )

        return qs.order_by(*SORT_OPTIONS[sort])

    def list(self, request, *args, **kwargs):
        cache_key = build_search_cache_key(request.query_params.dict())
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        response = super().list(request, *args, **kwargs)
        cache.set(cache_key, response.data, timeout=SEARCH_CACHE_TTL)
        return response


@extend_schema(
    summary="Autocomplete product titles (min 3 chars, prefix matches ranked first)",
    parameters=[OpenApiParameter("q", str, required=True, description="Search prefix, minimum 3 characters")],
    responses={200: {"type": "object", "properties": {"results": {"type": "array", "items": {"type": "string"}}}}},
)
class ProductAutocompleteView(APIView):
    """
    GET /api/search/suggest/?q=xxx

    Requires >= 3 characters. Prefix matches (title__istartswith) are
    returned before general substring matches, capped at 10 total.
    Rate-limited to 20 req/min per user-or-IP via AutocompleteRateThrottle.
    Results are cached briefly since autocomplete traffic is bursty and
    the same prefixes get hit repeatedly as a user types.
    """

    throttle_classes = [AutocompleteRateThrottle]

    def get(self, request):
        q = request.query_params.get("q", "").strip()
        if len(q) < 3:
            raise ValidationError({"q": "Query must be at least 3 characters."})

        cache_key = f"suggest:{q.lower()}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response({"results": cached})

        prefix_matches = list(
            Product.objects.filter(title__istartswith=q)
            .order_by("title")
            .values_list("title", flat=True)[:10]
        )

        results = list(dict.fromkeys(prefix_matches))  # dedupe, preserve order
        remaining = 10 - len(results)
        if remaining > 0:
            general_matches = (
                Product.objects.filter(title__icontains=q)
                .exclude(title__istartswith=q)
                .order_by("title")
                .values_list("title", flat=True)[: remaining * 2]
            )
            for title in general_matches:
                if title not in results:
                    results.append(title)
                if len(results) >= 10:
                    break

        cache.set(cache_key, results, timeout=SUGGEST_CACHE_TTL)
        return Response({"results": results})
