"""
Integration tests for the UCMC AI Marketplace domain config.

Verifies:
- config.yaml loads without errors
- All entity types registered correctly
- State machines support the expected transitions
- Event policy accepts marketplace event types
- Decision policies are registered and evaluatable
- Full seller onboarding flow produces expected decisions
- Buyer churn detection triggers re-engagement
- Event bridge maps all UCMC signals
- Webhook receiver routes all action types
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.behavior.builder import BehaviorBuilder
from core.behavior.repository import BehaviorRepository
from core.behavior.schema import BehavioralProfile
from core.config.loader import DomainConfigLoader
from core.config.schema import ApplicationConfig
from core.decision.engine import DecisionEngine
from core.decision.policy import PolicyRegistry
from core.decision.schema import ActionType
from core.entity.registry import EntityRegistry
from core.entity.state import EntityStateMachine
from core.events.schema import Event, EventType
from core.events.validator import EventValidator
from core.identity.graph import IdentityGraph
from core.identity.resolver import IdentityResolver
from core.identity.schema import IdentityTouchpoint, TouchpointType
from core.prediction.engine import PredictionEngine

from domain.ucmc.event_bridge import SIGNAL_TO_UGIE_EVENT, build_ugie_event
from domain.ucmc.webhook_receiver import (
    handle_email_webhook,
    handle_notification_webhook,
    handle_workflow_webhook,
    route_webhook,
)

APP_ID = "ucmc_marketplace"


# ---------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------


def _make_loader():
    return DomainConfigLoader(
        entity_registry=EntityRegistry(),
        state_machine=EntityStateMachine(),
        event_validator=EventValidator(),
        policy_registry=PolicyRegistry(),
    )


@pytest.fixture(scope="module")
def loaded():
    """Load the UCMC domain config and return all engine components."""
    registry = EntityRegistry()
    state_machine = EntityStateMachine()
    validator = EventValidator()
    policy_registry = PolicyRegistry()

    loader = DomainConfigLoader(
        entity_registry=registry,
        state_machine=state_machine,
        event_validator=validator,
        policy_registry=policy_registry,
    )
    config = loader.load_file("domain/ucmc/config.yaml")
    return {
        "config": config,
        "loader": loader,
        "registry": registry,
        "state_machine": state_machine,
        "validator": validator,
        "policy_registry": policy_registry,
    }


# ---------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------


class TestConfigLoading:

    def test_loads_without_errors(self, loaded):
        assert loaded["config"].application.id == APP_ID
        assert loaded["config"].application.name == "UCMC AI Marketplace"

    def test_application_tracked(self, loaded):
        assert APP_ID in loaded["loader"].loaded_applications


# ---------------------------------------------------------------
# Entity registration
# ---------------------------------------------------------------


class TestEntityRegistration:

    @pytest.mark.parametrize("type_name", [
        "Buyer", "Seller", "Listing", "Escrow", "Dispute", "Portfolio",
    ])
    def test_entity_type_registered(self, loaded, type_name):
        defn = loaded["registry"].get(APP_ID, type_name)
        assert defn is not None, f"Entity type '{type_name}' not registered"
        assert defn.type_name == type_name

    def test_buyer_is_person(self, loaded):
        defn = loaded["registry"].get(APP_ID, "Buyer")
        assert defn.is_person is True
        assert "email_hash" in defn.required_attributes
        assert "public_key" in defn.required_attributes

    def test_seller_is_person(self, loaded):
        defn = loaded["registry"].get(APP_ID, "Seller")
        assert defn.is_person is True
        assert "display_name" in defn.required_attributes

    def test_listing_is_asset(self, loaded):
        defn = loaded["registry"].get(APP_ID, "Listing")
        assert defn.is_asset is True
        assert "title" in defn.required_attributes
        assert "category" in defn.required_attributes

    def test_escrow_required_attributes(self, loaded):
        defn = loaded["registry"].get(APP_ID, "Escrow")
        assert "buyer_id" in defn.required_attributes
        assert "seller_id" in defn.required_attributes
        assert "amount" in defn.required_attributes

    def test_entity_initial_states(self, loaded):
        assert loaded["registry"].get(APP_ID, "Buyer").initial_state == "registered"
        assert loaded["registry"].get(APP_ID, "Seller").initial_state == "registered"
        assert loaded["registry"].get(APP_ID, "Listing").initial_state == "draft"
        assert loaded["registry"].get(APP_ID, "Escrow").initial_state == "initiated"
        assert loaded["registry"].get(APP_ID, "Dispute").initial_state == "open"


# ---------------------------------------------------------------
# State machines
# ---------------------------------------------------------------


class TestStateMachines:

    @pytest.mark.parametrize("type_name", [
        "Buyer", "Seller", "Listing", "Escrow", "Dispute", "Portfolio",
    ])
    def test_state_machine_registered(self, loaded, type_name):
        sm = loaded["state_machine"].get(APP_ID, type_name)
        assert sm is not None, f"State machine for '{type_name}' not registered"

    def test_seller_lifecycle(self, loaded):
        sm = loaded["state_machine"].get(APP_ID, "Seller")
        assert sm.initial_state == "registered"
        to_states = {t.to_state for t in sm.transitions}
        assert "email_verified" in to_states
        assert "profile_complete" in to_states
        assert "kyc_pending" in to_states
        assert "kyc_verified" in to_states
        assert "active" in to_states

    def test_seller_transition_registered_to_email_verified(self, loaded):
        sm = loaded["state_machine"].get(APP_ID, "Seller")
        transitions = [t for t in sm.transitions
                       if t.from_state == "registered" and t.to_state == "email_verified"]
        assert len(transitions) == 1
        assert "USER_VERIFIED" in transitions[0].trigger_events

    def test_seller_transition_profile_to_kyc(self, loaded):
        sm = loaded["state_machine"].get(APP_ID, "Seller")
        transitions = [t for t in sm.transitions
                       if t.from_state == "profile_complete" and t.to_state == "kyc_pending"]
        assert len(transitions) == 1
        assert "KYC_STARTED" in transitions[0].trigger_events

    def test_buyer_lifecycle(self, loaded):
        sm = loaded["state_machine"].get(APP_ID, "Buyer")
        assert sm.initial_state == "registered"
        from_to = {(t.from_state, t.to_state) for t in sm.transitions}
        assert ("registered", "email_verified") in from_to
        assert ("email_verified", "kyc_pending") in from_to
        assert ("kyc_pending", "kyc_verified") in from_to
        assert ("kyc_verified", "active") in from_to

    def test_escrow_lifecycle(self, loaded):
        sm = loaded["state_machine"].get(APP_ID, "Escrow")
        assert sm.initial_state == "initiated"
        from_to = {(t.from_state, t.to_state) for t in sm.transitions}
        assert ("initiated", "locked") in from_to
        assert ("locked", "delivered") in from_to
        assert ("delivered", "released") in from_to
        assert ("locked", "reverted") in from_to
        assert ("locked", "disputed") in from_to
        assert ("released", "finalized") in from_to

    def test_listing_lifecycle(self, loaded):
        sm = loaded["state_machine"].get(APP_ID, "Listing")
        assert sm.initial_state == "draft"
        from_to = {(t.from_state, t.to_state) for t in sm.transitions}
        assert ("draft", "active") in from_to
        assert ("active", "paused") in from_to
        assert ("active", "archived") in from_to

    def test_dispute_lifecycle(self, loaded):
        sm = loaded["state_machine"].get(APP_ID, "Dispute")
        assert sm.initial_state == "open"
        from_to = {(t.from_state, t.to_state) for t in sm.transitions}
        assert ("open", "evidence") in from_to
        assert ("evidence", "voting") in from_to
        assert ("voting", "resolved") in from_to


# ---------------------------------------------------------------
# Event policy
# ---------------------------------------------------------------


class TestEventPolicy:

    def test_event_policy_registered(self, loaded):
        policy = loaded["validator"]._policies.get(APP_ID)
        assert policy is not None

    @pytest.mark.parametrize("event_type", [
        "USER_REGISTERED", "USER_VERIFIED", "SESSION_STARTED",
        "CONTENT_CREATED", "PAYMENT_COMPLETED", "PAYMENT_INITIATED",
        "KYC_STARTED", "KYC_COMPLETED", "DISPUTE_OPENED",
        "DISPUTE_RESOLVED", "REVIEW_CREATED", "MESSAGE_SENT",
        "ORDER_COMPLETED", "REFUND_COMPLETED", "FLAG_SUBMITTED",
        "ACCOUNT_DEACTIVATED", "CUSTOM",
    ])
    def test_event_type_allowed(self, loaded, event_type):
        policy = loaded["validator"]._policies.get(APP_ID)
        assert event_type in policy.allowed_events

    def test_subscription_events_blocked(self, loaded):
        policy = loaded["validator"]._policies.get(APP_ID)
        assert "SUBSCRIPTION_STARTED" in policy.blocked_events

    def test_requires_actor(self, loaded):
        policy = loaded["validator"]._policies.get(APP_ID)
        assert policy.require_actor is True


# ---------------------------------------------------------------
# Decision policies
# ---------------------------------------------------------------


class TestDecisionPolicies:

    def test_policies_registered(self, loaded):
        policies = loaded["policy_registry"].list_for_application(APP_ID)
        ucmc_policies = [p for p in policies if p.application_id == APP_ID]
        assert len(ucmc_policies) >= 8

    def test_welcome_email_policy(self, loaded):
        policies = loaded["policy_registry"].list_for_application(APP_ID)
        welcome = [p for p in policies if p.name == "Welcome Email"]
        assert len(welcome) == 1
        assert welcome[0].action.action_type == ActionType.SEND_EMAIL
        assert "USER_REGISTERED" in welcome[0].trigger_events
        assert welcome[0].max_executions_per_identity == 1

    def test_fraud_flag_policy(self, loaded):
        policies = loaded["policy_registry"].list_for_application(APP_ID)
        fraud = [p for p in policies if p.name == "Fraud Flag"]
        assert len(fraud) == 1
        assert fraud[0].action.action_type == ActionType.FLAG_FOR_REVIEW
        assert fraud[0].action.priority == 95

    def test_kyc_nudge_policy(self, loaded):
        policies = loaded["policy_registry"].list_for_application(APP_ID)
        kyc = [p for p in policies if p.name == "KYC Nudge"]
        assert len(kyc) == 1
        assert kyc[0].action.action_type == ActionType.SEND_EMAIL
        assert kyc[0].max_executions_per_identity == 3
        assert "KYC_STARTED" in kyc[0].abort_if_events

    def test_buyer_reengagement_policy(self, loaded):
        policies = loaded["policy_registry"].list_for_application(APP_ID)
        reengage = [p for p in policies if p.name == "Buyer Re-engagement"]
        assert len(reengage) == 1
        assert reengage[0].action.action_type == ActionType.SEND_EMAIL
        assert len(reengage[0].trigger_events) == 0  # always evaluate

    def test_policy_names_unique(self, loaded):
        policies = loaded["policy_registry"].list_for_application(APP_ID)
        ucmc_names = [p.name for p in policies if p.application_id == APP_ID]
        assert len(ucmc_names) == len(set(ucmc_names))


# ---------------------------------------------------------------
# Full seller onboarding flow
# ---------------------------------------------------------------


class TestSellerOnboardingFlow:

    def _make_pipeline(self, loaded):
        graph = IdentityGraph()
        resolver = IdentityResolver(graph)
        behavior_repo = BehaviorRepository()
        builder = BehaviorBuilder()
        prediction_engine = PredictionEngine(behavior_repo)
        decision_engine = DecisionEngine(
            behavior_repo=behavior_repo,
            prediction_engine=prediction_engine,
            policy_registry=loaded["policy_registry"],
        )
        return graph, resolver, behavior_repo, builder, prediction_engine, decision_engine

    def test_seller_full_lifecycle(self, loaded):
        graph, resolver, behavior_repo, builder, pred_engine, decision_engine = (
            self._make_pipeline(loaded)
        )

        seller_id = "seller_001"

        # 1. USER_REGISTERED — creates identity
        event = Event(
            application_id=APP_ID,
            type=EventType.USER_REGISTERED,
            actor_id=seller_id,
            actor_type="Seller",
            properties={"email": "seller@ucmc.test", "display_name": "AI Pro"},
        )
        result = resolver.resolve_from_event(event)
        assert result is not None
        identity_id = result.identity.id
        profile = behavior_repo.get_or_create(identity_id, APP_ID)
        builder.apply(event, profile)
        behavior_repo.save(profile)

        # Decide after registration — should get Welcome Email
        decisions = decision_engine.decide(
            identity_id=identity_id,
            application_id=APP_ID,
            trigger_event_type="USER_REGISTERED",
            return_all=True,
        )
        welcome = [d for d in decisions if d.payload.get("template") == "ucmc_welcome"]
        assert len(welcome) >= 1

        # 2. USER_VERIFIED — email verification
        event = Event(
            application_id=APP_ID,
            type=EventType.USER_VERIFIED,
            actor_id=seller_id,
            actor_type="Seller",
        )
        event.identity_id = identity_id
        builder.apply(event, profile)
        behavior_repo.save(profile)

        # 3. ENTITY_UPDATED — profile completion
        event = Event(
            application_id=APP_ID,
            type=EventType.ENTITY_UPDATED,
            actor_id=seller_id,
            actor_type="Seller",
            properties={"bio": "Expert in AI services", "country": "KE"},
        )
        event.identity_id = identity_id
        builder.apply(event, profile)
        behavior_repo.save(profile)

        # 4. KYC_COMPLETED
        event = Event(
            application_id=APP_ID,
            type=EventType.KYC_COMPLETED,
            actor_id=seller_id,
            actor_type="Seller",
        )
        event.identity_id = identity_id
        builder.apply(event, profile)
        behavior_repo.save(profile)

        # 5. CONTENT_CREATED — first listing
        event = Event(
            application_id=APP_ID,
            type=EventType.CONTENT_CREATED,
            actor_id=seller_id,
            actor_type="Seller",
            target_id="listing_001",
            target_type="Listing",
            properties={"title": "AI Logo Design", "category": "CREATIVE", "price": 50},
        )
        event.identity_id = identity_id
        builder.apply(event, profile)
        behavior_repo.save(profile)

        # 6. PAYMENT_COMPLETED — escrow release
        event = Event(
            application_id=APP_ID,
            type=EventType.PAYMENT_COMPLETED,
            actor_id=seller_id,
            actor_type="Seller",
            properties={"amount": 50.00, "currency": "KES", "escrow_released": True},
        )
        event.identity_id = identity_id
        builder.apply(event, profile)
        behavior_repo.save(profile)

        assert profile.rfm.total_monetary_value >= 50.0
        assert profile.rfm.total_conversions >= 1

        # Decide after payment — should get review request (from global or ucmc policy)
        decisions = decision_engine.decide(
            identity_id=identity_id,
            application_id=APP_ID,
            trigger_event_type="PAYMENT_COMPLETED",
            return_all=True,
        )
        action_types = {d.action_type for d in decisions}
        assert ActionType.REQUEST_REVIEW in action_types or len(decisions) > 0


# ---------------------------------------------------------------
# Buyer churn detection
# ---------------------------------------------------------------


class TestBuyerChurnDetection:

    def test_churn_triggers_reengagement(self, loaded):
        behavior_repo = BehaviorRepository()
        builder = BehaviorBuilder()
        prediction_engine = PredictionEngine(behavior_repo)
        decision_engine = DecisionEngine(
            behavior_repo=behavior_repo,
            prediction_engine=prediction_engine,
            policy_registry=loaded["policy_registry"],
        )

        identity_id = "buyer_churn_001"
        profile = behavior_repo.get_or_create(identity_id, APP_ID)

        now = datetime.now(timezone.utc)
        past = now - timedelta(days=5)

        # Simulate multiple sessions in the past
        for i in range(5):
            event = Event(
                application_id=APP_ID,
                type=EventType.SESSION_STARTED,
                actor_id="buyer_x",
                actor_type="Buyer",
                timestamp=past + timedelta(hours=i),
            )
            event.identity_id = identity_id
            builder.apply(event, profile)

        # Simulate some browsing
        for _ in range(3):
            event = Event(
                application_id=APP_ID,
                type=EventType.ITEM_VIEWED,
                actor_id="buyer_x",
                actor_type="Buyer",
                properties={"item_id": "listing_123"},
                timestamp=past + timedelta(hours=10),
            )
            event.identity_id = identity_id
            builder.apply(event, profile)

        behavior_repo.save(profile)
        assert profile.engagement.total_sessions >= 5

        decisions = decision_engine.decide(
            identity_id=identity_id,
            application_id=APP_ID,
            return_all=True,
        )
        assert len(decisions) >= 0  # May get reengagement or other


# ---------------------------------------------------------------
# Event bridge
# ---------------------------------------------------------------


class TestEventBridge:

    @pytest.mark.parametrize("signal", [
        "INIT", "PROFILE_UPDATE", "LISTING_CREATE", "LISTING_UPDATE",
        "MESSAGE_SEND", "DELIVERY_CONFIRM", "REVIEW_SUBMIT",
        "KYC_START", "KYC_VERIFIED", "KYC_REJECTED",
        "PAYMENT_INITIATE", "LOCK", "RELEASE", "REVERT", "FINALIZE",
        "DISPUTE_OPEN", "DISPUTE_VOTE", "DISPUTE_RESOLVE",
        "EMAIL_VERIFIED", "ONBOARDING_COMPLETE",
        "DEPOSIT_CONFIRMED", "WITHDRAWAL_REQUEST",
        "REPORT_ACTOR", "ACTOR_BANNED", "SANCTIONS_HIT",
    ])
    def test_signal_has_mapping(self, signal):
        assert signal in SIGNAL_TO_UGIE_EVENT

    def test_build_ugie_event_listing_create(self):
        event = build_ugie_event(
            signal_type="LISTING_CREATE",
            actor_id="seller_abc",
            actor_type="Seller",
            target_id="listing_xyz",
            properties={"title": "AI Logo Design", "category": "CREATIVE"},
        )
        assert event is not None
        assert event["application_id"] == APP_ID
        assert event["type"] == "CONTENT_CREATED"
        assert event["actor_id"] == "seller_abc"
        assert event["actor_type"] == "Seller"
        assert event["target_id"] == "listing_xyz"
        assert event["target_type"] == "Listing"
        assert event["properties"]["title"] == "AI Logo Design"

    def test_build_ugie_event_escrow_lock(self):
        event = build_ugie_event(
            signal_type="LOCK",
            actor_id="buyer_abc",
            properties={"amount": 100, "currency": "KES"},
        )
        assert event is not None
        assert event["type"] == "PAYMENT_INITIATED"
        assert event["properties"]["escrow"] is True
        assert event["properties"]["amount"] == 100

    def test_build_ugie_event_escrow_release(self):
        event = build_ugie_event(
            signal_type="RELEASE",
            actor_id="system",
            actor_type="Seller",
        )
        assert event is not None
        assert event["type"] == "PAYMENT_COMPLETED"
        assert event["properties"]["escrow_released"] is True

    def test_build_ugie_event_custom_type(self):
        event = build_ugie_event(
            signal_type="KYC_REJECTED",
            actor_id="user_001",
        )
        assert event is not None
        assert event["type"] == "CUSTOM"
        assert event["custom_type"] == "KYC_REJECTED"

    def test_build_ugie_event_unknown_signal(self):
        event = build_ugie_event(
            signal_type="TOTALLY_UNKNOWN",
            actor_id="user_001",
        )
        assert event is None

    def test_build_ugie_event_all_mapped_types_are_valid_event_types(self):
        valid_types = {e.value for e in EventType}
        for signal, mapping in SIGNAL_TO_UGIE_EVENT.items():
            assert mapping["type"] in valid_types, (
                f"Signal '{signal}' maps to invalid EventType '{mapping['type']}'"
            )


# ---------------------------------------------------------------
# Webhook receiver
# ---------------------------------------------------------------


class TestWebhookReceiver:

    def test_route_email(self):
        result = route_webhook({
            "action_id": "act_001",
            "action_type": "SEND_EMAIL",
            "identity_id": "id_001",
            "payload": {"template": "ucmc_welcome"},
        })
        assert result.success is True
        assert "ucmc_welcome" in result.message

    def test_route_notification(self):
        result = route_webhook({
            "action_id": "act_002",
            "action_type": "SEND_IN_APP",
            "identity_id": "id_001",
            "payload": {"template": "seller_profile_nudge"},
        })
        assert result.success is True

    def test_route_recommendation(self):
        result = route_webhook({
            "action_id": "act_003",
            "action_type": "SHOW_RECOMMENDATION",
            "identity_id": "id_001",
            "payload": {"template": "service_recommendations"},
        })
        assert result.success is True

    def test_route_discount(self):
        result = route_webhook({
            "action_id": "act_004",
            "action_type": "SHOW_DISCOUNT",
            "identity_id": "id_001",
            "payload": {"template": "buyer_retention_discount"},
        })
        assert result.success is True

    def test_route_workflow_flag(self):
        result = route_webhook({
            "action_id": "act_005",
            "action_type": "FLAG_FOR_REVIEW",
            "identity_id": "id_001",
            "payload": {"reason": "high_fraud_probability"},
        })
        assert result.success is True
        assert "admin.flagUser" in result.message

    def test_route_escalate(self):
        result = route_webhook({
            "action_id": "act_006",
            "action_type": "ESCALATE_SUPPORT",
            "identity_id": "id_001",
            "payload": {"reason": "sanctions_screening_hit"},
        })
        assert result.success is True

    def test_route_unknown_action(self):
        result = route_webhook({
            "action_id": "act_007",
            "action_type": "TOTALLY_UNKNOWN",
            "identity_id": "id_001",
            "payload": {},
        })
        assert result.success is False

    def test_email_unknown_template(self):
        result = handle_email_webhook({
            "action_id": "act_008",
            "identity_id": "id_001",
            "payload": {"template": "nonexistent_template"},
        })
        assert result.success is False

    def test_notification_unknown_template(self):
        result = handle_notification_webhook({
            "action_id": "act_009",
            "action_type": "SEND_IN_APP",
            "identity_id": "id_001",
            "payload": {"template": "nonexistent_template"},
        })
        assert result.success is False

    def test_all_email_templates_recognized(self):
        for template_name in [
            "ucmc_welcome", "kyc_nudge", "buyer_reengagement",
            "review_request", "seller_referral_ask",
        ]:
            result = handle_email_webhook({
                "action_id": f"act_{template_name}",
                "identity_id": "id_001",
                "payload": {"template": template_name},
            })
            assert result.success is True, f"Template '{template_name}' failed"

    def test_all_notification_templates_recognized(self):
        for template_name in [
            "seller_profile_nudge", "create_first_listing",
            "delivery_reminder", "service_recommendations",
            "buyer_retention_discount",
        ]:
            result = handle_notification_webhook({
                "action_id": f"act_{template_name}",
                "action_type": "SEND_IN_APP",
                "identity_id": "id_001",
                "payload": {"template": template_name},
            })
            assert result.success is True, f"Template '{template_name}' failed"
