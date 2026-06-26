"""
Unit Tests — core/entity

Tests cover:
- Entity schema, attributes, state, scoring, tags
- EntityRegistry type definitions and validation
- EntityStateMachine transitions
- EntityRepository CRUD, indexes, relationships
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest
from datetime import datetime, timezone

from core.entity.schema import (
    Entity, EntityType, EntityStatus, EntityRelationship, RelationshipType
)
from core.entity.registry import EntityRegistry, EntityTypeDefinition
from core.entity.state import EntityStateMachine, StateMachineDefinition, StateTransition
from core.entity.repository import EntityRepository


# ===========================================================================
# Fixtures
# ===========================================================================

def make_entity(type_name="Buyer", application_id="ucmc", **kwargs) -> Entity:
    return Entity(
        application_id=application_id,
        type=EntityType.CUSTOM,
        type_name=type_name,
        **kwargs
    )

def make_repo() -> EntityRepository:
    return EntityRepository()

def make_registry() -> EntityRegistry:
    return EntityRegistry()

def make_sm() -> EntityStateMachine:
    return EntityStateMachine()


# ===========================================================================
# Entity Schema Tests
# ===========================================================================

class TestEntitySchema:

    def test_entity_created_with_defaults(self):
        e = make_entity()
        assert e.id is not None
        assert e.status == EntityStatus.ACTIVE
        assert e.attributes == {}
        assert e.scores == {}

    def test_set_attribute_records_history(self):
        e = make_entity()
        e.set_attribute("display_name", "Acme Corp")
        assert e.attributes["display_name"] == "Acme Corp"
        assert len(e.attribute_history) == 1
        assert e.attribute_history[0].old_value is None
        assert e.attribute_history[0].new_value == "Acme Corp"

    def test_set_same_attribute_value_no_history(self):
        e = make_entity()
        e.set_attribute("name", "Alice")
        e.set_attribute("name", "Alice")
        assert len(e.attribute_history) == 1

    def test_set_attribute_change_records_old_value(self):
        e = make_entity()
        e.set_attribute("status_label", "pending")
        e.set_attribute("status_label", "active")
        assert e.attribute_history[1].old_value == "pending"
        assert e.attribute_history[1].new_value == "active"

    def test_set_attributes_bulk(self):
        e = make_entity()
        e.set_attributes({"name": "Bob", "country": "KE"})
        assert e.attributes["name"] == "Bob"
        assert e.attributes["country"] == "KE"

    def test_transition_state_records_history(self):
        e = make_entity()
        e.transition_state("onboarding")
        e.transition_state("active")
        assert e.state == "active"
        assert len(e.state_history) == 2
        assert e.state_history[1]["from"] == "onboarding"
        assert e.state_history[1]["to"] == "active"

    def test_set_and_get_score(self):
        e = make_entity()
        e.set_score("churn_probability", 0.72)
        assert e.get_score("churn_probability") == 0.72
        assert e.get_score("nonexistent", 0.0) == 0.0

    def test_add_and_remove_tags(self):
        e = make_entity()
        e.add_tag("high_value")
        e.add_tag("verified")
        assert e.has_tag("high_value")
        e.remove_tag("high_value")
        assert not e.has_tag("high_value")
        assert e.has_tag("verified")

    def test_duplicate_tag_not_added(self):
        e = make_entity()
        e.add_tag("vip")
        e.add_tag("vip")
        assert e.tags.count("vip") == 1

    def test_touch_updates_last_active(self):
        e = make_entity()
        assert e.last_active_at is None
        e.touch()
        assert e.last_active_at is not None

    def test_is_active(self):
        e = make_entity()
        assert e.is_active()
        e.status = EntityStatus.SUSPENDED
        assert not e.is_active()


# ===========================================================================
# Entity Registry Tests
# ===========================================================================

class TestEntityRegistry:

    def setup_method(self):
        self.registry = make_registry()

    def test_register_and_get_definition(self):
        self.registry.register(EntityTypeDefinition(
            application_id="ucmc",
            type_name="Seller",
            required_attributes=["display_name"],
            allowed_states=["onboarding", "active"],
            initial_state="onboarding",
            is_person=True,
        ))
        defn = self.registry.get("ucmc", "Seller")
        assert defn is not None
        assert defn.type_name == "Seller"
        assert defn.is_person is True

    def test_unregistered_type_returns_none(self):
        assert self.registry.get("ucmc", "UnknownType") is None

    def test_validate_entity_passes_with_required_attrs(self):
        self.registry.register(EntityTypeDefinition(
            application_id="ucmc",
            type_name="Buyer",
            required_attributes=["email"],
        ))
        e = make_entity(type_name="Buyer")
        e.set_attribute("email", "buyer@test.com")
        result = self.registry.validate_entity(e)
        assert result.valid is True

    def test_validate_entity_fails_missing_required_attr(self):
        self.registry.register(EntityTypeDefinition(
            application_id="ucmc",
            type_name="Buyer",
            required_attributes=["email"],
        ))
        e = make_entity(type_name="Buyer")
        result = self.registry.validate_entity(e)
        assert result.valid is False
        assert any("email" in err for err in result.errors)

    def test_validate_entity_fails_invalid_state(self):
        self.registry.register(EntityTypeDefinition(
            application_id="ucmc",
            type_name="Buyer",
            allowed_states=["onboarding", "active"],
        ))
        e = make_entity(type_name="Buyer")
        e.transition_state("banned")
        result = self.registry.validate_entity(e)
        assert result.valid is False

    def test_validate_entity_warns_no_definition(self):
        e = make_entity(type_name="NoDefinitionType")
        result = self.registry.validate_entity(e)
        assert result.valid is True
        assert len(result.warnings) > 0

    def test_list_for_application(self):
        self.registry.register(EntityTypeDefinition(application_id="ucmc", type_name="Buyer"))
        self.registry.register(EntityTypeDefinition(application_id="ucmc", type_name="Seller"))
        self.registry.register(EntityTypeDefinition(application_id="trading", type_name="Trader"))
        ucmc_types = self.registry.list_for_application("ucmc")
        names = [d.type_name for d in ucmc_types]
        assert "Buyer" in names
        assert "Seller" in names
        assert "Trader" not in names

    def test_initial_state_for(self):
        self.registry.register(EntityTypeDefinition(
            application_id="ucmc",
            type_name="Seller",
            initial_state="onboarding",
        ))
        assert self.registry.initial_state_for("ucmc", "Seller") == "onboarding"
        assert self.registry.initial_state_for("ucmc", "NoType") is None

    def test_is_person_type(self):
        self.registry.register(EntityTypeDefinition(
            application_id="ucmc",
            type_name="Seller",
            is_person=True,
        ))
        assert self.registry.is_person_type("ucmc", "Seller") is True
        assert self.registry.is_person_type("ucmc", "Service") is False


# ===========================================================================
# Entity State Machine Tests
# ===========================================================================

class TestEntityStateMachine:

    def setup_method(self):
        self.sm = make_sm()
        self.sm.register(StateMachineDefinition(
            application_id="ucmc",
            type_name="Seller",
            initial_state="onboarding",
            states=["onboarding", "active", "suspended"],
            transitions=[
                StateTransition(
                    from_state="onboarding",
                    to_state="active",
                    trigger_events=["KYC_COMPLETED"],
                ),
                StateTransition(
                    from_state="active",
                    to_state="suspended",
                    trigger_events=["DISPUTE_OPENED"],
                ),
                StateTransition(
                    from_state="suspended",
                    to_state="active",
                    trigger_events=["DISPUTE_RESOLVED"],
                ),
            ]
        ))

    def test_initialize_state(self):
        e = make_entity(type_name="Seller")
        assert e.state is None
        self.sm.initialize_state(e)
        assert e.state == "onboarding"

    def test_valid_transition(self):
        e = make_entity(type_name="Seller")
        self.sm.initialize_state(e)
        result = self.sm.process_event(e, "KYC_COMPLETED")
        assert result.success is True
        assert e.state == "active"
        assert result.from_state == "onboarding"
        assert result.to_state == "active"

    def test_invalid_transition_returns_failure(self):
        e = make_entity(type_name="Seller")
        self.sm.initialize_state(e)
        result = self.sm.process_event(e, "PAYMENT_COMPLETED")
        assert result.success is False
        assert e.state == "onboarding"

    def test_chained_transitions(self):
        e = make_entity(type_name="Seller")
        self.sm.initialize_state(e)
        self.sm.process_event(e, "KYC_COMPLETED")
        self.sm.process_event(e, "DISPUTE_OPENED")
        assert e.state == "suspended"
        self.sm.process_event(e, "DISPUTE_RESOLVED")
        assert e.state == "active"

    def test_no_machine_returns_failure(self):
        e = make_entity(type_name="UnknownType")
        result = self.sm.process_event(e, "SOME_EVENT")
        assert result.success is False

    def test_conditional_transition(self):
        self.sm.register(StateMachineDefinition(
            application_id="ucmc",
            type_name="ConditionalEntity",
            initial_state="pending",
            states=["pending", "approved"],
            transitions=[
                StateTransition(
                    from_state="pending",
                    to_state="approved",
                    trigger_events=["REVIEW_PASSED"],
                    condition=lambda e: e.get_attribute("score", 0) >= 80,
                )
            ]
        ))
        e = make_entity(type_name="ConditionalEntity")
        self.sm.initialize_state(e)

        # Condition fails — score too low
        e.set_attribute("score", 50)
        result = self.sm.process_event(e, "REVIEW_PASSED")
        assert result.success is False

        # Condition passes
        e.set_attribute("score", 90)
        result = self.sm.process_event(e, "REVIEW_PASSED")
        assert result.success is True
        assert e.state == "approved"

    def test_builtin_user_state_machine(self):
        e = make_entity(type_name="User")
        self.sm.initialize_state(e)
        assert e.state == "registered"
        result = self.sm.process_event(e, "SESSION_STARTED")
        assert result.success is True
        assert e.state == "active"


# ===========================================================================
# Entity Repository Tests
# ===========================================================================

class TestEntityRepository:

    def setup_method(self):
        self.repo = make_repo()

    def test_save_and_get(self):
        e = make_entity()
        self.repo.save(e)
        fetched = self.repo.get(e.id)
        assert fetched is not None
        assert fetched.id == e.id

    def test_get_nonexistent_returns_none(self):
        assert self.repo.get("nonexistent") is None

    def test_delete(self):
        e = make_entity()
        self.repo.save(e)
        self.repo.delete(e.id)
        assert self.repo.get(e.id) is None

    def test_soft_delete_marks_status(self):
        e = make_entity()
        self.repo.save(e)
        self.repo.soft_delete(e.id)
        assert self.repo.get(e.id).status == EntityStatus.DELETED

    def test_find_by_application_and_type(self):
        e1 = make_entity(type_name="Buyer", application_id="ucmc")
        e2 = make_entity(type_name="Seller", application_id="ucmc")
        e3 = make_entity(type_name="Buyer", application_id="trading")
        for e in [e1, e2, e3]:
            self.repo.save(e)
        buyers = self.repo.find_by_application_and_type("ucmc", "Buyer")
        assert len(buyers) == 1
        assert buyers[0].id == e1.id

    def test_find_by_identity(self):
        e = make_entity(identity_id="identity_abc")
        self.repo.save(e)
        found = self.repo.find_by_identity("identity_abc")
        assert len(found) == 1
        assert found[0].id == e.id

    def test_find_by_state(self):
        e = make_entity()
        e.transition_state("active")
        self.repo.save(e)
        found = self.repo.find_by_state("ucmc", "Buyer", "active")
        assert len(found) == 1

    def test_find_by_tag(self):
        e = make_entity()
        e.add_tag("vip")
        self.repo.save(e)
        found = self.repo.find_by_tag("vip")
        assert len(found) == 1

    def test_find_by_attribute(self):
        e = make_entity()
        e.set_attribute("country", "KE")
        self.repo.save(e)
        found = self.repo.find_by_attribute("ucmc", "Buyer", "country", "KE")
        assert len(found) == 1

    def test_save_relationship(self):
        rel = EntityRelationship(
            source_id="user_001",
            source_type="User",
            relationship_type=RelationshipType.OWNS,
            target_id="portfolio_001",
            target_type="Portfolio",
            application_id="trading",
        )
        self.repo.save_relationship(rel)
        rels = self.repo.get_relationships_from("user_001")
        assert len(rels) == 1
        assert rels[0].target_id == "portfolio_001"

    def test_get_relationships_to(self):
        rel = EntityRelationship(
            source_id="seller_001",
            source_type="Seller",
            relationship_type=RelationshipType.SELLS,
            target_id="service_001",
            target_type="Service",
            application_id="ucmc",
        )
        self.repo.save_relationship(rel)
        rels = self.repo.get_relationships_to("service_001")
        assert len(rels) == 1

    def test_delete_relationship(self):
        rel = EntityRelationship(
            source_id="a",
            source_type="User",
            relationship_type=RelationshipType.FOLLOWS,
            target_id="b",
            target_type="Organization",
            application_id="ucmc",
        )
        self.repo.save_relationship(rel)
        self.repo.delete_relationship(rel.id)
        assert self.repo.get_relationship(rel.id) is None

    def test_count(self):
        for _ in range(3):
            self.repo.save(make_entity(type_name="Buyer"))
        for _ in range(2):
            self.repo.save(make_entity(type_name="Seller"))
        assert self.repo.count(application_id="ucmc") == 5
        assert self.repo.count(application_id="ucmc", type_name="Buyer") == 3

    def test_stats(self):
        self.repo.save(make_entity())
        stats = self.repo.stats()
        assert stats["total_entities"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
