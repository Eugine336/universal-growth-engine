"""
Tests for the Audience Engine — rule evaluation, CRUD, dot-path field access.
"""

from __future__ import annotations

import pytest

from core.audience.engine import AudienceEngine
from core.audience.schema import (
    Audience,
    AudienceDefinition,
    AudienceRule,
    AudienceRuleGroup,
)
from core.behavior.repository import BehaviorRepository
from core.behavior.schema import BehavioralProfile, IntentSignal


def _repo_with_profiles() -> BehaviorRepository:
    repo = BehaviorRepository()

    p1 = BehavioralProfile(identity_id="user_001", application_id="app1")
    p1.engagement.tier = "power"
    p1.engagement.sessions_last_30d = 20
    p1.rfm.segment = "champions"
    p1.rfm.combined_score = 14
    p1.churn.risk_level = "low"
    p1.churn.risk_score = 0.1
    p1.traits["is_paying"] = True
    p1.traits["email"] = "alice@example.com"
    p1.traits["phone"] = "+254700111222"
    p1.set_intent_signal(IntentSignal(signal_type="purchase_intent", strength=0.9))
    repo.save(p1)

    p2 = BehavioralProfile(identity_id="user_002", application_id="app1")
    p2.engagement.tier = "active"
    p2.engagement.sessions_last_30d = 8
    p2.rfm.segment = "loyal"
    p2.rfm.combined_score = 10
    p2.churn.risk_level = "medium"
    p2.churn.risk_score = 0.45
    p2.traits["is_paying"] = True
    p2.traits["email"] = "bob@example.com"
    repo.save(p2)

    p3 = BehavioralProfile(identity_id="user_003", application_id="app1")
    p3.engagement.tier = "cold"
    p3.engagement.sessions_last_30d = 1
    p3.rfm.segment = "at_risk"
    p3.rfm.combined_score = 4
    p3.churn.risk_level = "high"
    p3.churn.risk_score = 0.8
    p3.traits["is_paying"] = False
    repo.save(p3)

    p4 = BehavioralProfile(identity_id="user_004", application_id="app1")
    p4.engagement.tier = "warming"
    p4.engagement.sessions_last_30d = 3
    p4.rfm.segment = "new"
    p4.rfm.combined_score = 6
    p4.churn.risk_level = "low"
    p4.churn.risk_score = 0.15
    p4.traits["is_paying"] = False
    p4.traits["email"] = "carol@example.com"
    repo.save(p4)

    return repo


class TestRuleEvaluation:

    def test_eq(self):
        repo = _repo_with_profiles()
        engine = AudienceEngine(repo)
        rule = AudienceRule(field="engagement.tier", operator="eq", value="power")
        p = list(repo._profiles.values())[0]  # user_001
        assert engine._evaluate_rule(p, rule) is True

    def test_neq(self):
        repo = _repo_with_profiles()
        engine = AudienceEngine(repo)
        rule = AudienceRule(field="engagement.tier", operator="neq", value="cold")
        p = list(repo._profiles.values())[0]
        assert engine._evaluate_rule(p, rule) is True

    def test_gt(self):
        repo = _repo_with_profiles()
        engine = AudienceEngine(repo)
        rule = AudienceRule(field="rfm.combined_score", operator="gt", value=12)
        p1 = repo.get("user_001", "app1")
        p3 = repo.get("user_003", "app1")
        assert engine._evaluate_rule(p1, rule) is True
        assert engine._evaluate_rule(p3, rule) is False

    def test_gte(self):
        repo = _repo_with_profiles()
        engine = AudienceEngine(repo)
        rule = AudienceRule(field="rfm.combined_score", operator="gte", value=14)
        p1 = repo.get("user_001", "app1")
        assert engine._evaluate_rule(p1, rule) is True

    def test_lt(self):
        repo = _repo_with_profiles()
        engine = AudienceEngine(repo)
        rule = AudienceRule(field="churn.risk_score", operator="lt", value=0.5)
        p1 = repo.get("user_001", "app1")
        p3 = repo.get("user_003", "app1")
        assert engine._evaluate_rule(p1, rule) is True
        assert engine._evaluate_rule(p3, rule) is False

    def test_lte(self):
        repo = _repo_with_profiles()
        engine = AudienceEngine(repo)
        rule = AudienceRule(field="churn.risk_score", operator="lte", value=0.1)
        p1 = repo.get("user_001", "app1")
        assert engine._evaluate_rule(p1, rule) is True

    def test_in(self):
        repo = _repo_with_profiles()
        engine = AudienceEngine(repo)
        rule = AudienceRule(
            field="engagement.tier",
            operator="in",
            value=["power", "active"],
        )
        p1 = repo.get("user_001", "app1")
        p3 = repo.get("user_003", "app1")
        assert engine._evaluate_rule(p1, rule) is True
        assert engine._evaluate_rule(p3, rule) is False

    def test_not_in(self):
        repo = _repo_with_profiles()
        engine = AudienceEngine(repo)
        rule = AudienceRule(
            field="engagement.tier",
            operator="not_in",
            value=["cold", "warming"],
        )
        p1 = repo.get("user_001", "app1")
        p3 = repo.get("user_003", "app1")
        assert engine._evaluate_rule(p1, rule) is True
        assert engine._evaluate_rule(p3, rule) is False

    def test_contains_string(self):
        repo = _repo_with_profiles()
        engine = AudienceEngine(repo)
        rule = AudienceRule(
            field="traits.email",
            operator="contains",
            value="alice",
        )
        p1 = repo.get("user_001", "app1")
        p2 = repo.get("user_002", "app1")
        assert engine._evaluate_rule(p1, rule) is True
        assert engine._evaluate_rule(p2, rule) is False

    def test_exists(self):
        repo = _repo_with_profiles()
        engine = AudienceEngine(repo)
        rule = AudienceRule(field="traits.email", operator="exists")
        p1 = repo.get("user_001", "app1")
        p3 = repo.get("user_003", "app1")
        assert engine._evaluate_rule(p1, rule) is True
        assert engine._evaluate_rule(p3, rule) is False

    def test_nonexistent_field_returns_false(self):
        repo = _repo_with_profiles()
        engine = AudienceEngine(repo)
        rule = AudienceRule(
            field="nonexistent.deep.path",
            operator="eq",
            value="anything",
        )
        p1 = repo.get("user_001", "app1")
        assert engine._evaluate_rule(p1, rule) is False

    def test_nonexistent_field_exists_returns_false(self):
        repo = _repo_with_profiles()
        engine = AudienceEngine(repo)
        rule = AudienceRule(field="traits.address", operator="exists")
        p1 = repo.get("user_001", "app1")
        assert engine._evaluate_rule(p1, rule) is False


class TestDotPathAccess:

    def test_engagement_tier(self):
        repo = _repo_with_profiles()
        engine = AudienceEngine(repo)
        p1 = repo.get("user_001", "app1")
        assert engine._get_field_value(p1, "engagement.tier") == "power"

    def test_rfm_combined_score(self):
        repo = _repo_with_profiles()
        engine = AudienceEngine(repo)
        p1 = repo.get("user_001", "app1")
        assert engine._get_field_value(p1, "rfm.combined_score") == 14

    def test_churn_risk_level(self):
        repo = _repo_with_profiles()
        engine = AudienceEngine(repo)
        p3 = repo.get("user_003", "app1")
        assert engine._get_field_value(p3, "churn.risk_level") == "high"

    def test_traits_dict(self):
        repo = _repo_with_profiles()
        engine = AudienceEngine(repo)
        p1 = repo.get("user_001", "app1")
        assert engine._get_field_value(p1, "traits.is_paying") is True

    def test_deep_nonexistent(self):
        repo = _repo_with_profiles()
        engine = AudienceEngine(repo)
        p1 = repo.get("user_001", "app1")
        assert engine._get_field_value(p1, "a.b.c.d") is None

    def test_identity_id(self):
        repo = _repo_with_profiles()
        engine = AudienceEngine(repo)
        p1 = repo.get("user_001", "app1")
        assert engine._get_field_value(p1, "identity_id") == "user_001"


class TestRuleGroups:

    def test_and_group(self):
        repo = _repo_with_profiles()
        engine = AudienceEngine(repo)
        group = AudienceRuleGroup(
            operator="AND",
            rules=[
                AudienceRule(field="engagement.tier", operator="eq", value="power"),
                AudienceRule(field="traits.is_paying", operator="eq", value=True),
            ],
        )
        p1 = repo.get("user_001", "app1")
        p3 = repo.get("user_003", "app1")
        assert engine._evaluate_group(p1, group) is True
        assert engine._evaluate_group(p3, group) is False

    def test_or_group(self):
        repo = _repo_with_profiles()
        engine = AudienceEngine(repo)
        group = AudienceRuleGroup(
            operator="OR",
            rules=[
                AudienceRule(field="engagement.tier", operator="eq", value="power"),
                AudienceRule(field="engagement.tier", operator="eq", value="cold"),
            ],
        )
        p1 = repo.get("user_001", "app1")
        p2 = repo.get("user_002", "app1")
        p3 = repo.get("user_003", "app1")
        assert engine._evaluate_group(p1, group) is True
        assert engine._evaluate_group(p2, group) is False
        assert engine._evaluate_group(p3, group) is True

    def test_empty_group_matches_all(self):
        repo = _repo_with_profiles()
        engine = AudienceEngine(repo)
        group = AudienceRuleGroup(operator="AND", rules=[])
        p1 = repo.get("user_001", "app1")
        assert engine._evaluate_group(p1, group) is True


class TestAudienceEvaluation:

    def test_empty_definition_matches_all(self):
        repo = _repo_with_profiles()
        engine = AudienceEngine(repo)
        definition = AudienceDefinition(name="all_users")
        result = engine.preview("plt1", definition)
        assert result["matching_count"] == 4

    def test_single_rule_filters(self):
        repo = _repo_with_profiles()
        engine = AudienceEngine(repo)
        definition = AudienceDefinition(
            name="power_users",
            groups=[
                AudienceRuleGroup(
                    operator="AND",
                    rules=[
                        AudienceRule(
                            field="engagement.tier",
                            operator="eq",
                            value="power",
                        ),
                    ],
                ),
            ],
        )
        result = engine.preview("plt1", definition)
        assert result["matching_count"] == 1
        assert "user_001" in result["sample_identity_ids"]

    def test_combined_groups_and(self):
        repo = _repo_with_profiles()
        engine = AudienceEngine(repo)
        definition = AudienceDefinition(
            name="paying_low_churn",
            groups=[
                AudienceRuleGroup(
                    operator="AND",
                    rules=[
                        AudienceRule(
                            field="traits.is_paying",
                            operator="eq",
                            value=True,
                        ),
                    ],
                ),
                AudienceRuleGroup(
                    operator="AND",
                    rules=[
                        AudienceRule(
                            field="churn.risk_level",
                            operator="eq",
                            value="low",
                        ),
                    ],
                ),
            ],
        )
        result = engine.preview("plt1", definition)
        assert result["matching_count"] == 1
        assert "user_001" in result["sample_identity_ids"]


class TestAudienceCRUD:

    def test_create_and_get(self):
        repo = BehaviorRepository()
        engine = AudienceEngine(repo)
        definition = AudienceDefinition(name="test_audience")
        audience = engine.create_audience("plt1", definition)
        assert audience.status == "active"
        assert audience.definition.name == "test_audience"
        fetched = engine.get_audience(audience.id)
        assert fetched is not None
        assert fetched.id == audience.id

    def test_list(self):
        repo = BehaviorRepository()
        engine = AudienceEngine(repo)
        engine.create_audience("plt1", AudienceDefinition(name="a1"))
        engine.create_audience("plt1", AudienceDefinition(name="a2"))
        engine.create_audience("plt2", AudienceDefinition(name="a3"))
        assert len(engine.list_audiences("plt1")) == 2
        assert len(engine.list_audiences("plt2")) == 1

    def test_update(self):
        repo = BehaviorRepository()
        engine = AudienceEngine(repo)
        audience = engine.create_audience(
            "plt1", AudienceDefinition(name="original")
        )
        updated = engine.update_audience(
            audience.id, AudienceDefinition(name="renamed")
        )
        assert updated.definition.name == "renamed"

    def test_update_nonexistent(self):
        repo = BehaviorRepository()
        engine = AudienceEngine(repo)
        assert engine.update_audience("fake", AudienceDefinition(name="x")) is None

    def test_archive(self):
        repo = BehaviorRepository()
        engine = AudienceEngine(repo)
        audience = engine.create_audience(
            "plt1", AudienceDefinition(name="to_archive")
        )
        archived = engine.archive_audience(audience.id)
        assert archived.status == "archived"
        assert len(engine.list_audiences("plt1")) == 0

    def test_archive_nonexistent(self):
        repo = BehaviorRepository()
        engine = AudienceEngine(repo)
        assert engine.archive_audience("fake") is None

    def test_get_nonexistent(self):
        repo = BehaviorRepository()
        engine = AudienceEngine(repo)
        assert engine.get_audience("fake") is None

    def test_evaluate_updates_member_count(self):
        repo = _repo_with_profiles()
        engine = AudienceEngine(repo)
        audience = engine.create_audience(
            "plt1",
            AudienceDefinition(
                name="paying",
                groups=[
                    AudienceRuleGroup(
                        rules=[
                            AudienceRule(
                                field="traits.is_paying",
                                operator="eq",
                                value=True,
                            )
                        ]
                    )
                ],
            ),
        )
        profiles = engine.evaluate(audience.id)
        assert len(profiles) == 2
        assert audience.member_count == 2
        assert audience.last_evaluated_at is not None

    def test_evaluate_nonexistent_returns_empty(self):
        repo = BehaviorRepository()
        engine = AudienceEngine(repo)
        assert engine.evaluate("fake") == []

    def test_stats(self):
        repo = BehaviorRepository()
        engine = AudienceEngine(repo)
        engine.create_audience("plt1", AudienceDefinition(name="a1"))
        engine.create_audience("plt1", AudienceDefinition(name="a2"))
        stats = engine.stats()
        assert stats["total_audiences"] == 2
        assert stats["by_status"]["active"] == 2
