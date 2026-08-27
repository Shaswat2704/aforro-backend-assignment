import hashlib

from django.core.cache import cache

SEARCH_CACHE_PREFIX = "search"
SUGGEST_CACHE_PREFIX = "suggest"
SEARCH_CACHE_TTL = 60  # seconds
SUGGEST_CACHE_TTL = 30  # seconds


def build_search_cache_key(query_params):
    """
    Deterministic cache key for a product-search request: sort the query
    params so ?a=1&b=2 and ?b=2&a=1 hit the same cache entry, then hash
    to keep the key short and free of characters Redis dislikes.
    """
    normalized = "&".join(f"{k}={v}" for k, v in sorted(query_params.items()))
    digest = hashlib.md5(normalized.encode()).hexdigest()
    return f"{SEARCH_CACHE_PREFIX}:{digest}"


def invalidate_search_cache():
    """
    Called whenever Product, Category, or Inventory changes, since any of
    those can change search results or the in-stock/quantity fields the
    search API returns. django-redis supports glob deletes natively; for
    backends that don't (e.g. LocMemCache in some test configurations) we
    fall back to a full clear, which is safe (just less surgical).
    """
    try:
        cache.delete_pattern(f"{SEARCH_CACHE_PREFIX}:*")
    except AttributeError:
        cache.clear()


def invalidate_suggest_cache():
    try:
        cache.delete_pattern(f"{SUGGEST_CACHE_PREFIX}:*")
    except AttributeError:
        cache.clear()
