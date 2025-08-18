# admin/views.py
from datetime import datetime, timezone
from typing import Any, Callable, Dict
from sqladmin import ModelView
from models import Payment, Merchant, WebhookOutbox

def _fmt_epoch(value: int | None) -> str:
    if value is None:
        return "-"
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return str(value)

class PaymentAdmin(ModelView, model=Payment):
    name = "Payment"
    name_plural = "Payments"

    column_list = [
        Payment.payment_id,
        Payment.amount,
        Payment.currency,
        Payment.status,
        Payment.idempotency_key,
        Payment.created_at,
        Payment.merchant_id,
    ]
    column_sortable_list = [Payment.created_at, Payment.amount, Payment.status]
    column_searchable_list = [Payment.idempotency_key, Payment.currency, Payment.status]
    column_filters = [Payment.status, Payment.currency, Payment.merchant_id]
    can_create = False
    can_delete = False

    column_formatters: Dict[str, Callable[[Any, Any], Any]] = {
        "created_at": lambda m, a: _fmt_epoch(m.created_at),
    }

    form_choices = {
        "status": [
            ("new", "new"),
            ("processing", "processing"),
            ("approved", "approved"),
            ("declined", "declined"),
            ("failed", "failed"),
        ]
    }

class MerchantAdmin(ModelView, model=Merchant):
    name = "Merchant"
    name_plural = "Merchants"
    column_list = [Merchant.id, Merchant.webhook_url, Merchant.api_secret]
    column_searchable_list = [Merchant.webhook_url]
    column_sortable_list = [Merchant.webhook_url]
    can_delete = False

class WebhookOutboxAdmin(ModelView, model=WebhookOutbox):
    name = "Webhook outbox"
    name_plural = "Webhook outbox"
    column_list = [WebhookOutbox.payment_id, WebhookOutbox.delivered]
    column_filters = [WebhookOutbox.delivered]
    can_create = False
    can_delete = True
