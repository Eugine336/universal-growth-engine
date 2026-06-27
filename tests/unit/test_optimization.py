"""Tests for the optimization layer (send-time + channel)."""

import pytest
from datetime import datetime, timedelta, timezone

from core.optimization.send_time import SendTimeOptimizer
from core.optimization.channel import ChannelOptimizer
from core.action.schema import Action
from core.behavior.schema import (
    BehavioralProfile,
    CommunicationPreference,
    EngagementProfile,
    RFMScore,
)
from core.decision.schema import Decision, ActionType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_profile(
    best_hour=None,
    best_day=None,
    preferred_channel=None,
    email_open_rate=0.0,
    push_open_rate=0.0,
    sms_response_rate=0.0,
    unsubscribed=None,
):
    return BehavioralProfile(
        identity_id="identity_001",
        application_id="ucmc",
        communication=CommunicationPreference(
            best_hour=best_hour,
            best_day=best_day,
            preferred_channel=preferred_channel,
            email_open_rate=email_open_rate,
            push_open_rate=push_open_rate,
            sms_response_rate=sms_response_rate,
            unsubscribed_channels=unsubscribed or [],
        ),
    )


def _make_action(action_type="SEND_EMAIL"):
    return Action(
        decision_id="dec_001",
        identity_id="identity_001",
        application_id="ucmc",
        action_type=action_type,
        payload={"template": "test"},
    )


def _make_decision(action_type=ActionType.SEND_EMAIL, channel="email"):
    return Decision(
        identity_id="identity_001",
        application_id="ucmc",
        action_type=action_type,
        channel=channel,
        payload={},
    )


# ---------------------------------------------------------------------------
# Send-Time Optimizer Tests
# ---------------------------------------------------------------------------

class TestSendTimeOptimizer:

    def test_delays_action_to_best_hour(self):
        optimizer = SendTimeOptimizer()
        profile = _make_profile(best_hour=10)
        now = datetime(2026, 6, 27, 15, 0, 0, tzinfo=timezone.utc)

        action = _make_action()
        result = optimizer.optimize(action, profile, now=now)

        assert result.execute_after is not None
        assert result.execute_after.hour == 10

    def test_no_delay_when_current_is_best_hour_with_day(self):
        optimizer = SendTimeOptimizer()
        now = datetime(2026, 6, 27, 10, 30, 0, tzinfo=timezone.utc)
        profile = _make_profile(best_hour=10, best_day="Saturday")

        action = _make_action()
        result = optimizer.optimize(action, profile, now=now)

        assert result.execute_after is not None
        assert result.execute_after.weekday() == 5  # Saturday

    def test_no_optimization_when_no_engagement_data(self):
        optimizer = SendTimeOptimizer()
        profile = _make_profile()

        action = _make_action()
        result = optimizer.optimize(action, profile)

        assert result.execute_after is None

    def test_no_optimization_for_non_comm_action(self):
        optimizer = SendTimeOptimizer()
        profile = _make_profile(best_hour=10)

        action = _make_action(action_type="SHOW_UPSELL")
        result = optimizer.optimize(action, profile)

        assert result.execute_after is None

    def test_next_optimal_time_returns_none_without_data(self):
        optimizer = SendTimeOptimizer()
        profile = _make_profile()

        result = optimizer.next_optimal_time(profile)
        assert result is None

    def test_next_optimal_time_advances_day_if_hour_passed(self):
        optimizer = SendTimeOptimizer()
        profile = _make_profile(best_hour=8)
        now = datetime(2026, 6, 27, 12, 0, 0, tzinfo=timezone.utc)

        result = optimizer.next_optimal_time(profile, now=now)
        assert result is not None
        assert result.hour == 8
        assert result.day == 28

    def test_next_optimal_time_with_best_day(self):
        optimizer = SendTimeOptimizer()
        profile = _make_profile(best_hour=9, best_day="Monday")
        now = datetime(2026, 6, 27, 10, 0, 0, tzinfo=timezone.utc)  # Saturday

        result = optimizer.next_optimal_time(profile, now=now)
        assert result is not None
        assert result.weekday() == 0  # Monday

    def test_next_optimal_time_same_day_if_not_passed(self):
        optimizer = SendTimeOptimizer()
        profile = _make_profile(best_hour=18)
        now = datetime(2026, 6, 27, 10, 0, 0, tzinfo=timezone.utc)

        result = optimizer.next_optimal_time(profile, now=now)
        assert result is not None
        assert result.hour == 18
        assert result.day == 27


# ---------------------------------------------------------------------------
# Channel Optimizer Tests
# ---------------------------------------------------------------------------

class TestChannelOptimizer:

    def test_selects_preferred_channel(self):
        optimizer = ChannelOptimizer()
        profile = _make_profile(
            preferred_channel="push",
            email_open_rate=0.2,
            push_open_rate=0.3,
        )
        decision = _make_decision()
        result = optimizer.optimize_channel(decision, profile)

        assert result.channel == "push"
        assert result.action_type == ActionType.SEND_PUSH

    def test_unsubscribed_channels_excluded(self):
        optimizer = ChannelOptimizer()
        profile = _make_profile(
            preferred_channel="email",
            email_open_rate=0.5,
            push_open_rate=0.1,
            unsubscribed=["email"],
        )
        decision = _make_decision()
        result = optimizer.optimize_channel(decision, profile)

        assert result.channel != "email"

    def test_channel_ranking_order(self):
        optimizer = ChannelOptimizer()
        profile = _make_profile(
            email_open_rate=0.4,
            push_open_rate=0.6,
            sms_response_rate=0.2,
        )
        ranked = optimizer.rank_channels(profile)

        assert ranked[0][0] == "push"
        assert ranked[1][0] == "email"
        assert ranked[2][0] == "sms"

    def test_channel_locked_skips_optimization(self):
        optimizer = ChannelOptimizer()
        profile = _make_profile(push_open_rate=0.9)
        decision = _make_decision(channel="email")
        decision.payload["channel_locked"] = True

        result = optimizer.optimize_channel(decision, profile)
        assert result.channel == "email"

    def test_non_comm_action_skips_optimization(self):
        optimizer = ChannelOptimizer()
        profile = _make_profile(push_open_rate=0.9)
        decision = _make_decision(
            action_type=ActionType.SHOW_UPSELL, channel=None,
        )
        result = optimizer.optimize_channel(decision, profile)
        assert result.action_type == ActionType.SHOW_UPSELL

    def test_rank_channels_with_all_unsubscribed(self):
        optimizer = ChannelOptimizer()
        profile = _make_profile(
            unsubscribed=["email", "push", "sms", "whatsapp", "in_app"],
        )
        ranked = optimizer.rank_channels(profile)
        assert ranked == []

    def test_preferred_channel_gets_boost(self):
        optimizer = ChannelOptimizer()
        profile = _make_profile(
            preferred_channel="sms",
            email_open_rate=0.3,
            sms_response_rate=0.25,
        )
        ranked = optimizer.rank_channels(profile)
        sms_entry = next(r for r in ranked if r[0] == "sms")
        assert sms_entry[1] == 0.35  # 0.25 + 0.1 boost
