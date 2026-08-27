import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_order_confirmation(self, order_id):
    """
    Simulates sending an order-confirmation notification (email/SMS/push).
    Kept as a standalone task — triggered via .delay() from
    OrderCreateView — so the HTTP request returns immediately instead of
    blocking on a notification provider.

    A real integration (SES, SendGrid, Twilio...) would replace the log
    line below; the retry wiring is already in place for that: transient
    provider failures raise and get retried up to 3 times.
    """
    from apps.orders.models import Order  # local import avoids app-loading issues at task discovery time

    try:
        order = Order.objects.select_related("store").prefetch_related("items__product").get(pk=order_id)
    except Order.DoesNotExist:
        logger.warning("send_order_confirmation: order %s no longer exists", order_id)
        return

    item_lines = ", ".join(f"{i.product.title} x{i.quantity_requested}" for i in order.items.all())
    logger.info(
        "Order confirmation for order #%s (store=%s): %s",
        order.id, order.store.name, item_lines,
    )
    return {"order_id": order.id, "notified_at": timezone.now().isoformat()}


@shared_task
def generate_daily_inventory_summary():
    """
    Periodic task (see CELERY_BEAT_SCHEDULE in settings.py) that logs a
    per-store low-stock summary. In production this would email/Slack the
    ops team or write a report row to a table instead of just logging —
    logging keeps the assignment self-contained and easy to verify via
    `docker compose logs celery_beat celery_worker`.
    """
    from apps.stores.models import Inventory, Store

    LOW_STOCK_THRESHOLD = 10
    summary = []
    for store in Store.objects.all():
        low_stock_count = Inventory.objects.filter(
            store=store, quantity__lt=LOW_STOCK_THRESHOLD
        ).count()
        total_products = Inventory.objects.filter(store=store).count()
        summary.append(
            {"store_id": store.id, "store": store.name, "total_products": total_products, "low_stock": low_stock_count}
        )

    logger.info("Daily inventory summary (%d stores): %s", len(summary), summary)
    return summary
