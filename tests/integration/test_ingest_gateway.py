"""
Integration test — Universal Webhook Ingest Gateway.

Proves: platform auth → inbound transformer → UGIE event pipeline,
for Stripe, Paystack, Shopify, and generic payloads.
"""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from api.rest.app import create_app, pipeline


@pytest.fixture(scope="module")
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app(db_url=f"sqlite:///{db_path}")
    with TestClient(app) as c:
        yield c
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture(scope="module")
def api_key(client):
    resp = client.post("/api/v1/platforms", json={
        "name": "IngestTest",
        "slug": "ingest-test",
        "owner_email": "test@ingest.io",
    })
    assert resp.status_code == 200
    return resp.json()["api_key"]


def _headers(api_key):
    return {"X-API-Key": api_key}


class TestIngestStripe:

    def test_payment_succeeded(self, client, api_key):
        payload = {
            "id": "evt_stripe_1",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_1",
                    "customer": "cus_stripe_buyer",
                    "amount": 9900,
                    "currency": "usd",
                    "status": "succeeded",
                }
            },
        }
        resp = client.post(
            "/api/v1/ingest/stripe",
            json=payload,
            headers=_headers(api_key),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "stripe"
        assert data["events_created"] == 1

    def test_subscription_created(self, client, api_key):
        payload = {
            "id": "evt_stripe_2",
            "type": "customer.subscription.created",
            "data": {"object": {"id": "sub_1", "customer": "cus_sub", "plan": {"id": "plan_pro"}}},
        }
        resp = client.post(
            "/api/v1/ingest/stripe",
            json=payload,
            headers=_headers(api_key),
        )
        assert resp.status_code == 200
        assert resp.json()["events_created"] == 1

    def test_unknown_stripe_event(self, client, api_key):
        payload = {
            "id": "evt_stripe_unk",
            "type": "radar.early_fraud_warning.created",
            "data": {"object": {"id": "issfr_1"}},
        }
        resp = client.post(
            "/api/v1/ingest/stripe",
            json=payload,
            headers=_headers(api_key),
        )
        assert resp.status_code == 200
        assert resp.json()["events_created"] == 1


class TestIngestPaystack:

    def test_charge_success(self, client, api_key):
        payload = {
            "event": "charge.success",
            "data": {
                "reference": "ref_ps_1",
                "amount": 500000,
                "currency": "NGN",
                "status": "success",
                "channel": "card",
                "customer": {"email": "buyer@paystack.ng"},
            },
        }
        resp = client.post(
            "/api/v1/ingest/paystack",
            json=payload,
            headers=_headers(api_key),
        )
        assert resp.status_code == 200
        assert resp.json()["events_created"] == 1

    def test_subscription_create(self, client, api_key):
        payload = {
            "event": "subscription.create",
            "data": {
                "customer": {"email": "sub@paystack.ng"},
                "plan": {"plan_code": "PLN_test"},
            },
        }
        resp = client.post(
            "/api/v1/ingest/paystack",
            json=payload,
            headers=_headers(api_key),
        )
        assert resp.status_code == 200


class TestIngestShopify:

    def test_order_create(self, client, api_key):
        payload = {
            "id": 12345,
            "name": "#1001",
            "total_price": "150.00",
            "currency": "KES",
            "customer": {"id": 67890, "email": "shop_buyer@ke.com"},
        }
        headers = _headers(api_key)
        headers["X-Shopify-Topic"] = "orders/create"
        resp = client.post("/api/v1/ingest/shopify", json=payload, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["events_created"] == 1

    def test_customer_create(self, client, api_key):
        payload = {"id": 11111, "email": "newcust@shop.com", "customer": {}}
        headers = _headers(api_key)
        headers["X-Shopify-Topic"] = "customers/create"
        resp = client.post("/api/v1/ingest/shopify", json=payload, headers=headers)
        assert resp.status_code == 200

    def test_refund_create(self, client, api_key):
        payload = {"id": 22222, "customer": {"email": "refund@shop.com"}}
        headers = _headers(api_key)
        headers["X-Shopify-Topic"] = "refunds/create"
        resp = client.post("/api/v1/ingest/shopify", json=payload, headers=headers)
        assert resp.status_code == 200


class TestIngestGeneric:

    def test_known_event_type(self, client, api_key):
        payload = {
            "event_type": "PAGE_VIEWED",
            "actor_id": "gen_user_1",
            "properties": {"page_url": "/pricing"},
        }
        resp = client.post(
            "/api/v1/ingest/generic",
            json=payload,
            headers=_headers(api_key),
        )
        assert resp.status_code == 200
        assert resp.json()["events_created"] == 1

    def test_custom_event_type(self, client, api_key):
        payload = {
            "event_type": "widget_clicked",
            "actor_id": "gen_user_2",
            "properties": {"widget": "hero_cta"},
        }
        resp = client.post(
            "/api/v1/ingest/generic",
            json=payload,
            headers=_headers(api_key),
        )
        assert resp.status_code == 200
        assert resp.json()["events_created"] == 1


class TestIngestAuth:

    def test_no_api_key_returns_401(self, client):
        resp = client.post("/api/v1/ingest/stripe", json={"type": "test"})
        assert resp.status_code == 401

    def test_bad_api_key_returns_401(self, client):
        resp = client.post(
            "/api/v1/ingest/stripe",
            json={"type": "test"},
            headers={"X-API-Key": "bad_key_12345"},
        )
        assert resp.status_code == 401


class TestIngestUnknownSource:

    def test_unknown_source_returns_404(self, client, api_key):
        resp = client.post(
            "/api/v1/ingest/unknown_provider",
            json={"data": "test"},
            headers=_headers(api_key),
        )
        assert resp.status_code == 404
        assert "unknown_provider" in resp.json()["detail"].lower()


class TestListSources:

    def test_list_available_sources(self, client):
        resp = client.get("/api/v1/ingest/sources")
        assert resp.status_code == 200
        sources = resp.json()["sources"]
        assert "stripe" in sources
        assert "paystack" in sources
        assert "shopify" in sources
        assert "generic" in sources
