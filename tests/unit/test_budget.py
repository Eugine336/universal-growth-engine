"""Unit tests for the Budget Allocator Engine."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from core.budget.engine import BudgetAllocator
from core.budget.schema import (
    BudgetPlan,
    Channel,
    ChannelBudget,
    ChannelPerformance,
    ReallocationEvent,
)


@pytest.fixture()
def allocator():
    return BudgetAllocator()


class TestCreatePlan:

    def test_basic_plan(self, allocator):
        plan = allocator.create_plan(
            platform_id="test",
            total_budget=1000.0,
        )
        assert plan.platform_id == "test"
        assert plan.total_budget == 1000.0
        assert plan.period == "monthly"
        assert plan.auto_optimize is True
        assert plan.status == "active"
        assert plan.id

    def test_with_channel_allocations(self, allocator):
        plan = allocator.create_plan(
            platform_id="test",
            total_budget=1000.0,
            channel_allocations={
                "email": 300.0,
                "meta_ads": 500.0,
                "referral": 200.0,
            },
        )
        assert len(plan.channel_budgets) == 3
        assert plan.channel_budgets["email"].allocated_budget == 300.0
        assert plan.channel_budgets["meta_ads"].allocated_budget == 500.0
        assert plan.channel_budgets["referral"].allocated_budget == 200.0

    def test_with_channel_configs(self, allocator):
        plan = allocator.create_plan(
            platform_id="test",
            total_budget=1000.0,
            channel_allocations={"email": 500.0, "sms": 500.0},
            channel_configs={
                "email": {"auto_pause_threshold": 50.0, "min_budget": 100.0},
                "sms": {"auto_pause_threshold": 80.0},
            },
        )
        assert plan.channel_budgets["email"].auto_pause_threshold == 50.0
        assert plan.channel_budgets["email"].min_budget == 100.0
        assert plan.channel_budgets["sms"].auto_pause_threshold == 80.0

    def test_custom_strategy(self, allocator):
        plan = allocator.create_plan(
            platform_id="test",
            total_budget=5000.0,
            reallocation_strategy="winner_takes_more",
            optimization_frequency="hourly",
            period="weekly",
        )
        assert plan.reallocation_strategy == "winner_takes_more"
        assert plan.optimization_frequency == "hourly"
        assert plan.period == "weekly"


class TestGetUpdatePlan:

    def test_get_existing(self, allocator):
        allocator.create_plan("test", 1000.0)
        plan = allocator.get_plan("test")
        assert plan is not None
        assert plan.total_budget == 1000.0

    def test_get_nonexistent(self, allocator):
        assert allocator.get_plan("nope") is None

    def test_update(self, allocator):
        allocator.create_plan("test", 1000.0)
        plan = allocator.update_plan("test", total_budget=2000.0, period="weekly")
        assert plan.total_budget == 2000.0
        assert plan.period == "weekly"

    def test_update_nonexistent(self, allocator):
        assert allocator.update_plan("nope", total_budget=100.0) is None


class TestRecordAction:

    def test_records_metrics(self, allocator):
        allocator.record_action("test", "email", cost=5.0, success=True)
        perf = allocator.get_channel_performance("test", "email")
        assert perf.total_actions == 1
        assert perf.successful_actions == 1
        assert perf.total_spend == 5.0
        assert perf.first_action_at is not None

    def test_failed_action(self, allocator):
        allocator.record_action("test", "email", cost=2.0, success=False)
        perf = allocator.get_channel_performance("test", "email")
        assert perf.total_actions == 1
        assert perf.successful_actions == 0
        assert perf.total_spend == 2.0

    def test_multiple_actions(self, allocator):
        allocator.record_action("test", "email", cost=3.0, success=True)
        allocator.record_action("test", "email", cost=4.0, success=True)
        allocator.record_action("test", "email", cost=2.0, success=False)
        perf = allocator.get_channel_performance("test", "email")
        assert perf.total_actions == 3
        assert perf.successful_actions == 2
        assert perf.total_spend == 9.0

    def test_updates_plan_spent(self, allocator):
        allocator.create_plan(
            "test", 1000.0, channel_allocations={"email": 500.0}
        )
        allocator.record_action("test", "email", cost=50.0)
        plan = allocator.get_plan("test")
        assert plan.channel_budgets["email"].spent == 50.0
        assert plan.channel_budgets["email"].remaining == 450.0


class TestRecordConversion:

    def test_basic_conversion(self, allocator):
        allocator.record_action("test", "email", cost=10.0, success=True)
        allocator.record_conversion("test", "email")
        perf = allocator.get_channel_performance("test", "email")
        assert perf.conversions == 1
        assert perf.conversion_rate == 1.0
        assert perf.cac == 10.0
        assert perf.last_conversion_at is not None

    def test_cac_calculation(self, allocator):
        for _ in range(10):
            allocator.record_action("test", "email", cost=5.0, success=True)
        allocator.record_conversion("test", "email")
        allocator.record_conversion("test", "email")
        perf = allocator.get_channel_performance("test", "email")
        assert perf.cac == 25.0  # 50 / 2
        assert perf.conversion_rate == 0.2  # 2 / 10

    def test_zero_conversions_none_cac(self, allocator):
        allocator.record_action("test", "sms", cost=100.0, success=True)
        perf = allocator.get_channel_performance("test", "sms")
        assert perf.cac is None

    def test_conversion_rate_zero_on_no_success(self, allocator):
        allocator.record_action("test", "push", cost=5.0, success=False)
        allocator.record_conversion("test", "push")
        perf = allocator.get_channel_performance("test", "push")
        assert perf.conversion_rate == 0.0


class TestOptimize:

    def test_no_plan_returns_none(self, allocator):
        assert allocator.optimize("nope") is None

    def test_no_performance_data(self, allocator):
        allocator.create_plan("test", 1000.0)
        assert allocator.optimize("test") is None

    def test_proportional_reallocation(self, allocator):
        allocator.create_plan(
            "test",
            3000.0,
            channel_allocations={
                "email": 1000.0,
                "meta_ads": 1000.0,
                "google_ads": 1000.0,
            },
            channel_configs={
                "email": {"auto_pause_threshold": 100.0, "min_budget": 0.0},
                "meta_ads": {"auto_pause_threshold": 100.0, "min_budget": 0.0},
                "google_ads": {"auto_pause_threshold": 100.0, "min_budget": 0.0},
            },
        )
        # email: CAC = $5 (good)
        for _ in range(20):
            allocator.record_action("test", "email", cost=5.0, success=True)
        for _ in range(20):
            allocator.record_conversion("test", "email")

        # meta_ads: CAC = $50 (ok)
        for _ in range(10):
            allocator.record_action("test", "meta_ads", cost=50.0, success=True)
        for _ in range(10):
            allocator.record_conversion("test", "meta_ads")

        # google_ads: CAC = $200 (over threshold), only 3 actions to leave remaining budget
        for _ in range(3):
            allocator.record_action("test", "google_ads", cost=200.0, success=True)
        for _ in range(3):
            allocator.record_conversion("test", "google_ads")

        event = allocator.optimize("test")
        assert event is not None
        assert isinstance(event, ReallocationEvent)

        plan = allocator.get_plan("test")
        assert plan.channel_budgets["google_ads"].status == "paused"
        assert plan.channel_budgets["email"].allocated_budget > 1000.0
        assert plan.channel_budgets["meta_ads"].allocated_budget > 1000.0

    def test_winner_takes_more(self, allocator):
        allocator.create_plan(
            "test",
            3000.0,
            channel_allocations={
                "email": 1000.0,
                "sms": 1000.0,
                "push": 1000.0,
            },
            reallocation_strategy="winner_takes_more",
            channel_configs={
                "email": {"auto_pause_threshold": 100.0},
                "sms": {"auto_pause_threshold": 100.0},
                "push": {"auto_pause_threshold": 100.0},
            },
        )
        for _ in range(10):
            allocator.record_action("test", "email", cost=5.0, success=True)
        for _ in range(10):
            allocator.record_conversion("test", "email")

        for _ in range(10):
            allocator.record_action("test", "sms", cost=20.0, success=True)
        for _ in range(10):
            allocator.record_conversion("test", "sms")

        for _ in range(5):
            allocator.record_action("test", "push", cost=200.0, success=True)
        for _ in range(5):
            allocator.record_conversion("test", "push")

        event = allocator.optimize("test")
        assert event is not None
        plan = allocator.get_plan("test")
        assert plan.channel_budgets["push"].status == "paused"

    def test_equal_opportunity(self, allocator):
        allocator.create_plan(
            "test",
            2000.0,
            channel_allocations={
                "email": 1000.0,
                "sms": 1000.0,
            },
            reallocation_strategy="equal_opportunity",
            channel_configs={
                "email": {"auto_pause_threshold": 10.0},
                "sms": {"auto_pause_threshold": 200.0},
            },
        )
        for _ in range(10):
            allocator.record_action("test", "email", cost=20.0, success=True)
        for _ in range(10):
            allocator.record_conversion("test", "email")

        for _ in range(5):
            allocator.record_action("test", "sms", cost=10.0, success=True)
        for _ in range(5):
            allocator.record_conversion("test", "sms")

        event = allocator.optimize("test")
        assert event is not None
        plan = allocator.get_plan("test")
        assert plan.channel_budgets["email"].status == "paused"
        assert plan.channel_budgets["sms"].allocated_budget > 1000.0

    def test_min_budget_prevents_premature_pause(self, allocator):
        allocator.create_plan(
            "test",
            1000.0,
            channel_allocations={"email": 500.0, "sms": 500.0},
            channel_configs={
                "email": {"auto_pause_threshold": 10.0, "min_budget": 200.0},
                "sms": {"auto_pause_threshold": 200.0},
            },
        )
        # email CAC = $50 (exceeds threshold) but only spent $50 (< min_budget $200)
        allocator.record_action("test", "email", cost=50.0, success=True)
        allocator.record_conversion("test", "email")

        allocator.record_action("test", "sms", cost=5.0, success=True)
        allocator.record_conversion("test", "sms")

        event = allocator.optimize("test")
        # email should NOT be paused because min_budget not met
        plan = allocator.get_plan("test")
        assert plan.channel_budgets["email"].status == "active"

    def test_idempotent_no_changes(self, allocator):
        allocator.create_plan(
            "test",
            1000.0,
            channel_allocations={"email": 500.0, "sms": 500.0},
            channel_configs={
                "email": {"auto_pause_threshold": 100.0},
                "sms": {"auto_pause_threshold": 100.0},
            },
        )
        # Both channels performing well
        for _ in range(10):
            allocator.record_action("test", "email", cost=5.0, success=True)
        for _ in range(10):
            allocator.record_conversion("test", "email")
        for _ in range(10):
            allocator.record_action("test", "sms", cost=8.0, success=True)
        for _ in range(10):
            allocator.record_conversion("test", "sms")

        assert allocator.optimize("test") is None

    def test_paused_plan_returns_none(self, allocator):
        allocator.create_plan("test", 1000.0)
        allocator.update_plan("test", status="paused")
        allocator.record_action("test", "email", cost=5.0, success=True)
        assert allocator.optimize("test") is None


class TestPauseResume:

    def test_pause(self, allocator):
        allocator.create_plan(
            "test", 1000.0, channel_allocations={"email": 500.0}
        )
        plan = allocator.pause_channel("test", "email")
        assert plan.channel_budgets["email"].status == "paused"

    def test_resume(self, allocator):
        allocator.create_plan(
            "test", 1000.0, channel_allocations={"email": 500.0}
        )
        allocator.pause_channel("test", "email")
        plan = allocator.resume_channel("test", "email")
        assert plan.channel_budgets["email"].status == "active"

    def test_pause_no_plan(self, allocator):
        assert allocator.pause_channel("nope", "email") is None

    def test_pause_no_channel(self, allocator):
        allocator.create_plan("test", 1000.0)
        assert allocator.pause_channel("test", "nonexistent") is None

    def test_resume_no_plan(self, allocator):
        assert allocator.resume_channel("nope", "email") is None


class TestRecommendation:

    def test_no_plan(self, allocator):
        result = allocator.get_recommendation("nope")
        assert result["recommendation"] is None

    def test_no_data(self, allocator):
        allocator.create_plan("test", 1000.0)
        result = allocator.get_recommendation("test")
        assert result["recommendation"] is None

    def test_with_data(self, allocator):
        allocator.create_plan(
            "test",
            2000.0,
            channel_allocations={"email": 1000.0, "sms": 1000.0},
            channel_configs={
                "email": {"auto_pause_threshold": 10.0},
                "sms": {"auto_pause_threshold": 200.0},
            },
        )
        for _ in range(10):
            allocator.record_action("test", "email", cost=20.0, success=True)
        for _ in range(10):
            allocator.record_conversion("test", "email")
        for _ in range(5):
            allocator.record_action("test", "sms", cost=5.0, success=True)
        for _ in range(5):
            allocator.record_conversion("test", "sms")

        result = allocator.get_recommendation("test")
        assert result["would_reallocate"] is True
        assert len(result["channels_to_pause"]) == 1
        assert result["channels_to_pause"][0]["channel"] == "email"


class TestReallocationHistory:

    def test_empty_history(self, allocator):
        assert allocator.get_reallocation_history("test") == []

    def test_history_after_optimize(self, allocator):
        allocator.create_plan(
            "test",
            2000.0,
            channel_allocations={"email": 1000.0, "sms": 1000.0},
            channel_configs={
                "email": {"auto_pause_threshold": 10.0},
                "sms": {"auto_pause_threshold": 200.0},
            },
        )
        for _ in range(10):
            allocator.record_action("test", "email", cost=20.0, success=True)
        for _ in range(10):
            allocator.record_conversion("test", "email")
        for _ in range(5):
            allocator.record_action("test", "sms", cost=5.0, success=True)
        for _ in range(5):
            allocator.record_conversion("test", "sms")

        allocator.optimize("test")
        history = allocator.get_reallocation_history("test")
        assert len(history) == 1
        assert history[0].trigger == "auto"
        assert len(history[0].changes) > 0


class TestPerformanceTrend:

    def test_improving_trend(self, allocator):
        for i in range(5):
            allocator.record_action("test", "email", cost=1.0, success=True)
            if i >= 2:
                allocator.record_conversion("test", "email")

        perf = allocator.get_channel_performance("test", "email")
        assert perf.performance_trend in ("improving", "stable")

    def test_stable_on_few_samples(self, allocator):
        allocator.record_action("test", "email", cost=1.0, success=True)
        allocator.record_conversion("test", "email")
        perf = allocator.get_channel_performance("test", "email")
        assert perf.performance_trend == "stable"


class TestGetPerformance:

    def test_all_channels(self, allocator):
        allocator.record_action("test", "email", cost=5.0)
        allocator.record_action("test", "sms", cost=3.0)
        perf = allocator.get_performance("test")
        assert "email" in perf
        assert "sms" in perf
        assert len(perf) == 2

    def test_empty(self, allocator):
        assert allocator.get_performance("nope") == {}

    def test_single_channel(self, allocator):
        allocator.record_action("test", "email", cost=5.0)
        perf = allocator.get_channel_performance("test", "email")
        assert perf is not None
        assert perf.channel == "email"

    def test_single_channel_not_found(self, allocator):
        assert allocator.get_channel_performance("test", "nope") is None


class TestStats:

    def test_empty(self, allocator):
        s = allocator.stats()
        assert s["total_plans"] == 0
        assert s["total_spend"] == 0
        assert s["total_conversions"] == 0

    def test_with_data(self, allocator):
        allocator.create_plan("p1", 1000.0)
        allocator.create_plan("p2", 2000.0)
        allocator.update_plan("p2", status="paused")
        allocator.record_action("p1", "email", cost=50.0)
        allocator.record_conversion("p1", "email")
        s = allocator.stats()
        assert s["total_plans"] == 2
        assert s["active_plans"] == 1
        assert s["total_spend"] == 50.0
        assert s["total_conversions"] == 1
        assert s["total_channels_tracked"] == 1


class TestChannelBudgetRemaining:

    def test_remaining_property(self):
        cb = ChannelBudget(channel="email", allocated_budget=500.0, spent=200.0)
        assert cb.remaining == 300.0

    def test_remaining_zero(self):
        cb = ChannelBudget(channel="email", allocated_budget=100.0, spent=150.0)
        assert cb.remaining == 0.0


class TestChannelEnum:

    def test_values(self):
        assert Channel.EMAIL == "email"
        assert Channel.META_ADS == "meta_ads"
        assert Channel.REFERRAL == "referral"
        assert Channel.ORGANIC == "organic"
