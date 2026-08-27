from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.orders.urls")),
    path("", include("apps.stores.urls")),
    path("api/search/", include("apps.search.urls")),
    # OpenAPI schema + interactive docs. Swagger UI is the one the
    # assignment explicitly asks for ("testable through the Swagger UI");
    # Redoc is included too since it's effectively free with drf-spectacular
    # and useful as read-only reference docs.
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
