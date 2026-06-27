"""
Unit Tests — core/action

Tests cover:
- Action schema lifecycle
- ActionResult
- ConnectorManifest
- BaseConnector subclassing
- ConnectorRegistry: registration, resolution, defaults
- ActionOrchestrator: dispatch, retry, feedback, batch, stats
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest
from datetime import datetime, timezone, timedelta
from typing import Optional

from core.decision.schema import Decision, DecisionStatus, ActionType, DecisionContext

from core.action.schema import Action, ActionStatus, ActionResult, ConnectorManifest
from core.action.connector import (
    BaseConnector, ConnectorRegistry,
    EmailConnector, PushConnector, WorkflowConnector,
)
from core.action.orchestrator import ActionOrchestrator, DispatchResult


# ===========================================================================
# Fixtures
# ===========================================================================

def make_decision(
    action_type: ActionType = ActionType.SEND_EMAIL,
    identity_id: str = "identity_001",
    application_id: str = "ucmc",
    payload: dict = None,
    valid_until=None,
    execute_after=None,
) -> Decision:
    return Decision(
        identity_id=identity_id,
        application_id=application_id,
        action_type=action_type,
        priority=50,
        payload=payload or {"template": "test_template"},
        valid_until=valid_until,
        execute_after=execute_after,
        context=DecisionContext(
            policy_id="policy_001",
            policy_name="Test Policy",
            churn_score=0.3,
            fraud_score=0.05,
            engagement_tier="active",
            rfm_segment="loyal",
        ),
    )


def make_action(
    action_type: str = "SEND_EMAIL",
    identity_id: str = "identity_001",
    status: ActionStatus = ActionStatus.QUEUED,
) -> Action:
    return Action(
        decision_id="decision_001",
        identity_id=identity_id,
        application_id="ucmc",
        action_type=action_type,
        payload={"template": "test"},
        status=status,
    )


def make_orchestrator(feedback_fn=None) -> ActionOrchestrator:
    registry = ConnectorRegistry()
    orch = ActionOrchestrator(connector_registry=registry)
    if feedback_fn:
        orch.set_feedback_publisher(feedback_fn)
    return orch


# ---------------------------------------------------------------------------
# Custom test connectors
# ---------------------------------------------------------------------------

class AlwaysSucceedsConnector(BaseConnector):
    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            id="always_success",
            name="Always Success",
            supported_action_types=["TEST_SUCCESS"],
        )

    def execute(self, action: Action) -> ActionResult:
        return self._success(action, connector_ref="ref_001")


class AlwaysFailsConnector(BaseConnector):
    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            id="always_fail",
            name="Always Fail",
            supported_action_types=["TEST_FAIL"],
        )

    def execute(self, action: Action) -> ActionResult:
        return self._failure(action, error="simulated failure")


class ExplodingConnector(BaseConnector):
    """Raises an exception instead of returning a result."""

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            id="exploding",
            name="Exploding Connector",
            supported_action_types=["TEST_EXPLODE"],
        )

    def execute(self, action: Action) -> ActionResult:
        raise RuntimeError("connector exploded")


class SucceedOnRetryConnector(BaseConnector):
    """Fails first N times, then succeeds."""

    def __init__(self, fail_times: int = 1):
        self._fail_times = fail_times
        self._call_count = 0

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            id="retry_success",
            name="Retry Success",
            supported_action_types=["TEST_RETRY"],
        )

    def execute(self, action: Action) -> ActionResult:
        self._call_count += 1
        if self._call_count <= self._fail_times:
            return self._failure(action, error=f"attempt {self._call_count} failed")
        return self._success(action, connector_ref="ref_retry")


# ===========================================================================
# Action Schema Tests
# ===========================================================================

class TestActionSchema:

    def test_action_created_with_defaults(self):
        a = make_action()
        assert a.id is not None
        assert a.status == ActionStatus.QUEUED
        assert a.attempts == 0

    def test_is_executable_when_queued(self):
        a = make_action()
        assert a.is_executable() is True

    def test_not_executable_when_succeeded(self):
        a = make_action(status=ActionStatus.SUCCEEDED)
        assert a.is_executable() is False

    def test_not_executable_when_expired(self):
        a = make_action()
        a.valid_until = datetime.now(timezone.utc) - timedelta(hours=1)
        assert a.is_executable() is False

    def test_not_executable_before_execute_after(self):
        a = make_action()
        a.execute_after = datetime.now(timezone.utc) + timedelta(hours=10)
        assert a.is_executable() is False

    def test_record_success_attempt(self):
        a = make_action()
        result = ActionResult(success=True, connector_id="email")
        a.record_attempt(result)
        assert a.status == ActionStatus.SUCCEEDED
        assert a.attempts == 1
        assert a.completed_at is not None

    def test_record_failure_sets_retrying(self):
        a = make_action()
        result = ActionResult(success=False, connector_id="email", error="failed")
        a.record_attempt(result)
        assert a.status == ActionStatus.RETRYING
        assert a.last_error == "failed"

    def test_exhausted_after_max_attempts(self):
        a = make_action()
        a.max_attempts = 2
        for _ in range(2):
            a.record_attempt(ActionResult(success=False, connector_id="email", error="x"))
        assert a.status == ActionStatus.EXHAUSTED

    def test_can_retry_while_under_max(self):
        a = make_action()
        assert a.can_retry() is True
        a.status = ActionStatus.EXHAUSTED
        assert a.can_retry() is False

    def test_latest_result(self):
        a = make_action()
        r1 = ActionResult(success=False, connector_id="email", error="first")
        r2 = ActionResult(success=True, connector_id="email")
        a.record_attempt(r1)
        a.record_attempt(r2)
        assert a.latest_result().success is True


# ===========================================================================
# Connector Tests
# ===========================================================================

class TestConnectors:

    def test_email_connector_execute_succeeds(self):
        c = EmailConnector()
        action = make_action(action_type="SEND_EMAIL")
        result = c.execute(action)
        assert result.success is True
        assert result.connector_id == "email"

    def test_push_connector_execute_succeeds(self):
        c = PushConnector()
        action = make_action(action_type="SEND_PUSH")
        result = c.execute(action)
        assert result.success is True

    def test_workflow_connector_handles_multiple_types(self):
        c = WorkflowConnector()
        assert c.can_handle("TRIGGER_REENGAGEMENT") is True
        assert c.can_handle("FLAG_FOR_REVIEW") is True
        assert c.can_handle("SEND_EMAIL") is False

    def test_custom_connector_success(self):
        c = AlwaysSucceedsConnector()
        action = make_action(action_type="TEST_SUCCESS")
        result = c.execute(action)
        assert result.success is True
        assert result.connector_ref == "ref_001"

    def test_custom_connector_failure(self):
        c = AlwaysFailsConnector()
        action = make_action(action_type="TEST_FAIL")
        result = c.execute(action)
        assert result.success is False
        assert "simulated failure" in result.error


# ===========================================================================
# ConnectorRegistry Tests
# ===========================================================================

class TestConnectorRegistry:

    def setup_method(self):
        self.registry = ConnectorRegistry()

    def test_default_connectors_registered(self):
        types = self.registry.supported_action_types()
        assert "SEND_EMAIL" in types
        assert "SEND_PUSH" in types
        assert "FLAG_FOR_REVIEW" in types
        assert "TRIGGER_REENGAGEMENT" in types

    def test_resolve_returns_correct_connector(self):
        connector = self.registry.resolve("SEND_EMAIL")
        assert connector is not None
        assert connector.manifest.id == "email"

    def test_resolve_returns_none_for_unknown(self):
        assert self.registry.resolve("UNKNOWN_ACTION") is None

    def test_register_custom_connector(self):
        self.registry.register(AlwaysSucceedsConnector())
        connector = self.registry.resolve("TEST_SUCCESS")
        assert connector is not None
        assert connector.manifest.id == "always_success"

    def test_get_by_id(self):
        connector = self.registry.get("email")
        assert connector is not None

    def test_list_connectors(self):
        manifests = self.registry.list_connectors()
        ids = [m.id for m in manifests]
        assert "email" in ids
        assert "push" in ids
        assert "workflow" in ids

    def test_disabled_connector_not_registered(self):
        class DisabledConnector(BaseConnector):
            @property
            def manifest(self):
                return ConnectorManifest(
                    id="disabled",
                    name="Disabled",
                    supported_action_types=["DISABLED_ACTION"],
                    enabled=False,
                )
            def execute(self, action):
                return self._success(action)

        self.registry.register(DisabledConnector())
        assert self.registry.resolve("DISABLED_ACTION") is None


# ===========================================================================
# ActionOrchestrator Tests
# ===========================================================================

class TestActionOrchestrator:

    def setup_method(self):
        self.orchestrator = make_orchestrator()

    def test_dispatch_succeeds_for_known_action_type(self):
        decision = make_decision(action_type=ActionType.SEND_EMAIL)
        result = self.orchestrator.dispatch(decision)
        assert result.success is True
        assert result.action.status == ActionStatus.SUCCEEDED

    def test_dispatch_fails_for_unknown_action_type(self):
        decision = make_decision(action_type=ActionType.SEND_EMAIL)
        decision.action_type = ActionType.SEND_EMAIL
        # Override with unregistered type directly on action
        self.orchestrator._registry._action_map.pop("SEND_EMAIL", None)
        result = self.orchestrator.dispatch(decision)
        assert result.success is False

    def test_dispatch_records_decision_outcome(self):
        decision = make_decision(action_type=ActionType.SEND_EMAIL)
        self.orchestrator.dispatch(decision)
        assert decision.status == DecisionStatus.EXECUTED
        assert decision.outcome is not None
        assert decision.outcome.success is True

    def test_dispatch_with_custom_succeeding_connector(self):
        self.orchestrator.register_connector(AlwaysSucceedsConnector())
        decision = make_decision(action_type=ActionType.SEND_EMAIL)
        decision.action_type = ActionType.SEND_EMAIL
        # Use a decision with our custom action type via the action directly
        action = make_action(action_type="TEST_SUCCESS")
        action.decision_id = decision.id
        self.orchestrator._store_action(action)
        connector = self.orchestrator._registry.resolve("TEST_SUCCESS")
        result = self.orchestrator._execute_with_retry(action, connector)
        assert result.success is True

    def test_retry_on_failure(self):
        registry = ConnectorRegistry()
        registry.register(SucceedOnRetryConnector(fail_times=1))
        orch = ActionOrchestrator(connector_registry=registry)

        action = make_action(action_type="TEST_RETRY")
        action.max_attempts = 3
        connector = registry.resolve("TEST_RETRY")
        result = orch._execute_with_retry(action, connector)

        assert result.success is True
        assert action.attempts == 2

    def test_exhausted_after_all_retries_fail(self):
        registry = ConnectorRegistry()
        registry.register(AlwaysFailsConnector())
        orch = ActionOrchestrator(connector_registry=registry)

        action = make_action(action_type="TEST_FAIL")
        action.max_attempts = 3
        connector = registry.resolve("TEST_FAIL")
        orch._execute_with_retry(action, connector)

        assert action.status == ActionStatus.EXHAUSTED
        assert action.attempts == 3

    def test_exploding_connector_handled_gracefully(self):
        registry = ConnectorRegistry()
        registry.register(ExplodingConnector())
        orch = ActionOrchestrator(connector_registry=registry)

        action = make_action(action_type="TEST_EXPLODE")
        action.max_attempts = 1
        connector = registry.resolve("TEST_EXPLODE")
        result = orch._execute_with_retry(action, connector)

        assert result.success is False
        assert "exploded" in result.error

    def test_feedback_publisher_called_on_success(self):
        published = []

        def capture_feedback(app_id, event_type, payload):
            published.append((app_id, event_type, payload))

        orch = make_orchestrator(feedback_fn=capture_feedback)
        decision = make_decision(action_type=ActionType.SEND_EMAIL)
        orch.dispatch(decision)

        assert len(published) == 1
        assert published[0][1] == "ACTION_EXECUTED"
        assert published[0][2]["action_type"] == "SEND_EMAIL"

    def test_feedback_not_called_on_failure(self):
        published = []

        def capture_feedback(app_id, event_type, payload):
            published.append(payload)

        registry = ConnectorRegistry()
        registry.register(AlwaysFailsConnector())
        orch = ActionOrchestrator(connector_registry=registry, feedback_publisher=capture_feedback)

        action = make_action(action_type="TEST_FAIL")
        action.max_attempts = 1
        self.orchestrator._store_action(action)
        connector = registry.resolve("TEST_FAIL")
        orch._execute_with_retry(action, connector)

        assert len(published) == 0

    def test_dispatch_batch(self):
        decisions = [
            make_decision(action_type=ActionType.SEND_EMAIL, identity_id=f"id_{i}")
            for i in range(3)
        ]
        results = self.orchestrator.dispatch_batch(decisions)
        assert len(results) == 3
        assert all(r.success for r in results)

    def test_dispatch_batch_skips_non_executable(self):
        expired = make_decision(action_type=ActionType.SEND_EMAIL)
        expired.valid_until = datetime.now(timezone.utc) - timedelta(hours=1)
        valid = make_decision(action_type=ActionType.SEND_EMAIL, identity_id="id_valid")
        results = self.orchestrator.dispatch_batch([expired, valid])
        assert len(results) == 1

    def test_get_action(self):
        decision = make_decision(action_type=ActionType.SEND_EMAIL)
        result = self.orchestrator.dispatch(decision)
        fetched = self.orchestrator.get_action(result.action.id)
        assert fetched is not None
        assert fetched.id == result.action.id

    def test_get_actions_for_identity(self):
        for _ in range(3):
            self.orchestrator.dispatch(
                make_decision(action_type=ActionType.SEND_EMAIL, identity_id="identity_001")
            )
        actions = self.orchestrator.get_actions_for_identity("identity_001")
        assert len(actions) == 3

    def test_record_feedback(self):
        decision = make_decision(action_type=ActionType.SEND_EMAIL)
        result = self.orchestrator.dispatch(decision)
        action = self.orchestrator.record_feedback(
            result.action.id, "email_opened", {"at": "2024-01-01"}
        )
        assert action is not None
        assert "email_opened" in action.feedback

    def test_stats(self):
        self.orchestrator.dispatch(make_decision(action_type=ActionType.SEND_EMAIL))
        stats = self.orchestrator.stats()
        assert stats["total_dispatched"] == 1
        assert stats["total_succeeded"] == 1
        assert stats["success_rate"] == 1.0
        assert "email" in stats["connectors"]

    def test_action_context_populated_from_decision(self):
        decision = make_decision(action_type=ActionType.SEND_EMAIL)
        result = self.orchestrator.dispatch(decision)
        assert result.action.context.get("policy_name") == "Test Policy"
        assert result.action.context.get("churn_score") == 0.3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
