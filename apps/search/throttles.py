from django.core.cache import caches
from rest_framework.throttling import SimpleRateThrottle


class AutocompleteRateThrottle(SimpleRateThrottle):
    """
    20 requests/minute per authenticated user, or per IP for anonymous
    callers — matches the assignment's "20 requests per minute per
    user/IP" spec. Uses a dedicated cache alias ("throttle") backed by the
    same Redis instance, so counters are isolated from the search-result
    cache and can be flushed independently.
    """

    scope = "autocomplete"
    cache = caches["throttle"]

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            ident = request.user.pk
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}
