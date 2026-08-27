from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.orders.urls")),
    path("", include("apps.stores.urls")),
    path("api/search/", include("apps.search.urls")),
]
