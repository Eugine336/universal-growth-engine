"""
Tests for the Webhook Connector, PayloadTransformers, and connector config loading.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import httpx
import pytest

from core.action.schema import Action, ActionResult, ActionStatus
from connectors.webhook.connector import WebhookConnector, _resolve_env_vars
from connectors.webhook.transformer import (
    GenericWebhookTransformer,
    PassthroughTransformer,
    SendGridTransformer,
    TwilioSMSTransformer,
    TRANSFORMER_REGISTRY,
)


def _make_action(**overrides) -> Action:
    defaults = {
        "decision_id": "dec-001",
        "identity_id": "id-001",
        "application_id": "app-001",
        "action_type": "SEND_EMAIL",
        "payload": {
            "recipient": "alice@example.com",
            "from_email": "noreply@ugie.io",
            "subject": "Hello",
            "body": "<p>Hi Alice</p>",
            "phone": "+254700123456",
            "from_phone": "+15005550006",
            "message": "Hello from UGIE",
        },
        "context": {"policy_id": "p1", "policy_name": "test"},
    }
    defaults.update(overrides)
    return Action(**defaults)


# ---------------------------------------------------------------------------
# Transformer tests
# ---------------------------------------------------------------------------


class TestPassthroughTransformer:

    def test_passthrough(self):
        action = _make_action()
        result = PassthroughTransformer().transform(action)
        assert result == action.payload

    def test_passthrough_returns_copy(self):
        action = _make_action()
        result = PassthroughTransformer().transform(action)
        result["extra"] = True
        assert "extra" not in action.payload


class TestSendGridTransformer:

    def test_transform(self):
        action = _make_action()
        result = SendGridTransformer().transform(action)
        assert result["personalizations"][0]["to"][0]["email"] == "alice@example.com"
        assert result["from"]["email"] == "noreply@ugie.io"
        assert result["subject"] == "Hello"
        assert result["content"][0]["value"] == "<p>Hi Alice</p>"
        assert result["custom_args"]["action_id"] == action.id
        assert result["custom_args"]["identity_id"] == "id-001"

    def test_defaults(self):
        action = _make_action(payload={})
        result = SendGridTransformer().transform(action)
        assert result["personalizations"][0]["to"][0]["email"] == "id-001"
        assert result["from"]["email"] == "noreply@ugie.io"
        assert result["subject"] == "Notification"


class TestTwilioSMSTransformer:

    def test_transform(self):
        action = _make_action(action_type="SEND_SMS")
        result = TwilioSMSTransformer().transform(action)
        assert result["To"] == "+254700123456"
        assert result["From"] == "+15005550006"
        assert result["Body"] == "Hello from UGIE"


class TestGenericWebhookTransformer:

    def test_transform(self):
        action = _make_action(action_type="START_WORKFLOW")
        result = GenericWebhookTransformer().transform(action)
        assert result["event"] == "action_dispatch"
        assert result["action_id"] == action.id
        assert result["action_type"] == "START_WORKFLOW"
        assert result["identity_id"] == "id-001"
        assert result["application_id"] == "app-001"
        assert "dispatched_at" in result


class TestTransformerRegistry:

    def test_all_registered(self):
        assert "passthrough" in TRANSFORMER_REGISTRY
        assert "sendgrid" in TRANSFORMER_REGISTRY
        assert "twilio_sms" in TRANSFORMER_REGISTRY
        assert "generic_webhook" in TRANSFORMER_REGISTRY


# ---------------------------------------------------------------------------
# Env var resolution tests
# ---------------------------------------------------------------------------


class TestEnvVarResolution:

    def test_resolve_env_var(self):
        with patch.dict(os.environ, {"MY_KEY": "secret123"}):
            assert _resolve_env_vars("Bearer ${MY_KEY}") == "Bearer secret123"

    def test_unset_env_var_kept_as_is(self):
        result = _resolve_env_vars("${DOES_NOT_EXIST_XYZZY}")
        assert result == "${DOES_NOT_EXIST_XYZZY}"

    def test_no_placeholders(self):
        assert _resolve_env_vars("plain text") == "plain text"

    def test_multiple_vars(self):
        with patch.dict(os.environ, {"A": "1", "B": "2"}):
            assert _resolve_env_vars("${A}-${B}") == "1-2"


# ---------------------------------------------------------------------------
# WebhookConnector tests
# ---------------------------------------------------------------------------


class TestWebhookConnector:

    def _connector(self, **overrides):
        defaults = {
            "connector_id": "test_email",
            "name": "Test Email",
            "supported_action_types": ["SEND_EMAIL"],
            "webhook_url": "https://api.sendgrid.com/v3/mail/send",
            "headers": {"Authorization": "Bearer test_key"},
            "transformer": PassthroughTransformer(),
        }
        defaults.update(overrides)
        return WebhookConnector(**defaults)

    def test_manifest(self):
        c = self._connector()
        m = c.manifest
        assert m.id == "test_email"
        assert "SEND_EMAIL" in m.supported_action_types
        assert m.metadata["webhook_url"] == "https://api.sendgrid.com/v3/mail/send"

    def test_can_handle(self):
        c = self._connector()
        assert c.can_handle("SEND_EMAIL") is True
        assert c.can_handle("SEND_SMS") is False

    @patch("connectors.webhook.connector.httpx.Client")
    def test_successful_post(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "msg-123"}
        mock_response.text = '{"id": "msg-123"}'

        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        c = self._connector()
        action = _make_action()
        result = c.execute(action)

        assert result.success is True
        assert result.connector_id == "test_email"
        assert result.connector_ref == "msg-123"
        assert result.response == {"id": "msg-123"}
        assert result.duration_ms is not None

    @patch("connectors.webhook.connector.httpx.Client")
    def test_http_error(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"error": "internal"}
        mock_response.text = '{"error": "internal"}'

        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        c = self._connector()
        result = c.execute(_make_action())

        assert result.success is False
        assert "500" in result.error
        assert result.response == {"error": "internal"}

    @patch("connectors.webhook.connector.httpx.Client")
    def test_timeout(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.TimeoutException("timed out")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        c = self._connector(timeout_seconds=5)
        result = c.execute(_make_action())

        assert result.success is False
        assert "Timeout" in result.error

    @patch("connectors.webhook.connector.httpx.Client")
    def test_connection_error(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.ConnectError("refused")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        c = self._connector()
        result = c.execute(_make_action())

        assert result.success is False
        assert "Connection failed" in result.error

    @patch("connectors.webhook.connector.httpx.Client")
    def test_env_var_substitution_in_headers(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        mock_response.text = "{}"

        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with patch.dict(os.environ, {"MY_API_KEY": "real_key"}):
            c = self._connector(
                headers={"Authorization": "Bearer ${MY_API_KEY}"}
            )
            c.execute(_make_action())

        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer real_key"

    def test_transform_error_returns_failure(self):
        bad_transformer = MagicMock()
        bad_transformer.transform.side_effect = ValueError("bad payload")

        c = self._connector(transformer=bad_transformer)
        result = c.execute(_make_action())

        assert result.success is False
        assert "transform failed" in result.error.lower()

    @patch("connectors.webhook.connector.httpx.Client")
    def test_non_json_response(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("not json")
        mock_response.text = "OK"

        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        c = self._connector()
        result = c.execute(_make_action())

        assert result.success is True
        assert result.response == {"raw_body": "OK"}


# ---------------------------------------------------------------------------
# Connector config loading tests
# ---------------------------------------------------------------------------


class TestConnectorConfigLoading:

    def test_load_connector_from_yaml(self, tmp_path):
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text("""
application:
  id: test_app
  name: Test App

connectors:
  - id: test_email
    name: Test Email
    action_types: [SEND_EMAIL]
    webhook_url: "https://api.example.com/email"
    headers:
      Authorization: "Bearer test123"
    transformer: sendgrid
    timeout_seconds: 15
""")
        from core.action.connector import ConnectorRegistry
        from core.config.loader import DomainConfigLoader
        from core.decision.policy import PolicyRegistry
        from core.entity.registry import EntityRegistry
        from core.entity.state import EntityStateMachine
        from core.events.validator import EventValidator

        registry = ConnectorRegistry()
        loader = DomainConfigLoader(
            entity_registry=EntityRegistry(),
            state_machine=EntityStateMachine(),
            event_validator=EventValidator(),
            policy_registry=PolicyRegistry(),
            connector_registry=registry,
        )
        config = loader.load_file(str(config_yaml))

        assert len(config.connectors) == 1
        connector = registry.get("test_email")
        assert connector is not None
        assert connector.manifest.id == "test_email"
        assert "SEND_EMAIL" in connector.manifest.supported_action_types

    def test_connector_overrides_stub(self, tmp_path):
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text("""
application:
  id: override_app
  name: Override App

connectors:
  - id: custom_email
    name: Custom Email
    action_types: [SEND_EMAIL]
    webhook_url: "https://api.example.com/email"
    transformer: sendgrid
""")
        from core.action.connector import ConnectorRegistry
        from core.config.loader import DomainConfigLoader
        from core.decision.policy import PolicyRegistry
        from core.entity.registry import EntityRegistry
        from core.entity.state import EntityStateMachine
        from core.events.validator import EventValidator

        registry = ConnectorRegistry()
        loader = DomainConfigLoader(
            entity_registry=EntityRegistry(),
            state_machine=EntityStateMachine(),
            event_validator=EventValidator(),
            policy_registry=PolicyRegistry(),
            connector_registry=registry,
        )
        loader.load_file(str(config_yaml))

        connector = registry.resolve("SEND_EMAIL")
        assert connector is not None
        assert connector.manifest.id == "custom_email"

    def test_no_connector_registry_skips(self, tmp_path):
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text("""
application:
  id: no_reg
  name: No Registry

connectors:
  - id: should_skip
    name: Skip
    action_types: [SEND_EMAIL]
    webhook_url: "https://example.com"
""")
        from core.config.loader import DomainConfigLoader
        from core.decision.policy import PolicyRegistry
        from core.entity.registry import EntityRegistry
        from core.entity.state import EntityStateMachine
        from core.events.validator import EventValidator

        loader = DomainConfigLoader(
            entity_registry=EntityRegistry(),
            state_machine=EntityStateMachine(),
            event_validator=EventValidator(),
            policy_registry=PolicyRegistry(),
        )
        config = loader.load_file(str(config_yaml))
        assert len(config.connectors) == 1

    def test_unknown_transformer_falls_back(self, tmp_path):
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text("""
application:
  id: fallback_app
  name: Fallback App

connectors:
  - id: fallback_conn
    name: Fallback
    action_types: [SEND_PUSH]
    webhook_url: "https://example.com"
    transformer: nonexistent_transformer
""")
        from core.action.connector import ConnectorRegistry
        from core.config.loader import DomainConfigLoader
        from core.decision.policy import PolicyRegistry
        from core.entity.registry import EntityRegistry
        from core.entity.state import EntityStateMachine
        from core.events.validator import EventValidator

        registry = ConnectorRegistry()
        loader = DomainConfigLoader(
            entity_registry=EntityRegistry(),
            state_machine=EntityStateMachine(),
            event_validator=EventValidator(),
            policy_registry=PolicyRegistry(),
            connector_registry=registry,
        )
        loader.load_file(str(config_yaml))

        connector = registry.get("fallback_conn")
        assert connector is not None

    def test_stub_connectors_remain_as_fallback(self):
        from core.action.connector import ConnectorRegistry

        registry = ConnectorRegistry()
        sms = registry.resolve("SEND_SMS")
        assert sms is not None
        assert sms.manifest.id == "sms"
