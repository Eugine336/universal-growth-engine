"""
Unit tests — Inbound transformers (Stripe, Paystack, Shopify, Generic).
"""

import pytest

from core.ingest.transformer import InboundTransformerRegistry
from core.ingest.sources.stripe import StripeTransformer
from core.ingest.sources.paystack import PaystackTransformer
from core.ingest.sources.shopify import ShopifyTransformer
from core.ingest.sources.generic import GenericTransformer


PLATFORM_ID = "plt_test_123"


class TestInboundTransformerRegistry:

    def test_register_and_get(self):
        reg = InboundTransformerRegistry()
        t = StripeTransformer()
        reg.register(t)
        assert reg.get("stripe") is t

    def test_get_unknown_returns_none(self):
        reg = InboundTransformerRegistry()
        assert reg.get("unknown") is None

    def test_list_sources(self):
        reg = InboundTransformerRegistry()
        reg.register(StripeTransformer())
        reg.register(PaystackTransformer())
        reg.register(GenericTransformer())
        sources = reg.list_sources()
        assert "generic" in sources
        assert "paystack" in sources
        assert "stripe" in sources


class TestStripeTransformer:

    def setup_method(self):
        self.t = StripeTransformer()

    def test_source_name(self):
        assert self.t.source_name == "stripe"

    def test_payment_intent_succeeded(self):
        payload = {
            "id": "evt_123",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_abc",
                    "customer": "cus_xyz",
                    "amount": 5000,
                    "currency": "usd",
                    "status": "succeeded",
                }
            },
        }
        events = self.t.transform(payload, PLATFORM_ID)
        assert len(events) == 1
        ev = events[0]
        assert ev["type"] == "PAYMENT_COMPLETED"
        assert ev["actor_id"] == "cus_xyz"
        assert ev["application_id"] == PLATFORM_ID
        assert ev["properties"]["amount"] == 5000
        assert ev["properties"]["currency"] == "usd"
        assert ev["source"] == "webhook"

    def test_payment_failed(self):
        payload = {
            "id": "evt_456",
            "type": "payment_intent.payment_failed",
            "data": {"object": {"id": "pi_def", "customer": "cus_abc"}},
        }
        events = self.t.transform(payload, PLATFORM_ID)
        assert events[0]["type"] == "PAYMENT_FAILED"

    def test_subscription_created(self):
        payload = {
            "id": "evt_789",
            "type": "customer.subscription.created",
            "data": {"object": {"id": "sub_1", "customer": "cus_sub"}},
        }
        events = self.t.transform(payload, PLATFORM_ID)
        assert events[0]["type"] == "SUBSCRIPTION_STARTED"

    def test_subscription_deleted(self):
        payload = {
            "id": "evt_del",
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": "sub_2", "customer": "cus_del"}},
        }
        events = self.t.transform(payload, PLATFORM_ID)
        assert events[0]["type"] == "SUBSCRIPTION_CANCELLED"

    def test_subscription_updated_maps_to_custom(self):
        payload = {
            "id": "evt_upd",
            "type": "customer.subscription.updated",
            "data": {"object": {"id": "sub_3", "customer": "cus_upd"}},
        }
        events = self.t.transform(payload, PLATFORM_ID)
        assert events[0]["type"] == "CUSTOM"
        assert events[0]["custom_type"] == "subscription_updated"

    def test_charge_refunded(self):
        payload = {
            "id": "evt_ref",
            "type": "charge.refunded",
            "data": {"object": {"id": "ch_1", "customer": "cus_ref", "amount": 2000}},
        }
        events = self.t.transform(payload, PLATFORM_ID)
        assert events[0]["type"] == "REFUND_COMPLETED"

    def test_unknown_stripe_event(self):
        payload = {
            "id": "evt_unk",
            "type": "some.unknown.event",
            "data": {"object": {"id": "obj_1"}},
        }
        events = self.t.transform(payload, PLATFORM_ID)
        assert events[0]["type"] == "CUSTOM"
        assert events[0]["custom_type"] == "stripe.some.unknown.event"


class TestPaystackTransformer:

    def setup_method(self):
        self.t = PaystackTransformer()

    def test_source_name(self):
        assert self.t.source_name == "paystack"

    def test_charge_success(self):
        payload = {
            "event": "charge.success",
            "data": {
                "reference": "ref_123",
                "amount": 150000,
                "currency": "NGN",
                "status": "success",
                "channel": "card",
                "customer": {"email": "buyer@ng.com", "customer_code": "CUS_x"},
            },
        }
        events = self.t.transform(payload, PLATFORM_ID)
        assert len(events) == 1
        ev = events[0]
        assert ev["type"] == "PAYMENT_COMPLETED"
        assert ev["actor_id"] == "buyer@ng.com"
        assert ev["properties"]["amount"] == 150000
        assert ev["properties"]["currency"] == "NGN"

    def test_transfer_success(self):
        payload = {
            "event": "transfer.success",
            "data": {
                "reference": "tr_456",
                "amount": 50000,
                "customer": {"email": "seller@ng.com"},
            },
        }
        events = self.t.transform(payload, PLATFORM_ID)
        assert events[0]["type"] == "REFUND_COMPLETED"

    def test_subscription_create(self):
        payload = {
            "event": "subscription.create",
            "data": {"customer": {"email": "sub@ng.com"}},
        }
        events = self.t.transform(payload, PLATFORM_ID)
        assert events[0]["type"] == "SUBSCRIPTION_STARTED"

    def test_subscription_disable(self):
        payload = {
            "event": "subscription.disable",
            "data": {"customer": {"email": "unsub@ng.com"}},
        }
        events = self.t.transform(payload, PLATFORM_ID)
        assert events[0]["type"] == "SUBSCRIPTION_CANCELLED"

    def test_invoice_update_maps_to_custom(self):
        payload = {
            "event": "invoice.update",
            "data": {"customer": {"email": "inv@ng.com"}},
        }
        events = self.t.transform(payload, PLATFORM_ID)
        assert events[0]["type"] == "CUSTOM"
        assert events[0]["custom_type"] == "invoice_updated"

    def test_unknown_paystack_event(self):
        payload = {
            "event": "unknown.event",
            "data": {"reference": "ref_unk", "customer": {}},
        }
        events = self.t.transform(payload, PLATFORM_ID)
        assert events[0]["type"] == "CUSTOM"
        assert events[0]["custom_type"] == "paystack.unknown.event"


class TestShopifyTransformer:

    def setup_method(self):
        self.t = ShopifyTransformer()

    def test_source_name(self):
        assert self.t.source_name == "shopify"

    def test_orders_create(self):
        payload = {
            "id": 12345,
            "name": "#1001",
            "total_price": "99.99",
            "currency": "USD",
            "customer": {"id": 67890, "email": "buyer@shop.com"},
        }
        events = self.t.transform(
            payload, PLATFORM_ID,
            headers={"X-Shopify-Topic": "orders/create"},
        )
        assert len(events) == 1
        ev = events[0]
        assert ev["type"] == "ORDER_CREATED"
        assert ev["actor_id"] == "buyer@shop.com"
        assert ev["properties"]["amount"] == "99.99"
        assert ev["properties"]["order_name"] == "#1001"

    def test_orders_paid(self):
        payload = {
            "id": 22222,
            "customer": {"email": "payer@shop.com"},
        }
        events = self.t.transform(
            payload, PLATFORM_ID,
            headers={"X-Shopify-Topic": "orders/paid"},
        )
        assert events[0]["type"] == "PAYMENT_COMPLETED"

    def test_orders_cancelled(self):
        payload = {"id": 33333, "customer": {"email": "cancel@shop.com"}}
        events = self.t.transform(
            payload, PLATFORM_ID,
            headers={"X-Shopify-Topic": "orders/cancelled"},
        )
        assert events[0]["type"] == "ORDER_CANCELLED"

    def test_orders_fulfilled(self):
        payload = {"id": 44444, "customer": {"email": "fulfilled@shop.com"}}
        events = self.t.transform(
            payload, PLATFORM_ID,
            headers={"X-Shopify-Topic": "orders/fulfilled"},
        )
        assert events[0]["type"] == "ORDER_COMPLETED"

    def test_customers_create(self):
        payload = {"id": 55555, "email": "new@shop.com", "customer": {}}
        events = self.t.transform(
            payload, PLATFORM_ID,
            headers={"X-Shopify-Topic": "customers/create"},
        )
        assert events[0]["type"] == "USER_REGISTERED"

    def test_refunds_create(self):
        payload = {"id": 66666, "customer": {"email": "refund@shop.com"}}
        events = self.t.transform(
            payload, PLATFORM_ID,
            headers={"X-Shopify-Topic": "refunds/create"},
        )
        assert events[0]["type"] == "REFUND_INITIATED"

    def test_products_create(self):
        payload = {"id": 77777, "title": "Cool Widget", "customer": {}}
        events = self.t.transform(
            payload, PLATFORM_ID,
            headers={"X-Shopify-Topic": "products/create"},
        )
        assert events[0]["type"] == "CONTENT_CREATED"

    def test_topic_from_payload_fallback(self):
        payload = {"id": 88888, "topic": "orders/create", "customer": {"email": "fb@shop.com"}}
        events = self.t.transform(payload, PLATFORM_ID)
        assert events[0]["type"] == "ORDER_CREATED"

    def test_unknown_topic(self):
        payload = {"id": 99999, "customer": {}}
        events = self.t.transform(
            payload, PLATFORM_ID,
            headers={"X-Shopify-Topic": "carts/create"},
        )
        assert events[0]["type"] == "CUSTOM"
        assert events[0]["custom_type"] == "shopify.carts/create"


class TestGenericTransformer:

    def setup_method(self):
        self.t = GenericTransformer()

    def test_source_name(self):
        assert self.t.source_name == "generic"

    def test_known_event_type_passthrough(self):
        payload = {
            "event_type": "PAGE_VIEWED",
            "actor_id": "user_1",
            "properties": {"url": "/home"},
        }
        events = self.t.transform(payload, PLATFORM_ID)
        assert len(events) == 1
        ev = events[0]
        assert ev["type"] == "PAGE_VIEWED"
        assert ev["actor_id"] == "user_1"
        assert "custom_type" not in ev

    def test_unknown_event_type_becomes_custom(self):
        payload = {
            "event_type": "widget_clicked",
            "actor_id": "user_2",
            "properties": {"widget": "cta"},
        }
        events = self.t.transform(payload, PLATFORM_ID)
        ev = events[0]
        assert ev["type"] == "CUSTOM"
        assert ev["custom_type"] == "widget_clicked"

    def test_user_id_fallback(self):
        payload = {"user_id": "uid_99", "event_type": "PAGE_VIEWED"}
        events = self.t.transform(payload, PLATFORM_ID)
        assert events[0]["actor_id"] == "uid_99"

    def test_customer_id_fallback(self):
        payload = {"customer_id": "cid_88", "event_type": "PAGE_VIEWED"}
        events = self.t.transform(payload, PLATFORM_ID)
        assert events[0]["actor_id"] == "cid_88"

    def test_optional_fields_passed_through(self):
        payload = {
            "event_type": "ITEM_VIEWED",
            "actor_id": "u1",
            "target_id": "item_10",
            "target_type": "Product",
            "actor_type": "Buyer",
            "context": {"session_id": "sess_1"},
            "properties": {"item_id": "item_10"},
        }
        events = self.t.transform(payload, PLATFORM_ID)
        ev = events[0]
        assert ev["target_id"] == "item_10"
        assert ev["target_type"] == "Product"
        assert ev["actor_type"] == "Buyer"
        assert ev["context"]["session_id"] == "sess_1"

    def test_empty_payload_defaults(self):
        events = self.t.transform({}, PLATFORM_ID)
        ev = events[0]
        assert ev["type"] == "CUSTOM"
        assert ev["actor_id"] == "unknown"
        assert ev["custom_type"] == "generic_custom"
        assert ev["properties"]["custom_type"] == "generic_custom"
