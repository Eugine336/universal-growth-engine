"""
Integration test — Python SDK end-to-end against the live API.

Proves: SDK → HTTP → UGIE pipeline → identity resolution → behavioral profiling.
"""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from api.rest.app import create_app, pipeline
from sdk.python.ugie.client import UGIEClient
from sdk.python.ugie.errors import UGIEError


class _SDKTestClient(UGIEClient):
    """Wraps the SDK client to use FastAPI TestClient transport."""

    def __init__(self, test_client: TestClient, api_key: str):
        super().__init__(api_key=api_key, base_url="http://testserver")
        self._test_client = test_client
        import httpx
        self._client = httpx.Client(
            transport=httpx.MockTransport(self._dispatch),
            base_url="http://testserver",
            headers={"X-API-Key": api_key},
            timeout=30.0,
        )

    def _dispatch(self, request: "httpx.Request") -> "httpx.Response":
        import httpx
        resp = self._test_client.request(
            method=request.method,
            url=str(request.url),
            headers=dict(request.headers),
            content=request.content,
        )
        return httpx.Response(
            status_code=resp.status_code,
            headers=dict(resp.headers),
            content=resp.content,
        )


@pytest.fixture(scope="module")
def test_app():
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
def api_key(test_app):
    resp = test_app.post("/api/v1/platforms", json={
        "name": "SDKTest",
        "slug": "sdk-test",
        "owner_email": "sdk@test.io",
    })
    assert resp.status_code == 200
    return resp.json()["api_key"]


@pytest.fixture(scope="module")
def sdk(test_app, api_key):
    client = _SDKTestClient(test_app, api_key)
    yield client
    client.close()


class TestSDKTrack:

    def test_track_signup(self, sdk):
        result = sdk.track("sdk_user_1", "signup", {"source": "organic"})
        assert result.get("success") is True

    def test_track_purchase(self, sdk):
        result = sdk.track("sdk_user_1", "purchase", {"amount": 2500, "currency": "KES"})
        assert result.get("success") is True

    def test_track_page_view(self, sdk):
        result = sdk.track("sdk_user_1", "page_view", {"page_url": "/pricing"})
        assert result.get("success") is True

    def test_track_raw_event_type(self, sdk):
        result = sdk.track("sdk_user_1", "SEARCH_EXECUTED", {"query": "AI tools"})
        assert result.get("success") is True

    def test_track_custom_event(self, sdk):
        result = sdk.track("sdk_user_1", "custom_widget_click", {"widget": "hero"})
        assert result.get("success") is True

    def test_track_with_target(self, sdk):
        result = sdk.track(
            "sdk_user_1", "view_item", {"item_id": "item_1", "price": 50},
            target_id="item_1", target_type="Product",
        )
        assert result.get("success") is True

    def test_track_with_context(self, sdk):
        result = sdk.track(
            "sdk_user_1", "page_view", {"page_url": "/about"},
            context={"session_id": "sess_sdk_1", "utm_source": "twitter"},
        )
        assert result.get("success") is True


class TestSDKBatch:

    def test_track_batch(self, sdk):
        results = sdk.track_batch([
            {"actor_id": "batch_u1", "event_type": "signup", "properties": {"via": "email"}},
            {"actor_id": "batch_u2", "event_type": "purchase", "properties": {"amount": 100, "currency": "USD"}},
            {"actor_id": "batch_u3", "event_type": "review", "properties": {"rating": 5}},
        ])
        assert len(results) == 3
        assert all(r.get("success") is True for r in results)


class TestSDKIdentify:

    def test_identify_creates_identity(self, sdk):
        result = sdk.identify("ident_user_1", {
            "name": "Test User",
            "email": "testuser@sdk.io",
        })
        assert result.get("success") is True


class TestSDKErrors:

    def test_bad_api_key(self, test_app):
        bad_sdk = _SDKTestClient(test_app, "invalid_key_xyz")
        with pytest.raises(UGIEError) as exc_info:
            bad_sdk.track("user_x", "signup")
        assert exc_info.value.status_code == 401
        bad_sdk.close()
