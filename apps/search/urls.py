from django.urls import path

from .views import ProductAutocompleteView, ProductSearchView

urlpatterns = [
    path("products/", ProductSearchView.as_view(), name="product-search"),
    path("suggest/", ProductAutocompleteView.as_view(), name="product-suggest"),
]
