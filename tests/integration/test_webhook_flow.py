"""
Integration test — webhook connector flow and feedback endpoint.
"""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.rest.app import create_app, pipeline
from connectors.webhook.connector import WebhookConnector
from connectors.webhook.transformer import PassthroughTransformer


@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


class TestWebhookFeedbackEndpoint:

    def test_feedback_action_not_found(self, client):
        resp = client.post("/api/v1/webhooks/action-feedback", json={
            "action_id": "nonexistent-action",
            "event": "email_opened",
        })
        assert resp.status_code == 404

    def test_feedback_records_on_existing_action(self, client):
        from core.action.schema import Action

        action = Action(
            decision_id="dec-test",
            identity_id="id-test",
            application_id="app-test",
            action_type="SEND_EMAIL",
        )
        pipeline.action_orchestrator._store_action(action)

        resp = client.post("/api/v1/webhooks/action-feedback", json={
            "action_id": action.id,
            "event": "email_opened",
            "data": {"timestamp": "2024-01-01T00:00:00Z"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["action_id"] == action.id
        assert data["event"] == "email_opened"
        assert "email_opened" in data["feedback"]

    def test_feedback_multiple_events(self, client):
        from core.action.schema import Action

        action = Action(
            decision_id="dec-multi",
            identity_id="id-multi",
            application_id="app-test",
            action_type="SEND_EMAIL",
        )
        pipeline.action_orchestrator._store_action(action)

        client.post("/api/v1/webhooks/action-feedback", json={
            "action_id": action.id,
            "event": "email_delivered",
        })
        resp = client.post("/api/v1/webhooks/action-feedback", json={
            "action_id": action.id,
            "event": "email_clicked",
            "data": {"clicked_url": "https://example.com/offer"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "email_delivered" in data["feedback"]
        assert "email_clicked" in data["feedback"]


class TestWebhookConnectorWithOrchestrator:

    def test_dispatch_with_webhook_connector(self):
        from core.action.connector import ConnectorRegistry
        from core.action.orchestrator import ActionOrchestrator
        from core.decision.schema import ActionType, Decision

        registry = ConnectorRegistry()
        mock_connector = MagicMock()
        mock_connector.manifest = MagicMock(
            id="mock_webhook",
            name="Mock Webhook",
            supported_action_types=["SEND_EMAIL"],
            enabled=True,
        )
        mock_connector.can_handle.return_value = True
        mock_connector.execute.return_value = MagicMock(
            success=True,
            connector_id="mock_webhook",
            connector_ref="ref-123",
            response={"message_id": "msg-abc"},
            error=None,
            duration_ms=50.0,
        )

        registry.register(mock_connector)

        orchestrator = ActionOrchestrator(connector_registry=registry)
        decision = Decision(
            identity_id="id-999",
            application_id="app-999",
            action_type=ActionType.SEND_EMAIL,
            payload={"recipient": "test@example.com"},
        )

        result = orchestrator.dispatch(decision)
        assert result.success is True
        mock_connector.execute.assert_called_once()


class TestHealthIncludesConnectors:

    def test_health_endpoint(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_stats_includes_orchestrator(self, client):
        resp = client.get("/api/v1/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "action_orchestrator" in data
        assert "connectors" in data["action_orchestrator"]
