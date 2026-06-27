"""
Unit tests — Python SDK client and event shortcut mapping.
"""

import pytest

from sdk.python.ugie.client import UGIEClient
from sdk.python.ugie.errors import UGIEError
from sdk.python.ugie.shortcuts import EVENT_SHORTCUTS


class TestEventShortcuts:

    def test_common_shortcuts_exist(self):
        assert EVENT_SHORTCUTS["signup"] == "USER_REGISTERED"
        assert EVENT_SHORTCUTS["purchase"] == "PAYMENT_COMPLETED"
        assert EVENT_SHORTCUTS["subscribe"] == "SUBSCRIPTION_STARTED"
        assert EVENT_SHORTCUTS["cancel"] == "SUBSCRIPTION_CANCELLED"
        assert EVENT_SHORTCUTS["login"] == "LOGIN_SUCCESS"
        assert EVENT_SHORTCUTS["search"] == "SEARCH_EXECUTED"
        assert EVENT_SHORTCUTS["referral"] == "REFERRAL_SENT"
        assert EVENT_SHORTCUTS["review"] == "REVIEW_CREATED"
        assert EVENT_SHORTCUTS["page_view"] == "PAGE_VIEWED"
        assert EVENT_SHORTCUTS["kyc_complete"] == "KYC_COMPLETED"

    def test_shortcut_coverage(self):
        assert len(EVENT_SHORTCUTS) >= 20


class TestClientResolveEventType:

    def setup_method(self):
        self.client = UGIEClient(api_key="test_key", base_url="http://test:8000")

    def teardown_method(self):
        self.client.close()

    def test_shortcut_resolution(self):
        t, c = self.client._resolve_event_type("signup")
        assert t == "USER_REGISTERED"
        assert c is None

    def test_shortcut_case_insensitive(self):
        t, c = self.client._resolve_event_type("SIGNUP")
        assert t == "USER_REGISTERED"
        assert c is None

    def test_raw_event_type(self):
        t, c = self.client._resolve_event_type("PAGE_VIEWED")
        assert t == "PAGE_VIEWED"
        assert c is None

    def test_custom_event(self):
        t, c = self.client._resolve_event_type("my_custom_thing")
        assert t == "CUSTOM"
        assert c == "my_custom_thing"

    def test_purchase_shortcut(self):
        t, c = self.client._resolve_event_type("purchase")
        assert t == "PAYMENT_COMPLETED"
        assert c is None


class TestClientPayloadBuild:

    def setup_method(self):
        self.client = UGIEClient(
            api_key="test_key",
            base_url="http://test:8000",
            platform_slug="myapp",
        )

    def teardown_method(self):
        self.client.close()

    def test_track_builds_correct_structure(self):
        import httpx
        from unittest.mock import MagicMock, patch

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True}

        with patch.object(self.client._client, "request", return_value=mock_resp) as mock_req:
            self.client.track("user_1", "signup", {"source": "organic"})
            call_args = mock_req.call_args
            payload = call_args.kwargs.get("json") or call_args[1].get("json")
            assert payload["type"] == "USER_REGISTERED"
            assert payload["actor_id"] == "user_1"
            assert payload["application_id"] == "myapp"
            assert payload["properties"]["source"] == "organic"

    def test_track_with_target(self):
        from unittest.mock import MagicMock, patch

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True}

        with patch.object(self.client._client, "request", return_value=mock_resp) as mock_req:
            self.client.track(
                "user_1", "view_item", {"price": 100},
                target_id="item_42", target_type="Product",
            )
            payload = mock_req.call_args.kwargs.get("json") or mock_req.call_args[1].get("json")
            assert payload["target_id"] == "item_42"
            assert payload["target_type"] == "Product"

    def test_batch_builds_list(self):
        from unittest.mock import MagicMock, patch

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"success": True}, {"success": True}]

        with patch.object(self.client._client, "request", return_value=mock_resp) as mock_req:
            self.client.track_batch([
                {"actor_id": "u1", "event_type": "signup"},
                {"actor_id": "u2", "event_type": "purchase", "properties": {"amount": 50}},
            ])
            payload = mock_req.call_args.kwargs.get("json") or mock_req.call_args[1].get("json")
            assert len(payload) == 2
            assert payload[0]["type"] == "USER_REGISTERED"
            assert payload[1]["type"] == "PAYMENT_COMPLETED"


class TestUGIEError:

    def test_error_attributes(self):
        err = UGIEError("bad request", status_code=400, response_body={"detail": "bad"})
        assert err.status_code == 400
        assert err.response_body == {"detail": "bad"}
        assert str(err) == "bad request"

    def test_error_defaults(self):
        err = UGIEError("fail")
        assert err.status_code == 0
        assert err.response_body == {}

    def test_client_raises_on_4xx(self):
        from unittest.mock import MagicMock, patch

        client = UGIEClient(api_key="bad_key", base_url="http://test:8000")
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"detail": "Invalid API key"}
        mock_resp.text = "Unauthorized"

        with patch.object(client._client, "request", return_value=mock_resp):
            with pytest.raises(UGIEError) as exc_info:
                client.track("user_1", "signup")
            assert exc_info.value.status_code == 401
        client.close()
