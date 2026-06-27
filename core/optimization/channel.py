"""
Channel Optimizer

Selects the best communication channel based on the identity's response rates.

Uses communication preference data from the behavioral profile:
- preferred_channel
- email_open_rate / email_click_rate
- push_open_rate
- sms_response_rate
- unsubscribed_channels

Can override the channel field on a Decision if the policy allows flexibility.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from core.behavior.schema import BehavioralProfile
from core.decision.schema import ActionType, Decision

COMM_ACTION_TYPES = {
    ActionType.SEND_EMAIL,
    ActionType.SEND_PUSH,
    ActionType.SEND_SMS,
    ActionType.SEND_WHATSAPP,
    ActionType.SEND_IN_APP,
}

CHANNEL_ACTION_MAP = {
    "email": ActionType.SEND_EMAIL,
    "push": ActionType.SEND_PUSH,
    "sms": ActionType.SEND_SMS,
    "whatsapp": ActionType.SEND_WHATSAPP,
    "in_app": ActionType.SEND_IN_APP,
}


class ChannelOptimizer:

    def optimize_channel(
        self,
        decision: Decision,
        profile: BehavioralProfile,
    ) -> Decision:
        if decision.action_type not in COMM_ACTION_TYPES:
            return decision

        if decision.channel and decision.payload.get("channel_locked"):
            return decision

        ranked = self.rank_channels(profile)
        if not ranked:
            return decision

        best_channel, _ = ranked[0]
        action_type = CHANNEL_ACTION_MAP.get(best_channel)
        if action_type:
            decision.channel = best_channel
            decision.action_type = action_type

        return decision

    def rank_channels(
        self,
        profile: BehavioralProfile,
    ) -> List[Tuple[str, float]]:
        comm = profile.communication
        unsubscribed = set(comm.unsubscribed_channels)

        scores: List[Tuple[str, float]] = []

        if "email" not in unsubscribed:
            email_score = max(comm.email_open_rate, comm.email_click_rate)
            scores.append(("email", email_score))

        if "push" not in unsubscribed:
            scores.append(("push", comm.push_open_rate))

        if "sms" not in unsubscribed:
            scores.append(("sms", comm.sms_response_rate))

        if "whatsapp" not in unsubscribed:
            scores.append(("whatsapp", 0.0))

        if "in_app" not in unsubscribed:
            scores.append(("in_app", 0.0))

        if comm.preferred_channel and comm.preferred_channel not in unsubscribed:
            scores = [
                (ch, score + (0.1 if ch == comm.preferred_channel else 0.0))
                for ch, score in scores
            ]

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores
